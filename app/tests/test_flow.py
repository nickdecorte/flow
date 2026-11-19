import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import Root
from test_herdr import FakeClock, FakeHc, FakeHerdrApp

import flow
import herdr
import sdlc
import session

FLOW = Path(__file__).resolve().parent.parent / "flow.py"
ENGINEER = "---\nname: Engineer\nmodel:\n---\n\n## Role\nEngineer\n\n## Start\nImplement {{story_id}} (from {{from}})\n"


class FlowStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([
            {"id": "E1S1", "title": "With", "status": "in-analysis"},
            {"id": "E1S2", "title": "Without", "status": "waiting-for-analysis"},
        ])
        self.root.specification("E1S1", "with.md", "With")

    def tearDown(self) -> None:
        self.root.cleanup()

    def run_flow(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(FLOW), "status", str(self.folder), *args], capture_output=True, text=True)

    def statuses(self) -> dict:
        data = json.loads(self.root.config().read_text(encoding="utf-8"))
        return {s["id"]: s["status"] for e in data["epics"] for s in e["stories"]}

    def test_sets_a_valid_status(self) -> None:
        result = self.run_flow("E1S1", "in-development")

        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, "E1S1: in-analysis → in-development", ""))
        self.assertEqual(self.statuses(), {"E1S1": "in-development", "E1S2": "waiting-for-analysis"})

    def test_a_story_without_specification_may_go_to_done(self) -> None:
        self.assertEqual(self.run_flow("E1S2", "done").returncode, 0)
        self.assertEqual(self.statuses()["E1S2"], "done")

    def test_refusals_exit_1_with_a_message_and_leave_the_file(self) -> None:
        before = self.root.config().read_bytes()
        cases = {
            "unknown status": ("E1S1", "needs-analysis"),
            "unknown story": ("E1S9", "todo"),
            "waiting-for-analysis with specification": ("E1S1", "waiting-for-analysis"),
            "in-development without specification": ("E1S2", "in-development"),
        }
        for name, args in cases.items():
            with self.subTest(name):
                result = self.run_flow(*args)
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertIn(args[0] if name != "unknown status" else "needs-analysis", result.stderr)
        self.assertEqual(self.root.config().read_bytes(), before)

    def test_a_path_without_config_exits_1(self) -> None:
        result = subprocess.run([sys.executable, str(FLOW), "status", str(self.root.path / "nowhere"), "E1S1", "todo"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("config.json", result.stderr)


class FlowReadyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([
            {"id": "E1S1", "title": "Analysing"},
            {"id": "E1S2", "title": "Building"},
            {"id": "E1S3", "title": "Reviewing"},
            {"id": "E1S4", "title": "Planned"},
            {"id": "E1S5", "title": "Closed"},
            {"id": "E1S6", "title": "Without", "status": "waiting-for-analysis"},
        ])
        for story, status in (("E1S1", "in-analysis"), ("E1S2", "in-development"), ("E1S3", "in-review"),
                              ("E1S4", "todo"), ("E1S5", "done")):
            self.root.specification(story, f"{story}.md", story, status=status)

    def tearDown(self) -> None:
        self.root.cleanup()

    def run_flow(self, command: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(FLOW), command, str(self.folder), *args], capture_output=True, text=True)

    def stories(self) -> dict:
        data = json.loads(self.root.config().read_text(encoding="utf-8"))
        return {s["id"]: s for e in data["epics"] for s in e["stories"]}

    def test_marks_a_story_on_every_persona_column_ready(self) -> None:
        for story in ("E1S1", "E1S2", "E1S3"):
            with self.subTest(story):
                result = self.run_flow("ready", story)
                self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, f"{story}: ready", ""))
                self.assertIs(self.stories()[story]["ready"], True)
        ready = {s["story"]: s["ready"] for s in sdlc.load_state(self.root.path)["specifications"]}
        self.assertEqual(ready, {"E1S1": True, "E1S2": True, "E1S3": True, "E1S4": False, "E1S5": False})

    def test_ready_twice_changes_nothing(self) -> None:
        self.run_flow("ready", "E1S1")
        before = self.root.config().read_bytes()

        self.assertEqual(self.run_flow("ready", "E1S1").returncode, 0)
        self.assertEqual(self.root.config().read_bytes(), before)

    def test_refuses_todo_done_no_specification_and_unknown_story(self) -> None:
        before = self.root.config().read_bytes()
        for story in ("E1S4", "E1S5", "E1S6", "E1S9"):
            with self.subTest(story):
                result = self.run_flow("ready", story)
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertIn(story, result.stderr)
        self.assertEqual(self.root.config().read_bytes(), before)

    def test_a_status_change_clears_ready(self) -> None:
        self.run_flow("ready", "E1S1")

        self.assertEqual(self.run_flow("status", "E1S1", "in-development").returncode, 0)
        self.assertNotIn("ready", self.stories()["E1S1"])


