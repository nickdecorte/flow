import json
import threading
import unittest

from support import Client, Root

import sdlc
import server

TOKEN = "secret-token"


class SpaceApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.root.space([
            {"id": "SET-05", "title": "Prices", "status": "waiting-for-analysis", "labels": []},
            {"id": "SET-06", "title": "Vat", "status": "waiting-for-analysis", "labels": []},
        ])
        self.root.specification("SET-05", "prices.md", "Prices (SET-05)", status="todo")
        self.root.specification("SET-06", "vat.md", "Vat (SET-06)", status="in-analysis")
        self.path = self.root.config()
        self.specifications = self.path.parent / "specifications"
        self.httpd = server.make_server(self.root.path, 0, TOKEN)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.client = Client(self.httpd.server_address[1], TOKEN)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.root.cleanup()

    def version(self) -> str:
        status, space = self.client.request("GET", "/api/spaces/demo")
        self.assertEqual(status, 200)
        return space["version"]

    def stories(self) -> list[str]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [s["id"] for e in data["epics"] for s in e["stories"]]

    def test_create_edit_and_delete_through_the_api(self) -> None:
        status, epic = self.client.request("POST", "/api/spaces/demo/epics", {"title": "Reports", "version": self.version()})
        self.assertEqual((status, epic["epic"]), (200, "E2"))

        status, story = self.client.request("POST", "/api/spaces/demo/epics/E2/stories", {"title": "Export", "labels": "csv", "version": epic["version"]})
        self.assertEqual((status, story["story"]), (200, "E2S1"))

        status, _ = self.client.request("PATCH", "/api/spaces/demo/stories/E2S1", {"title": "Export to CSV", "version": story["version"]})
        self.assertEqual(status, 200)
        status, _ = self.client.request("PATCH", "/api/spaces/demo/epics/E2", {"title": "Reporting", "version": self.version()})
        self.assertEqual(status, 200)

        status, _ = self.client.request("PATCH", "/api/spaces/demo/epics/E2", {"position": 0, "version": self.version()})
        self.assertEqual(status, 200)
        self.assertEqual(self.client.request("PATCH", "/api/spaces/demo/epics/E2", {"position": 5, "version": self.version()})[0], 422)

        _, space = self.client.request("GET", "/api/spaces/demo")
        self.assertEqual([e["id"] for e in space["epics"]], ["E2", "E1"])
        epic = space["epics"][0]
        self.assertEqual((epic["title"], epic["stories"][0]["title"], epic["stories"][0]["labels"]), ("Reporting", "Export to CSV", ["csv"]))

        status, deleted = self.client.request("DELETE", f"/api/spaces/demo/epics/E2?version={self.version()}")
        self.assertEqual((status, deleted["stories"]), (200, ["E2S1"]))

    def test_deletion_lists_the_stories_and_the_specifications_that_go(self) -> None:
        status, story = self.client.request("GET", "/api/spaces/demo/deletion?story=SET-05")
        self.assertEqual(status, 200)
        self.assertEqual(story["stories"], [{"id": "SET-05", "title": "Prices"}])
        self.assertEqual([(s["file"], s["status"]) for s in story["specifications"]], [("prices.md", "todo")])

        _, epic = self.client.request("GET", "/api/spaces/demo/deletion?epic=E1")
        self.assertEqual([s["id"] for s in epic["stories"]], ["SET-05", "SET-06"])
        self.assertEqual([s["file"] for s in epic["specifications"]], ["prices.md", "vat.md"])

        self.assertEqual(self.client.request("GET", "/api/spaces/demo/deletion")[0], 400)

    def test_deleting_a_story_removes_its_specification(self) -> None:
        status, result = self.client.request("DELETE", f"/api/spaces/demo/stories/SET-05?version={self.version()}")

        self.assertEqual((status, result["specifications"]), (200, ["prices.md"]))
        self.assertEqual(self.stories(), ["SET-06"])
        self.assertFalse((self.specifications / "prices.md").exists())
        self.assertTrue((self.specifications / "vat.md").exists())

    def test_writing_needs_token_and_origin(self) -> None:
        before = self.path.read_bytes()
        version = self.version()
        requests = [
            ("POST", "/api/spaces/demo/epics", {"title": "X", "version": version}),
            ("POST", "/api/spaces/demo/epics/E1/stories", {"title": "X", "version": version}),
            ("PATCH", "/api/spaces/demo/epics/E1", {"title": "X", "version": version}),
            ("PATCH", "/api/spaces/demo/stories/SET-05", {"title": "X", "version": version}),
            ("DELETE", f"/api/spaces/demo/epics/E1?version={version}", None),
            ("DELETE", f"/api/spaces/demo/stories/SET-05?version={version}", None),
        ]
        for method, path, body in requests:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.client.request(method, path, body, token="guess")[0], 403)
                self.assertEqual(self.client.request(method, path, body, origin="https://evil.example")[0], 403)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unknown_space_epic_or_story_is_404(self) -> None:
        version = self.version()
        self.assertEqual(self.client.request("POST", "/api/spaces/nope/epics", {"title": "X", "version": version})[0], 404)
        self.assertEqual(self.client.request("POST", "/api/spaces/demo/epics/E9/stories", {"title": "X", "version": version})[0], 404)
        self.assertEqual(self.client.request("PATCH", "/api/spaces/demo/stories/SET-99", {"title": "X", "version": version})[0], 404)
        self.assertEqual(self.client.request("DELETE", f"/api/spaces/demo/epics/E9?version={version}")[0], 404)
        self.assertEqual(self.client.request("GET", "/api/spaces/demo/deletion?story=SET-99")[0], 404)

    def test_a_change_in_the_editor_is_a_conflict(self) -> None:
        version = self.version()
        self.path.write_text(self.path.read_text(encoding="utf-8").replace("Prices", "Prices!"), encoding="utf-8")
        before = self.path.read_bytes()

        status, body = self.client.request("PATCH", "/api/spaces/demo/stories/SET-05", {"title": "X", "version": version})
        self.assertEqual(status, 409)
        self.assertIn("changed in the meantime", body["error"])
        self.assertEqual(self.client.request("DELETE", f"/api/spaces/demo/stories/SET-05?version={version}")[0], 409)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue((self.specifications / "prices.md").exists())

    def test_invalid_fields_are_422(self) -> None:
        status, body = self.client.request("POST", "/api/spaces/demo/epics/E1/stories", {"title": "X", "labels": "With Space", "version": self.version()})
        self.assertEqual(status, 422)
        self.assertIn("With Space", body["error"])
        self.assertEqual(self.client.request("PATCH", "/api/spaces/demo/stories/SET-05", {"status": "done", "version": self.version()})[0], 422)

    def test_create_a_space_then_read_it(self) -> None:
        folder = self.root.path / "work" / "new"
        status, created = self.client.request("POST", "/api/spaces", {"name": "New", "path": str(folder)})
        self.assertEqual((status, created["space"]), (200, "new"))

        status, space = self.client.request("GET", "/api/spaces/new")
        self.assertEqual(status, 200)
        self.assertEqual((space["name"], space["path"], space["epics"], space["version"]), ("New", str(folder), [], created["version"]))
        self.assertTrue((folder / ".flow" / "config.json").is_file())

    def test_creating_a_space_refuses_conflicts_and_invalid_fields(self) -> None:
        status, body = self.client.request("POST", "/api/spaces", {"name": "demo", "path": str(self.root.path / "x")})
        self.assertEqual(status, 409)
        self.assertIn("Demo", body["error"])
        status, body = self.client.request("POST", "/api/spaces", {"name": "New", "path": "work/new"})
        self.assertEqual(status, 422)
        self.assertIn("absolute", body["error"])
        self.assertEqual(self.client.request("POST", "/api/spaces", {"name": "All", "path": str(self.root.path / "y")})[0], 422)
        self.assertEqual(sdlc.read_registry(self.root.path), [{"path": str(self.path.parent.parent)}])

    def test_creating_a_space_needs_token_and_origin(self) -> None:
        body = {"name": "New", "path": str(self.root.path / "work" / "new")}
        self.assertEqual(self.client.request("POST", "/api/spaces", body, token="guess")[0], 403)
        self.assertEqual(self.client.request("POST", "/api/spaces", body, origin="https://evil.example")[0], 403)
        self.assertEqual(sdlc.read_registry(self.root.path), [{"path": str(self.path.parent.parent)}])
        self.assertFalse((self.root.path / "work" / "new").exists())


if __name__ == "__main__":
    unittest.main()
