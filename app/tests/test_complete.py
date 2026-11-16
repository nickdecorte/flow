import json
import threading
import unittest
from unittest import mock

from support import Client, Root
from test_herdr import FakeHc, FakeHerdrApp

import sdlc
import server

TOKEN = "secret-token"


class CompleteSpecificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.root.space([
            {"id": "SET-05", "title": "With specification", "labels": ["mail"]},
            {"id": "SET-06", "title": "Without", "status": "waiting-for-analysis"},
        ])
        self.file = self.root.specification("SET-05", "p.md", "Products (SET-05)", status="in-review", tasks="- [ ] Task 1: Open")

    def tearDown(self) -> None:
        self.root.cleanup()

    def complete(self, story_id: str, source: str) -> dict:
        return sdlc.complete_specification(self.root.path, "demo", story_id, source)

    def stored(self) -> dict:
        data = json.loads(self.root.config().read_text())
        return {s["id"]: s for e in data["epics"] for s in e["stories"]}

    def test_sets_only_the_story_to_done_and_moves_nothing(self) -> None:
        result = self.complete("SET-05", "in-review")

        self.assertEqual(result, {"story": "SET-05", "specification": "p.md"})
        self.assertTrue(self.file.exists())
        stories = self.stored()
        self.assertEqual((stories["SET-05"]["status"], stories["SET-05"]["specification"], stories["SET-05"]["labels"]), ("done", "p.md", ["mail"]))
        self.assertEqual(stories["SET-06"]["status"], "waiting-for-analysis")
        self.assertEqual(sdlc.load_state(self.root.path)["specifications"][0]["status"], "done")

    def test_done_clears_ready(self) -> None:
        sdlc.set_story_ready(self.root.config(), "SET-05")

        self.complete("SET-05", "in-review")

        self.assertNotIn("ready", self.stored()["SET-05"])

    def test_another_status_done_or_no_specification_is_a_conflict_and_changes_nothing(self) -> None:
        before = self.root.config().read_bytes()
        for story_id, source in (("SET-05", "in-development"), ("SET-06", "waiting-for-analysis")):
            with self.subTest(story_id), self.assertRaises(sdlc.SpecificationConflict):
                self.complete(story_id, source)
        self.assertEqual(self.root.config().read_bytes(), before)

        self.complete("SET-05", "in-review")
        with self.assertRaises(sdlc.SpecificationConflict):
            self.complete("SET-05", "done")

    def test_unknown_space_or_story_is_not_found(self) -> None:
        with self.assertRaises(sdlc.NotFound):
            sdlc.complete_specification(self.root.path, "nope", "SET-05", "in-review")
        with self.assertRaises(sdlc.NotFound):
            self.complete("SET-99", "in-review")

    def test_done_is_not_a_persona_target(self) -> None:
        self.assertFalse(any(t["to"] == "done" for t in sdlc.transitions()))


class CompleteApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        folder = self.root.space([{"id": "SET-05", "title": "A"}])
        self.root.specification("SET-05", "p.md", "Products (SET-05)", status="in-review")
        self.session = sdlc.session_dir(folder, "SET-05")
        self.session.mkdir(parents=True)
        (self.session / "s.jsonl").write_text("{}\n")
        self.app = FakeHerdrApp([{"id": "sp1", "name": "Demo", "tabs": [
            self.tab("SET-05 · Reviewer", "idle", "t1"), self.tab("SET-05 · Engineer", "done", "t2"),
            self.tab("SET-06 · Engineer", "working", "t3"),
        ]}])
        self.hc = FakeHc(["finished"])
        self.httpd = server.make_server(self.root.path, 0, TOKEN, self.app, self.hc)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.client = Client(self.httpd.server_address[1], TOKEN)
        self.url = "/api/spaces/demo/stories/SET-05/specification/complete"

    @staticmethod
    def tab(name: str, status: str, terminal: str) -> dict:
        return {"id": f"tb-{name}", "name": name, "terminals": [{"terminal": terminal, "status": status}]}

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.root.cleanup()

    def status(self) -> str:
        return json.loads(self.root.config().read_text())["epics"][0]["stories"][0]["status"]

    def test_needs_token(self) -> None:
        status, _ = self.client.request("POST", self.url, {"from": "in-review"}, token="guess")
        self.assertEqual(status, 403)
        self.assertEqual(self.status(), "in-review")
        self.assertEqual(self.app.commands, [])

    def test_closes_the_story_tabs_deletes_its_session_and_sets_done(self) -> None:
        status, body = self.client.request("POST", self.url, {"from": "in-review"})

        self.assertEqual((status, body["story"]), (200, "SET-05"))
        self.assertEqual(self.status(), "done")
        self.assertEqual(self.app.commands, [
            ("tab.close", {"id": "tb-SET-05 · Reviewer", "confirmed": True}),
            ("tab.close", {"id": "tb-SET-05 · Engineer", "confirmed": True}),
        ])
        self.assertEqual(self.hc.calls, [["get", "t1", "--json"], ["get", "t2", "--json"]])
        self.assertFalse(self.session.exists())

    def test_a_program_that_does_not_end_keeps_the_status_and_the_session(self) -> None:
        self.hc.states = ["done"]

        with mock.patch.object(server, "CLOSE_SECONDS", 0.3):
            status, body = self.client.request("POST", self.url, {"from": "in-review"})

        self.assertEqual(status, 502)
        self.assertIn("t1 has not ended", body["error"])
        self.assertEqual(self.status(), "in-review")
        self.assertTrue(self.session.exists())

    def test_completes_without_tabs_or_session(self) -> None:
        self.app.spaces = []
        self.session.joinpath("s.jsonl").unlink()
        self.session.rmdir()
        status, _ = self.client.request("POST", self.url, {"from": "in-review"})
        self.assertEqual(status, 200)
        self.assertEqual(self.status(), "done")

    def test_stale_source_is_a_conflict_and_closes_nothing(self) -> None:
        status, _ = self.client.request("POST", self.url, {"from": "todo"})
        self.assertEqual(status, 409)
        self.assertEqual(self.status(), "in-review")
        self.assertEqual(self.app.commands, [])
        self.assertTrue(self.session.exists())

    def test_a_working_tab_of_the_story_refuses_done_and_changes_nothing(self) -> None:
        self.app.spaces[0]["tabs"][1] = self.tab("SET-05 · Engineer", "working", "t2")

        status, body = self.client.request("POST", self.url, {"from": "in-review"})

        self.assertEqual(status, 409)
        self.assertIn("SET-05 · Engineer in Demo is still working", body["error"])
        self.assertEqual(self.status(), "in-review")
        self.assertEqual(self.app.commands, [])
        self.assertTrue((self.session / "s.jsonl").exists())

    def test_herdr_app_failure_is_a_bad_gateway_and_keeps_the_status(self) -> None:
        self.app.fail = "tab.close"

        status, body = self.client.request("POST", self.url, {"from": "in-review"})

        self.assertEqual(status, 502)
        self.assertIn("nope", body["error"])
        self.assertEqual(self.status(), "in-review")
        self.assertTrue(self.session.exists())


if __name__ == "__main__":
    unittest.main()