class NextCase(unittest.TestCase):
    """A space with ready and unready stories on persona columns, one without specification, and an Engineer."""

    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([
            {"id": "E1S1", "title": "Ready"},
            {"id": "E1S2", "title": "Analysing"},
            {"id": "E1S3", "title": "Reviewable"},
            {"id": "E1S4", "title": "Without", "status": "waiting-for-analysis"},
            {"id": "E1S5", "title": "Reviewing"},
        ])
        self.root.specification("E1S1", "ready.md", "Ready", status="in-analysis")
        self.root.specification("E1S2", "analysing.md", "Analysing", status="in-analysis")
        self.root.specification("E1S3", "reviewable.md", "Reviewable", status="in-development")
        self.root.specification("E1S5", "reviewing.md", "Reviewing", status="in-review")
        for story in ("E1S1", "E1S3", "E1S5"):
            sdlc.set_story_ready(self.root.config(), story)
        self.root.persona("in-development", ENGINEER)
        self.app = FakeHerdrApp([{"id": "sp1", "name": "Demo", "tabs": [
            {"id": "tb0", "name": "1", "terminals": [{"status": "idle"}]},
            {"id": "tb1", "name": "E1S1 · Analyst", "terminals": [{"status": "idle"}]},
        ]}])
        self.spawned: list[tuple[list[str], Path]] = []

    def tearDown(self) -> None:
        self.root.cleanup()

    def next(self, story: str, terminal: str | None = None, path: str | None = None) -> str:
        return flow.next_story(self.root.path, path or str(self.folder), story, terminal, self.app,
                               lambda args, log: self.spawned.append((args, log)))


class FlowNextTest(NextCase):
    def test_from_a_shell_it_starts_the_next_persona_at_once(self) -> None:
        message = self.next("E1S1")

        self.assertEqual(message, "Started Engineer in tab E1S1 · Engineer in Demo")
        self.assertEqual([command for command, _ in self.app.commands], ["tab.close", "tab.new"])
        self.assertEqual(self.app.commands[-1][1]["task"], "Implement E1S1 (from In analysis)")
        self.assertEqual(self.spawned, [])

    def test_from_an_agent_it_only_schedules_the_worker(self) -> None:
        message = self.next("E1S1", terminal="term-7")

        log = sdlc.session_dir(self.folder, "E1S1") / "next.log"
        self.assertEqual(self.spawned, [([str(self.folder), "E1S1", "term-7", "in-analysis", "in-development"], log)])
        self.assertTrue(message.startswith("Handover to Engineer scheduled"))
        self.assertEqual(self.app.commands, [])

    def test_refusals_start_nothing(self) -> None:
        self.root.persona("in-review", "---\nname: Reviewer\nmodel:\n---\n\n## Role\nReviewer {{nope}}\n\n## Start\nReview\n")
        cases = [
            ("unregistered path", ("E1S1", None, str(self.root.path)), sdlc.NotFound, "No registered space"),
            ("unknown story", ("E1S9",), sdlc.NotFound, "E1S9 does not exist"),
            ("no specification", ("E1S4",), sdlc.NotFound, "E1S4 has no specification"),
            ("not ready", ("E1S2",), session.Refused, "E1S2 is not ready"),
            ("from In review", ("E1S5",), session.Refused, "only hands over from In analysis or In development"),
            ("invalid persona", ("E1S3", "term-7"), sdlc.PersonaError, "unknown variable"),
        ]
        for name, args, error, message in cases:
            with self.subTest(name), self.assertRaisesRegex(error, message):
                self.next(*args)
        (self.root.path / "personas" / "in-review.md").unlink()
        with self.assertRaisesRegex(session.Refused, "In review has no persona"):
            self.next("E1S3", "term-7")
        self.assertEqual((self.app.commands, self.spawned), ([], []))

    def test_a_refusal_exits_1_with_the_message_on_stderr(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sdlc, "ROOT", self.root.path), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = flow.main(["next", str(self.folder), "E1S2"])

        self.assertEqual((code, stdout.getvalue()), (1, ""))
        self.assertIn("E1S2 is not ready", stderr.getvalue())


