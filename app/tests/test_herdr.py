import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts app/ on sys.path)

import herdr

SPECIFICATION = {"story": "E8S1", "title": "Manage products"}
SPACE = {"name": "ETC Online", "path": "/repo"}
SESSION = Path("/repo/.flow/sessions/E8S1")
PERSONA = {"name": "Engineer", "role": "You are the Engineer.", "task": "Implement the specification.", "model": None}


class FakeHerdrApp:
    """Answers `ls` with the given spaces and records every `do` command."""

    def __init__(self, spaces: list[dict], fail: str | None = None):
        self.spaces = spaces
        self.fail = fail
        self.commands: list[tuple[str, dict]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        if args[0] == "ls":
            return subprocess.CompletedProcess(args, 0, json.dumps({"spaces": self.spaces}), "")
        command, payload = args[1], json.loads(args[2])
        self.commands.append((command, payload))
        if command == self.fail:
            return subprocess.CompletedProcess(args, 1, json.dumps({"error": "nope"}), "")
        return subprocess.CompletedProcess(args, 0, json.dumps({"ok": True}), "")


class FakeHc:
    """Answers `hc get` with the next of `states` (the last one repeats); records every call.

    A state `finished` is a terminal that has ended. `hc send` answers with an error when `send_fails`.
    """

    def __init__(self, states: list[str], send_fails: bool = False):
        self.states = list(states)
        self.send_fails = send_fails
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        code, payload = 0, {"ended": True, "reason": "status"}
        if args[0] == "get":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            payload = {"state": "finished"} if state == "finished" else {"state": "live", "status": {"app": "omp", "state": state}}
        elif args[0] == "send" and self.send_fails:
            code, payload = 3, {"error": {"kind": "not_idle", "message": "not idle"}}
        return subprocess.CompletedProcess(args, code, json.dumps(payload), "")

    def commands(self) -> list[str]:
        return [args[0] for args in self.calls]


class FakeClock:
    """A monotonic clock that moves `step` seconds on every read."""

    def __init__(self, step: float):
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def space(tabs: list[str], working: frozenset[str] = frozenset()) -> dict:
    """A herdr-app space with one terminal per tab, `working` for the tabs named in `working`."""
    return {
        "id": "sp1",
        "name": "ETC Online",
        "tabs": [
            {"id": f"tb-{name}", "name": name, "terminals": [{"status": "working" if name in working else "idle"}]}
            for name in tabs
        ],
    }


class StartSessionTest(unittest.TestCase):
    def test_new_tab_in_the_herdr_space_of_the_space(self) -> None:
        app = FakeHerdrApp([space(["1"])])

        result = herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)

        self.assertEqual(result["result"], "started")
        command, payload = app.commands[0]
        self.assertEqual(command, "tab.new")
        self.assertEqual(payload["space"], "sp1")
        self.assertEqual(payload["name"], "E8S1 · Engineer")
        self.assertEqual(payload["folder"], "/repo")
        self.assertEqual(payload["argv"], ["omp", "--append-system-prompt", "You are the Engineer.", "--session-dir", str(SESSION)])
        self.assertEqual(payload["task"], "Implement the specification.")

    def test_new_herdr_space_when_the_space_has_none(self) -> None:
        app = FakeHerdrApp([{"id": "x", "name": "Other", "tabs": []}])

        herdr.start_session(SPECIFICATION, SPACE, {**PERSONA, "model": "opus"}, SESSION, app)

        command, payload = app.commands[0]
        self.assertEqual(command, "space.new")
        self.assertEqual(payload["name"], "ETC Online")
        self.assertEqual(payload["tab"], "E8S1 · Engineer")
        self.assertEqual(payload["argv"][3:5], ["--model", "opus"])

    def test_open_tab_is_selected_instead_of_started_again(self) -> None:
        app = FakeHerdrApp([space(["1", "E8S1 · Engineer"])])

        result = herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)

        self.assertEqual(result["result"], "already_running")
        self.assertEqual(app.commands, [("tab.select", {"id": "tb-E8S1 · Engineer"})])

    def test_idle_tab_of_another_persona_is_closed_before_the_new_tab_opens(self) -> None:
        app = FakeHerdrApp([space(["1", "E8S1 · Analyst"])])

        result = herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)

        self.assertEqual(result, {"result": "started", "space": "ETC Online", "tab": "E8S1 · Engineer"})
        self.assertEqual(app.commands[0], ("tab.close", {"id": "tb-E8S1 · Analyst", "confirmed": True}))
        command, payload = app.commands[1]
        self.assertEqual(command, "tab.new")
        self.assertEqual(payload["name"], "E8S1 · Engineer")
        self.assertEqual(len(app.commands), 2)

    def test_tab_with_the_old_name_is_closed(self) -> None:
        app = FakeHerdrApp([space(["1", "E8S1"])])

        herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)

        self.assertEqual(
            [(command, payload.get("id")) for command, payload in app.commands],
            [("tab.close", "tb-E8S1"), ("tab.new", None)],
        )

    def test_new_herdr_space_when_closing_empties_the_space(self) -> None:
        app = FakeHerdrApp([space(["E8S1", "E8S1 · Analyst"])])

        result = herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)

        self.assertEqual(result, {"result": "started", "space": "ETC Online", "tab": "E8S1 · Engineer"})
        self.assertEqual([command for command, _ in app.commands], ["tab.close", "tab.close", "space.new"])
        _, payload = app.commands[-1]
        self.assertEqual(payload["name"], "ETC Online")
        self.assertEqual(payload["tab"], "E8S1 · Engineer")
        self.assertEqual(payload["folder"], "/repo")

    def test_working_tab_of_another_persona_blocks_the_start(self) -> None:
        app = FakeHerdrApp([space(["1", "E8S1 · Analyst"], working=frozenset({"E8S1 · Analyst"}))])

        with self.assertRaisesRegex(herdr.TabBusy, "E8S1 · Analyst in ETC Online"):
            herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)
        self.assertEqual(app.commands, [])

    def test_working_tab_with_the_old_name_blocks_the_start(self) -> None:
        app = FakeHerdrApp([space(["E8S1"], working=frozenset({"E8S1"}))])

        with self.assertRaises(herdr.TabBusy):
            herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)
        self.assertEqual(app.commands, [])

    def test_tabs_of_other_stories_do_not_match(self) -> None:
        others = ["E8S10 · Analyst", "E8S10", "E8S1x", "E8S · Analyst"]
        app = FakeHerdrApp([space(others, working=frozenset(others))])

        result = herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)

        self.assertEqual(result["result"], "started")
        self.assertEqual([command for command, _ in app.commands], ["tab.new"])

    def test_open_tab_stays_selected_next_to_a_matching_tab(self) -> None:
        tabs = ["E8S1 · Analyst", "E8S1 · Engineer"]
        app = FakeHerdrApp([space(tabs, working=frozenset({"E8S1 · Analyst"}))])

        result = herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)

        self.assertEqual(result["result"], "already_running")
        self.assertEqual(app.commands, [("tab.select", {"id": "tb-E8S1 · Engineer"})])

    def test_refusal_from_herdr_app_is_raised(self) -> None:
        app = FakeHerdrApp([space([])], fail="tab.new")
        with self.assertRaises(herdr.HerdrError):
            herdr.start_session(SPECIFICATION, SPACE, PERSONA, SESSION, app)


