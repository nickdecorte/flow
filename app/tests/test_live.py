import http.client
import json
import subprocess
import threading
import unittest
from unittest import mock

from support import Root
from test_herdr import FakeHerdrApp

import live
import sdlc
import server

TOKEN = "t0ken"


def status_line(terminal: str, state: str) -> str:
    return json.dumps({"method": "event", "params": {"type": "status", "terminal": terminal,
                                                      "data": {"status": {"app": "omp", "state": state}}}})


def title_line(terminal: str) -> str:
    return json.dumps({"method": "event", "params": {"type": "title", "terminal": terminal, "data": {"title": "π ⠦"}}})


def tab(name: str, *states: str | None) -> dict:
    return {"id": f"tb-{name}", "name": name, "terminals": [{"terminal": f"t-{name}", "status": s} for s in states]}


class AgentsMapTest(unittest.TestCase):
    SPACES = [{"id": "demo", "name": "Demo"}, {"id": "other", "name": "Other"}]
    SPECIFICATIONS = [{"space": "demo", "story": s} for s in ("E1S1", "E1S2", "E1S3", "E1S4")] + [{"space": "other", "story": "E2S1"}]

    def test_maps_story_tabs_to_space_id_and_story(self) -> None:
        opened = [
            {"name": "Demo", "tabs": [
                tab("E1S1 · Analyst", "idle"), tab("E1S1 · Engineer", "working"),
                tab("E1S2", "blocked"),
                tab("E1S3 · Engineer", None),
                tab("3", "working"),
            ]},
            {"name": "Elsewhere", "tabs": [tab("E2S1 · Analyst", "working")]},
        ]

        agents = live.agents_map(opened, self.SPACES, self.SPECIFICATIONS)

        self.assertEqual(agents, {
            "demo|E1S1": {"persona": "Engineer", "state": "working"},
            "demo|E1S2": {"persona": None, "state": "blocked"},
        })

    def test_without_a_working_terminal_the_first_agent_counts(self) -> None:
        opened = [{"name": "Demo", "tabs": [tab("E1S4 · Analyst", "done"), tab("E1S4 · Engineer", "idle")]}]

        self.assertEqual(live.agents_map(opened, self.SPACES, self.SPECIFICATIONS),
                         {"demo|E1S4": {"persona": "Analyst", "state": "done"}})


class RelevantTest(unittest.TestCase):
    def test_only_title_events_and_garbage_are_ignored(self) -> None:
        self.assertFalse(live.relevant(title_line("t1")))
        self.assertFalse(live.relevant("not json\n"))
        self.assertTrue(live.relevant(status_line("t1", "idle")))
        self.assertTrue(live.relevant(json.dumps({"channel": None, "seq": 1, "terminals": []})))
        self.assertTrue(live.relevant(json.dumps({"method": "event", "params": {"type": "finished", "terminal": "t1"}})))


class HubCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([{"id": "E1S1", "title": "One"}, {"id": "E1S2", "title": "Two"}])
        self.root.specification("E1S1", "one.md", "One", status="in-analysis")
        self.app = FakeHerdrApp([{"id": "sp1", "name": "Demo", "tabs": [tab("E1S1 · Analyst", "working")]}])
        self.hub = live.Hub(self.root.path, self.app, events=lambda: iter([]), sleep=lambda _: None)
        self.queue = self.hub.subscribe()

    def tearDown(self) -> None:
        self.root.cleanup()

    def received(self) -> list[tuple[str, dict]]:
        items = []
        while not self.queue.empty():
            items.append(self.queue.get_nowait())
        return items


