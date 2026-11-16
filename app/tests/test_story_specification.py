import json
import threading
import unittest
from datetime import date
from unittest import mock

from support import Client, Root

import sdlc
import server

TOKEN = "secret-token"
TODAY = date(2026, 11, 8)
FILE = "2026-11-08-set-05-cafe-manage-prices-specification.md"


class CreateSpecificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([
            {"id": "SET-05", "title": "Café / Manage {prices}", "status": "waiting-for-analysis", "labels": ["mail"]},
            {"id": "SET-06", "title": "With specification"},
            {"id": "SET-08", "title": "Closed", "status": "done"},
        ])
        self.root.specification("SET-06", "existing.md", "With specification", status="in-analysis")
        self.specifications = self.folder / ".flow" / "specifications"

    def tearDown(self) -> None:
        self.root.cleanup()

    def config(self) -> dict:
        return json.loads(self.root.config().read_text(encoding="utf-8"))

    def create(self, story_id: str) -> dict:
        return sdlc.create_specification(self.root.path, "demo", story_id, TODAY)

    def test_creates_the_file_and_sets_the_specification_and_todo(self) -> None:
        before = self.config()

        result = self.create("SET-05")

        self.assertEqual(result, {"specification": FILE, "story": "SET-05"})
        text = (self.specifications / FILE).read_text(encoding="utf-8")
        self.assertEqual(text, "---\nexecution: per-task\n---\n\n# Café / Manage {prices} (SET-05) Specification\n")
        before["epics"][0]["stories"][0].update(specification=FILE, status="todo")
        self.assertEqual(self.config(), before)

    def test_the_card_is_in_todo_afterwards(self) -> None:
        self.create("SET-05")
        state = sdlc.load_state(self.root.path)
        specification = next(s for s in state["specifications"] if s["story"] == "SET-05")

        self.assertEqual((specification["file"], specification["status"], specification["title"]), (FILE, "todo", "Café / Manage {prices} (SET-05)"))
        self.assertEqual(state["warnings"], [])

    def test_the_folder_is_made_when_it_is_missing(self) -> None:
        for path in self.specifications.iterdir():
            path.unlink()
        self.specifications.rmdir()

        self.create("SET-05")

        self.assertTrue((self.specifications / FILE).is_file())

    def test_story_with_a_specification_or_on_done_is_a_conflict(self) -> None:
        before = self.root.config().read_bytes()
        for story_id in ("SET-06", "SET-08"):
            with self.subTest(story_id), self.assertRaises(sdlc.SpecificationConflict):
                self.create(story_id)
        self.assertEqual(sorted(p.name for p in self.specifications.iterdir()), ["existing.md"])
        self.assertEqual(self.root.config().read_bytes(), before)

    def test_an_existing_file_is_a_conflict_and_stays(self) -> None:
        existing = self.specifications / FILE
        existing.write_text("my specification", encoding="utf-8")

        with self.assertRaises(sdlc.SpecificationConflict):
            self.create("SET-05")

        self.assertEqual(existing.read_text(encoding="utf-8"), "my specification")
        self.assertNotIn("specification", self.config()["epics"][0]["stories"][0])

    def test_unknown_space_or_story_is_not_found(self) -> None:
        with self.assertRaises(sdlc.NotFound):
            sdlc.create_specification(self.root.path, "nope", "SET-05", TODAY)
        with self.assertRaises(sdlc.NotFound):
            self.create("SET-99")

    def test_the_file_is_removed_when_the_config_cannot_be_written(self) -> None:
        before = self.root.config().read_bytes()
        with mock.patch.object(sdlc, "write_json", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.create("SET-05")
        self.assertFalse((self.specifications / FILE).exists())
        self.assertEqual(self.root.config().read_bytes(), before)

    def test_slug_drops_accents_and_symbols_and_is_bounded(self) -> None:
        self.assertEqual(sdlc.slug("Café / Manage {prices}"), "cafe-manage-prices")
        self.assertEqual(sdlc.slug("  Ærø: naïve — two!  "), "r-naive-two")
        long = sdlc.slug("word " * 30)
        self.assertLessEqual(len(long), sdlc.SLUG_LENGTH)
        self.assertFalse(long.endswith("-"))


class StorySpecificationApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([{"id": "SET-05", "title": "Products"}])
        self.httpd = server.make_server(self.root.path, 0, TOKEN)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.client = Client(self.httpd.server_address[1], TOKEN)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.root.cleanup()

    def post(self, path: str, **options) -> tuple[int, dict]:
        return self.client.request("POST", path, **options)

    def test_needs_token_and_origin(self) -> None:
        self.assertEqual(self.post("/api/spaces/demo/stories/SET-05/specification", token="guess")[0], 403)
        self.assertEqual(self.post("/api/spaces/demo/stories/SET-05/specification", origin="https://evil.example")[0], 403)
        self.assertEqual(list((self.folder / ".flow" / "specifications").iterdir()), [])

    def test_unknown_space_or_story_is_404(self) -> None:
        self.assertEqual(self.post("/api/spaces/nope/stories/SET-05/specification")[0], 404)
        self.assertEqual(self.post("/api/spaces/demo/stories/SET-99/specification")[0], 404)

    def test_creates_once_then_conflicts(self) -> None:
        status, body = self.post("/api/spaces/demo/stories/SET-05/specification")
        self.assertEqual(status, 200)
        self.assertEqual(body["story"], "SET-05")
        self.assertTrue((self.folder / ".flow" / "specifications" / body["specification"]).exists())

        self.assertEqual(self.post("/api/spaces/demo/stories/SET-05/specification")[0], 409)


if __name__ == "__main__":
    unittest.main()