PRODUCT_OWNER = {"name": "Product Owner", "role": "You break ideas down.", "task": "What is your idea?", "model": None}


class StartProductOwnerTest(unittest.TestCase):
    def test_new_herdr_space_when_the_space_has_none(self) -> None:
        app = FakeHerdrApp([{"id": "x", "name": "Other", "tabs": []}])

        result = herdr.start_product_owner(SPACE, PRODUCT_OWNER, app)

        self.assertEqual(result, {"result": "started", "space": "ETC Online", "tab": "Product Owner"})
        self.assertEqual(app.commands, [("space.new", {
            "name": "ETC Online", "tab": "Product Owner", "folder": "/repo",
            "argv": ["omp", "--append-system-prompt", "You break ideas down."], "task": "What is your idea?",
        })])

    def test_new_tab_next_to_story_tabs_which_stay_open(self) -> None:
        tabs = ["E8S1 · Analyst", "E8S1", "1"]
        app = FakeHerdrApp([space(tabs, working=frozenset(tabs))])

        result = herdr.start_product_owner(SPACE, {**PRODUCT_OWNER, "model": "opus"}, app)

        self.assertEqual(result, {"result": "started", "space": "ETC Online", "tab": "Product Owner"})
        self.assertEqual([command for command, _ in app.commands], ["tab.new"])
        _, payload = app.commands[0]
        self.assertEqual((payload["space"], payload["name"]), ("sp1", "Product Owner"))
        self.assertEqual(payload["argv"], ["omp", "--append-system-prompt", "You break ideas down.", "--model", "opus"])

    def test_open_tab_is_selected(self) -> None:
        app = FakeHerdrApp([space(["E8S1 · Analyst", "Product Owner"])])

        result = herdr.start_product_owner(SPACE, PRODUCT_OWNER, app)

        self.assertEqual(result["result"], "already_running")
        self.assertEqual(app.commands, [("tab.select", {"id": "tb-Product Owner"})])

    def test_a_story_never_matches_the_product_owner_tab(self) -> None:
        self.assertEqual(herdr.story_tabs(space(["Product Owner"])["tabs"], SPECIFICATION), [])


