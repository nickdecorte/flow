import http.client
import json
import threading
import unittest

from support import Root

import server


class ReadApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([{"id": "SET-05", "title": "Products"}, {"id": "SET-06", "title": "Without"}])
        self.root.specification("SET-05", "p.md", "Products (SET-05)", status="in-development",
                                front_matter="execution: autonomous", body="Some **bold** text")
        self.httpd = server.make_server(self.root.path, 0, "secret")
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.root.cleanup()

    def get(self, path: str, host: str | None = None) -> tuple[int, object]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        connection.putrequest("GET", path, skip_host=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        connection.endheaders()
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, json.loads(body) if body else None

    def test_refuses_foreign_host_headers(self) -> None:
        status, _ = self.get("/api/specifications", host=f"evil.example:{self.port}")
        self.assertEqual(status, 403)

    def test_accepts_localhost_host_header(self) -> None:
        status, _ = self.get("/api/specifications", host=f"localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_specifications_list_has_space_story_status_and_no_markdown_body(self) -> None:
        status, specifications = self.get("/api/specifications")
        self.assertEqual(status, 200)
        self.assertEqual(len(specifications), 1)
        specification = specifications[0]
        self.assertEqual(
            (specification["space"], specification["spaceName"], specification["story"], specification["status"], specification["execution"]),
            ("demo", "Demo", "SET-05", "in-development", "autonomous"),
        )
        self.assertNotIn("body", specification)

    def test_specification_detail_renders_html(self) -> None:
        status, specification = self.get("/api/spaces/demo/stories/SET-05/specification")
        self.assertEqual(status, 200)
        self.assertEqual(specification["file"], "p.md")
        self.assertIn("<strong>bold</strong>", specification["html"])

    def test_unknown_space_story_or_missing_specification_is_not_found(self) -> None:
        for path in ("/api/spaces/nope/stories/SET-05/specification", "/api/spaces/demo/stories/SET-99/specification",
                     "/api/spaces/demo/stories/SET-06/specification"):
            with self.subTest(path):
                status, body = self.get(path)
                self.assertEqual(status, 404)
                self.assertIn("error", body)

    def test_space_detail_carries_path_config_and_each_storys_specification(self) -> None:
        status, space = self.get("/api/spaces/demo")
        self.assertEqual(status, 200)
        self.assertEqual(space["path"], str(self.folder))
        self.assertEqual(space["config"], str(self.folder / ".flow" / "config.json"))
        self.assertNotIn("file", space)
        stories = space["epics"][0]["stories"]
        self.assertEqual([(s["status"], s["specification"]) for s in stories], [("in-development", "p.md"), ("waiting-for-analysis", None)])


if __name__ == "__main__":
    unittest.main()