class HandoverWorkerTest(NextCase):
    """`flow.py _handover`, the worker `next` spawns from an agent's terminal."""

    def handover(self, hc: FakeHc, clock_step: float = 1) -> tuple[int, str]:
        def wait(terminal: str, timeout: float, runner: herdr.Runner) -> str:
            return herdr.wait_terminal(terminal, timeout, runner, sleep=lambda _: None, clock=FakeClock(clock_step))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = flow.handover(self.root.path, str(self.folder), "E1S1", "t7", "in-analysis", "in-development",
                                 self.app, hc, wait)
        return code, out.getvalue()

    def sent(self, hc: FakeHc) -> list[str]:
        return [args[-1] for args in hc.calls if args[0] == "send"]

    def test_waits_through_working_and_blocked_then_starts_the_next_persona(self) -> None:
        hc = FakeHc(["working", "blocked", "idle"])

        code, log = self.handover(hc)

        self.assertEqual(code, 0)
        self.assertEqual(hc.commands(), ["get", "wait", "get", "get"])
        self.assertEqual([command for command, _ in self.app.commands], ["tab.close", "tab.new"])
        self.assertIn("Handover to Engineer done: started in tab E1S1 · Engineer in Demo", log)

    def test_a_status_changed_meanwhile_is_refused_logged_and_told(self) -> None:
        sdlc.set_story_status(self.root.config(), "E1S1", "in-development")
        hc = FakeHc(["idle"])

        code, log = self.handover(hc)

        self.assertEqual(code, 1)
        self.assertEqual(self.app.commands, [])
        self.assertIn("Handover to Engineer failed: The specification is now in In development", log)
        self.assertEqual(len(self.sent(hc)), 1)
        self.assertTrue(self.sent(hc)[0].startswith("Handover to Engineer failed: The specification is now in In development"))

    def test_a_herdr_failure_after_the_close_is_only_logged(self) -> None:
        self.app.fail = "tab.new"
        hc = FakeHc(["idle", "finished"])

        code, log = self.handover(hc)

        self.assertEqual(code, 1)
        self.assertEqual([command for command, _ in self.app.commands], ["tab.close", "tab.new"])
        self.assertIn("Handover to Engineer failed: herdr-app do tab.new: nope", log)
        self.assertIn("t7 has ended; the failure is only in this log", log)
        self.assertEqual(self.sent(hc), [])

    def test_a_timeout_is_logged_and_told_without_starting(self) -> None:
        hc = FakeHc(["working", "working", "idle"])

        code, log = self.handover(hc, clock_step=1000)

        self.assertEqual(code, 1)
        self.assertEqual(self.app.commands, [])
        self.assertIn("t7 is still working after 30 minutes", log)
        self.assertEqual(self.sent(hc), ["Handover to Engineer failed: t7 is still working after 30 minutes"])

    def test_a_message_the_terminal_refuses_is_logged(self) -> None:
        self.app.spaces[0]["tabs"].append({"id": "tb2", "name": "E1S1 · Reviewer", "terminals": [{"status": "working"}]})

        code, log = self.handover(FakeHc(["idle"], send_fails=True))

        self.assertEqual(code, 1)
        self.assertEqual(self.app.commands, [])
        self.assertIn("Handover to Engineer failed: Tab E1S1 · Reviewer in Demo is still working", log)
        self.assertIn("Could not tell t7: hc send --json: not idle", log)