class CloseStoryTest(unittest.TestCase):
    def test_closes_every_tab_of_the_story_and_no_other(self) -> None:
        app = FakeHerdrApp([space(["1", "E8S1", "E8S1 · Analyst", "E8S1 · Engineer", "E8S10 · Engineer"])])

        closed = herdr.close_story(SPECIFICATION, SPACE, app)

        self.assertEqual([tab["name"] for tab in closed], ["E8S1", "E8S1 · Analyst", "E8S1 · Engineer"])
        self.assertEqual(app.commands, [
            ("tab.close", {"id": f"tb-{name}", "confirmed": True}) for name in ("E8S1", "E8S1 · Analyst", "E8S1 · Engineer")
        ])

    def test_a_working_tab_of_the_story_closes_nothing(self) -> None:
        app = FakeHerdrApp([space(["E8S1 · Analyst", "E8S1 · Engineer"], working=frozenset({"E8S1 · Engineer"}))])

        with self.assertRaisesRegex(herdr.TabBusy, "E8S1 · Engineer in ETC Online"):
            herdr.close_story(SPECIFICATION, SPACE, app)
        self.assertEqual(app.commands, [])

    def test_without_the_herdr_space_there_is_nothing_to_close(self) -> None:
        app = FakeHerdrApp([{"id": "x", "name": "Other", "tabs": []}])
        self.assertEqual(herdr.close_story(SPECIFICATION, SPACE, app), [])
        self.assertEqual(app.commands, [])

    def test_waits_until_the_programs_of_the_closed_tabs_have_ended(self) -> None:
        tabs = [{"terminals": [{"terminal": "t1"}, {"status": "idle"}]}, {"terminals": [{"terminal": "t2"}]}]
        self.assertEqual(herdr.tab_terminals(tabs), ["t1", "t2"])

        hc, slept = FakeHc(["done", "finished", "finished"]), []
        herdr.wait_finished(["t1", "t2"], 10, hc, sleep=slept.append, clock=FakeClock(1))
        self.assertEqual(([args[1] for args in hc.calls], len(slept)), (["t1", "t1", "t2"], 1))

        with self.assertRaisesRegex(herdr.HerdrError, "t1 has not ended 10 seconds after its tab closed"):
            herdr.wait_finished(["t1"], 10, FakeHc(["done"]), sleep=lambda _: None, clock=FakeClock(4))