class HubAgentsTest(HubCase):
    def test_a_subscriber_first_gets_the_current_agents(self) -> None:
        self.assertEqual(self.received(), [("agents", live.OFFLINE)])

    def test_pushes_agents_only_when_they_changed(self) -> None:
        self.received()
        working = {"available": True, "agents": {"demo|E1S1": {"persona": "Analyst", "state": "working"}}}

        self.hub.refresh_agents()
        self.hub.refresh_agents()
        self.assertEqual(self.received(), [("agents", working)])

        self.app.spaces[0]["tabs"][0]["terminals"][0]["status"] = "idle"
        self.hub.refresh_agents()
        self.assertEqual(self.received()[0][1]["agents"]["demo|E1S1"]["state"], "idle")

    def test_a_failing_herdr_app_is_offline(self) -> None:
        self.hub.refresh_agents()
        self.received()
        self.hub.runner = lambda args: subprocess.CompletedProcess(args, 1, "", "no window")

        self.hub.refresh_agents()

        self.assertEqual(self.received(), [("agents", live.OFFLINE)])

    def test_title_events_ask_for_no_refresh_other_events_do(self) -> None:
        lines = []
        self.hub.events = lambda: iter(lines)

        lines[:] = [title_line("t1"), title_line("t1")]
        self.hub.follow_once()
        self.assertFalse(self.hub.dirty.is_set())

        lines[:] = [title_line("t1"), status_line("t1", "idle")]
        self.hub.follow_once()
        self.assertTrue(self.hub.dirty.is_set())

    def test_an_ended_stream_is_offline_and_restarts_after_a_while(self) -> None:
        self.hub.refresh_agents()
        self.received()
        started, slept = [], []

        def events():
            started.append(True)
            if len(started) == 1:
                raise OSError("hc not found")
            return iter([status_line("t1", "idle")])

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            if len(slept) == 2:
                raise StopIteration

        self.hub.events, self.hub.sleep = events, sleep
        with self.assertRaises(StopIteration):
            self.hub.follow_herdr()

        self.assertEqual((len(started), slept), (2, [live.RESTART_SECONDS, live.RESTART_SECONDS]))
        self.assertEqual(self.received(), [("agents", live.OFFLINE)])
        self.assertFalse(self.hub.following)


class HubFilesTest(HubCase):
    def test_the_first_look_only_remembers(self) -> None:
        self.received()
        self.hub.check_files()
        self.hub.check_files()
        self.assertEqual(self.received(), [])

    def test_config_and_specification_changes_push_changed(self) -> None:
        self.hub.check_files()
        self.received()
        changes = {
            "config": lambda: sdlc.set_story_ready(self.root.config(), "E1S1"),
            "specification edited": lambda: (sdlc.specifications_dir(self.folder) / "one.md").write_text("# Changed\n- [x] Task 1: Do it\n"),
            "specification added": lambda: self.root.specification(None, "new.md", "New"),
            "specification removed": lambda: (sdlc.specifications_dir(self.folder) / "new.md").unlink(),
        }
        for name, change in changes.items():
            with self.subTest(name):
                change()
                self.hub.check_files()
                self.assertEqual(self.received(), [("changed", {})])
                self.assertTrue(self.hub.dirty.is_set())
                self.hub.dirty.clear()


class EventsApiTest(HubCase):
    def setUp(self) -> None:
        super().setUp()
        self.httpd = server.make_server(self.root.path, 0, TOKEN, self.app, hub=self.hub)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def open_stream(self) -> http.client.HTTPResponse:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{self.port}"})
        return connection.getresponse()

    def frame(self, response: http.client.HTTPResponse) -> list[str]:
        lines = []
        while (line := response.fp.readline().decode("utf-8")) not in ("\n", ""):
            lines.append(line.rstrip("\n"))
        return lines

    def test_streams_the_snapshot_then_every_event(self) -> None:
        response = self.open_stream()

        self.assertEqual((response.status, response.getheader("Content-Type")), (200, "text/event-stream; charset=utf-8"))
        self.assertEqual(self.frame(response), ["event: agents", f"data: {json.dumps(live.OFFLINE)}"])
        self.hub.publish("changed", {})
        self.assertEqual(self.frame(response), ["event: changed", "data: {}"])

    def test_writes_a_keep_alive_when_nothing_happens(self) -> None:
        with mock.patch.object(server, "KEEPALIVE_SECONDS", 0.05):
            response = self.open_stream()
            self.frame(response)
            self.assertEqual(self.frame(response), [": keep-alive"])

    def test_a_closed_connection_unsubscribes(self) -> None:
        response = self.open_stream()
        self.frame(response)
        response.close()

        for _ in range(100):
            self.hub.publish("changed", {})
            if len(self.hub.subscribers) == 1:
                break
            threading.Event().wait(0.02)
        self.assertEqual(len(self.hub.subscribers), 1)

    def test_a_server_without_hub_has_no_events(self) -> None:
        plain = server.make_server(self.root.path, 0, TOKEN, self.app)
        threading.Thread(target=plain.serve_forever, daemon=True).start()
        self.addCleanup(plain.server_close)
        self.addCleanup(plain.shutdown)
        connection = http.client.HTTPConnection("127.0.0.1", plain.server_address[1], timeout=5)
        connection.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{plain.server_address[1]}"})
        self.assertEqual(connection.getresponse().status, 404)
        connection.close()


if __name__ == "__main__":
    unittest.main()
