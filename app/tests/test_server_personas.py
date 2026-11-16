import threading
import unittest

from support import Client, Root

import server

TOKEN = "secret-token"
FIELDS = {"name": "Reviewer", "model": "", "role": "You review.", "start": "Review {{specification_path}}.", "continue": ""}


class PersonaApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.httpd = server.make_server(self.root.path, 0, TOKEN)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.client = Client(self.httpd.server_address[1], TOKEN)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.root.cleanup()

    def put(self, key: str, version: str | None, **options) -> tuple[int, dict]:
        return self.client.request("PUT", f"/api/personas/{key}", {**FIELDS, "version": version}, **options)

    def test_lists_every_persona(self) -> None:
        status, personas = self.client.request("GET", "/api/personas")
        self.assertEqual(status, 200)
        self.assertEqual([p["key"] for p in personas], ["in-analysis", "in-development", "in-review", "product-owner"])
        self.assertEqual(personas[-1]["label"], "Product Owner")
        self.assertFalse(any(p["exists"] for p in personas))

    def test_create_update_and_delete(self) -> None:
        status, created = self.put("in-review", None)
        self.assertEqual(status, 200)
        self.assertTrue(created["exists"])

        status, _ = self.put("in-review", created["version"])
        self.assertEqual(status, 200)

        status, deleted = self.client.request("DELETE", f"/api/personas/in-review?version={created['version']}")
        self.assertEqual(status, 200)
        self.assertFalse(deleted["exists"])

    def test_stale_version_is_a_conflict(self) -> None:
        _, created = self.put("in-review", None)
        (self.root.path / "personas" / "in-review.md").write_text("---\nname: X\n---\n\n## Role\nA\n\n## Start\nB\n", encoding="utf-8")

        self.assertEqual(self.put("in-review", created["version"])[0], 409)
        self.assertEqual(self.client.request("DELETE", f"/api/personas/in-review?version={created['version']}")[0], 409)

    def test_invalid_fields_are_refused(self) -> None:
        status, body = self.client.request("PUT", "/api/personas/in-review", {**FIELDS, "start": "{{nope}}", "version": None})
        self.assertEqual(status, 422)
        self.assertIn("{{nope}}", body["error"])

    def test_writing_needs_token_and_origin(self) -> None:
        self.assertEqual(self.put("in-review", None, token="guess")[0], 403)
        self.assertEqual(self.put("in-review", None, origin="https://evil.example")[0], 403)
        self.assertEqual(self.client.request("DELETE", "/api/personas/in-review?version=x", token="guess")[0], 403)
        self.assertFalse((self.root.path / "personas" / "in-review.md").exists())

    def test_columns_without_personas_are_unknown(self) -> None:
        self.assertEqual(self.put("todo", None)[0], 404)
        self.assertEqual(self.put("../escape", None)[0], 404)

    def test_product_owner_round_trip(self) -> None:
        fields = {**FIELDS, "start": "Read {{spaces_file}}.", "version": None}
        status, created = self.client.request("PUT", "/api/personas/product-owner", fields)
        self.assertEqual(status, 200)
        self.assertEqual((created["key"], created["start"]), ("product-owner", "Read {{spaces_file}}."))

        status, deleted = self.client.request("DELETE", f"/api/personas/product-owner?version={created['version']}")
        self.assertEqual(status, 200)
        self.assertFalse(deleted["exists"])


if __name__ == "__main__":
    unittest.main()