class TerminalTest(unittest.TestCase):
    def test_status_is_the_agent_state_or_finished(self) -> None:
        self.assertEqual(herdr.terminal_status("t7", FakeHc(["blocked"])), "blocked")
        self.assertEqual(herdr.terminal_status("t7", FakeHc(["finished"])), "finished")

    def test_waits_through_working_and_blocked_until_idle(self) -> None:
        hc, slept = FakeHc(["working", "blocked", "idle"]), []

        state = herdr.wait_terminal("t7", 1800, hc, sleep=slept.append, clock=FakeClock(1))

        self.assertEqual(state, "idle")
        self.assertEqual(hc.commands(), ["get", "wait", "get", "get"])
        self.assertEqual(hc.calls[1], ["wait", "t7", "--json", "--timeout", "60"])
        self.assertEqual(slept, [herdr.BLOCKED_POLL_SECONDS])

    def test_a_finished_terminal_ends_the_wait(self) -> None:
        self.assertEqual(herdr.wait_terminal("t7", 1800, FakeHc(["working", "finished"]), clock=FakeClock(1)), "finished")

    def test_gives_up_after_the_timeout(self) -> None:
        hc = FakeHc(["working"])
        with self.assertRaisesRegex(herdr.HerdrError, "t7 is still working after 30 minutes"):
            herdr.wait_terminal("t7", 1800, hc, sleep=lambda _: None, clock=FakeClock(400))
        self.assertIn("wait", hc.commands())

    def test_send_types_only_when_the_agent_waits_for_input(self) -> None:
        for state in ("idle", "done", "error"):
            hc = FakeHc([state])
            herdr.send_if_idle("t7", "Hello", hc)
            self.assertEqual(hc.calls[-1], ["send", "--json", "t7", "Hello"])
        for state in ("working", "blocked", "finished"):
            hc = FakeHc([state])
            with self.assertRaisesRegex(herdr.HerdrError, f"t7 is {state}; nothing was typed"):
                herdr.send_if_idle("t7", "Hello", hc)
            self.assertEqual(hc.commands(), ["get"])

    def test_a_send_hc_refuses_is_an_error(self) -> None:
        with self.assertRaisesRegex(herdr.HerdrError, "hc send --json: not idle"):
            herdr.send_if_idle("t7", "Hello", FakeHc(["done"], send_fails=True))

    def test_waits_until_herdr_app_no_longer_shows_the_terminal_working(self) -> None:
        def app_showing(states: list[str]) -> FakeHerdrApp:
            app = FakeHerdrApp([])
            calls = iter(states)

            def ls(args: list[str]) -> subprocess.CompletedProcess:
                status = next(calls, states[-1])
                app.spaces = [{"id": "sp1", "name": "ETC Online", "tabs": [
                    {"id": "tb1", "name": "E8S1 · Analyst", "terminals": [{"terminal": "t7", "status": status}]},
                    {"id": "tb2", "name": "E8S2 · Analyst", "terminals": [{"terminal": "t8", "status": "working"}]},
                ]}]
                return FakeHerdrApp.__call__(app, args)
            return ls

        slept: list[float] = []
        herdr.wait_app_settled("t7", 60, app_showing(["working", "working", "done"]), sleep=slept.append, clock=FakeClock(1))
        self.assertEqual(slept, [1, 1])

        with self.assertRaisesRegex(herdr.HerdrError, "herdr-app still shows t7 as working after 60 seconds"):
            herdr.wait_app_settled("t7", 60, app_showing(["working"]), sleep=lambda _: None, clock=FakeClock(40))



class AgentArgvTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.session = Path(self._dir.name) / "E8S1"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_new_session_folder_starts_a_new_session(self) -> None:
        self.assertEqual(herdr.agent_argv(PERSONA, self.session)[-2:], ["--session-dir", str(self.session)])
        self.session.mkdir()
        (self.session / "notes.txt").write_text("not a session")
        self.assertNotIn("--continue", herdr.agent_argv(PERSONA, self.session))

    def test_a_folder_with_a_session_continues_it_with_the_new_role_and_model(self) -> None:
        self.session.mkdir()
        (self.session / "2026-11-09_abc.jsonl").write_text("{}\n")

        argv = herdr.agent_argv({**PERSONA, "model": "opus"}, self.session)

        self.assertEqual(argv, [
            "omp", "--append-system-prompt", "You are the Engineer.", "--model", "opus",
            "--session-dir", str(self.session), "--continue",
        ])


if __name__ == "__main__":
    unittest.main()