class BreakdownTest(unittest.TestCase):
    """`flow.py breakdown`: an approved breakdown into epics and stories, all or nothing."""

    def setUp(self) -> None:
        self.root = Root()
        self.demo = self.root.space([{"id": "E1S1", "title": "Old", "status": "waiting-for-analysis"}])
        data = json.loads(self.root.config().read_text(encoding="utf-8"))
        data["space"]["nextEpic"] = 5
        data["epics"][0]["nextStory"] = 3
        self.root.write_config(self.demo, data)
        self.other = self.root.space([], space_id="other", name="Other")

    def tearDown(self) -> None:
        self.root.cleanup()

    def run_breakdown(self, breakdown: object) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        text = breakdown if isinstance(breakdown, str) else json.dumps(breakdown)
        with mock.patch.object(sdlc, "ROOT", self.root.path), mock.patch.object(sys, "stdin", io.StringIO(text)), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = flow.main(["breakdown"])
        return code, stdout.getvalue(), stderr.getvalue()

    def epics(self, space_id: str = "demo") -> dict:
        data = json.loads(self.root.config(space_id).read_text(encoding="utf-8"))
        return {e["id"]: e for e in data["epics"]}

    def test_new_and_existing_epics_in_two_spaces_in_one_call(self) -> None:
        code, stdout, stderr = self.run_breakdown({"epics": [
            {"space": str(self.demo), "title": " Ideas ", "stories": [
                {"title": "First", "description": "**Why** it matters", "labels": ["ui"]},
                {"title": "Second"},
            ]},
            {"space": str(self.demo), "epic": "E1", "stories": [{"title": "Third"}]},
            {"space": str(self.other), "title": "Elsewhere", "stories": [{"title": "Fourth"}]},
        ]})

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(stdout, "Demo: E5 Ideas (E5S1, E5S2); E1 (+E1S3)\nOther: E2 Elsewhere (E2S1)\n")
        demo = self.epics()
        self.assertEqual(demo["E5"]["title"], "Ideas")
        self.assertEqual(demo["E5"]["stories"][0], {
            "id": "E5S1", "title": "First", "description": "**Why** it matters", "status": "waiting-for-analysis", "labels": ["ui"],
        })
        self.assertEqual([s["id"] for s in demo["E1"]["stories"]], ["E1S1", "E1S3"])
        self.assertEqual([s["title"] for s in self.epics("other")["E2"]["stories"]], ["Fourth"])

    def test_nothing_is_written_when_any_entry_is_invalid(self) -> None:
        good = {"space": str(self.other), "title": "Fine", "stories": [{"title": "Fine"}]}
        cases = [
            ("invalid JSON", "{not json", "Invalid JSON"),
            ("no epics", {"epics": []}, "at least one epic"),
            ("unregistered space", {"epics": [good, {"space": str(self.root.path), "title": "X", "stories": [{"title": "S"}]}]},
             "Epic 2: No registered space"),
            ("unknown epic", {"epics": [good, {"space": str(self.demo), "epic": "E9", "stories": [{"title": "S"}]}]},
             "Epic 2: Epic E9 does not exist"),
            ("both epic and title", {"epics": [{"space": str(self.demo), "epic": "E1", "title": "X", "stories": [{"title": "S"}]}]},
             "Epic 1: give exactly one of epic"),
            ("neither epic nor title", {"epics": [{"space": str(self.demo), "stories": [{"title": "S"}]}]},
             "Epic 1: give exactly one of epic"),
            ("empty epic title", {"epics": [{"space": str(self.demo), "title": " ", "stories": [{"title": "S"}]}]},
             "Epic 1: Title is empty"),
            ("empty story title", {"epics": [good, {"space": str(self.demo), "epic": "E1", "stories": [{"title": "S"}, {"title": ""}]}]},
             "Epic 2, story 2: Title is empty"),
            ("bad label", {"epics": [{"space": str(self.demo), "epic": "E1", "stories": [{"title": "S", "labels": ["Bad Label"]}]}]},
             "Epic 1, story 1: Invalid label"),
            ("no stories", {"epics": [{"space": str(self.demo), "title": "X", "stories": []}]}, "Epic 1: stories must be"),
        ]
        before = (self.root.config().read_bytes(), self.root.config("other").read_bytes())
        for name, breakdown, message in cases:
            with self.subTest(name):
                code, stdout, stderr = self.run_breakdown(breakdown)
                self.assertEqual((code, stdout), (1, ""))
                self.assertIn(message, stderr)
                self.assertEqual((self.root.config().read_bytes(), self.root.config("other").read_bytes()), before)


class InstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.source = Path(self.dir.name) / "source"
        (self.source / "extensions").mkdir(parents=True)
        (self.source / "extensions" / "a.ts").write_text("// a\n")
        (self.source / "skills" / "flow-persona-x").mkdir(parents=True)
        (self.source / "skills" / "flow-persona-x" / "SKILL.md").write_text("Run `{{flow}} start`\n")
        self.agent = Path(self.dir.name) / "agent"
        self.target = self.agent / "extensions"
        self.skill = self.agent / "skills" / "flow-persona-x" / "SKILL.md"

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_copies_new_extensions_and_leaves_others(self) -> None:
        self.target.mkdir(parents=True)
        (self.target / "other.ts").write_text("// someone else's\n")
        output = flow.install(self.agent, self.source)
        self.assertEqual((self.target / "a.ts").read_text(), "// a\n")
        self.assertEqual((self.target / "other.ts").read_text(), "// someone else's\n")
        self.assertIn(f"installed: {self.target / 'a.ts'}", output)

    def test_installs_skills_with_the_flow_command_of_this_checkout(self) -> None:
        output = flow.install(self.agent, self.source)
        self.assertEqual(self.skill.read_text(), f"Run `{sdlc.FLOW_COMMAND} start`\n")
        self.assertIn(f"installed: {self.skill}", output)

    def test_a_second_run_changes_nothing_and_a_changed_copy_is_updated(self) -> None:
        flow.install(self.agent, self.source)
        self.assertEqual(flow.install(self.agent, self.source), f"unchanged: {self.target / 'a.ts'}\nunchanged: {self.skill}")
        (self.target / "a.ts").write_text("// edited\n")
        self.assertIn("updated:", flow.install(self.agent, self.source))
        self.assertEqual((self.target / "a.ts").read_text(), "// a\n")

    def test_the_folder_follows_pi_coding_agent_dir(self) -> None:
        with mock.patch.dict("os.environ", {"PI_CODING_AGENT_DIR": "/x/agent"}):
            self.assertEqual(flow.omp_agent_dir(), Path("/x/agent"))


if __name__ == "__main__":
    unittest.main()
