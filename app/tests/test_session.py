import json
import unittest

from support import Root
from test_herdr import FakeHerdrApp

import herdr
import sdlc
import session

ENGINEER = "---\nname: Engineer\nmodel:\n---\n\n## Role\nEngineer\n\n## Start\nImplement {{story_id}}\n"


class StartStoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([
            {"id": "E1S1", "title": "Ready"},
            {"id": "E1S2", "title": "Without", "status": "waiting-for-analysis"},
            {"id": "E1S3", "title": "Building"},
        ])
        self.root.specification("E1S1", "ready.md", "Ready (E1S1)", status="in-analysis")
        self.root.specification("E1S3", "building.md", "Building (E1S3)", status="in-development")
        self.root.persona("in-development", ENGINEER)
        self.app = FakeHerdrApp([{"id": "sp1", "name": "Demo", "tabs": []}])

    def tearDown(self) -> None:
        self.root.cleanup()

    def start(self, story: str, source: str, target: str, space_id: str = "demo") -> dict:
        return session.start_story(self.root.path, space_id, story, source, target, self.app)

    def ready(self, story: str) -> bool:
        data = json.loads(self.root.config().read_text(encoding="utf-8"))
        return bool(sdlc.find_story(data, story)[1].get("ready"))

    def test_starts_the_target_persona_on_the_story_session_folder(self) -> None:
        result = self.start("E1S1", "in-analysis", "in-development")

        self.assertEqual(result, {"result": "started", "space": "Demo", "tab": "E1S1 · Engineer"})
        _, payload = self.app.commands[-1]
        self.assertEqual(payload["argv"][-2:], ["--session-dir", str(self.folder / ".flow" / "sessions" / "E1S1")])
        self.assertEqual(payload["task"], "Implement E1S1")

    def test_a_started_agent_clears_ready(self) -> None:
        sdlc.set_story_ready(self.root.config(), "E1S1")

        self.start("E1S1", "in-analysis", "in-development")

        self.assertFalse(self.ready("E1S1"))

    def test_selecting_an_open_tab_keeps_ready(self) -> None:
        sdlc.set_story_ready(self.root.config(), "E1S1")
        self.app.spaces[0]["tabs"] = [{"id": "tb1", "name": "E1S1 · Engineer", "terminals": [{"status": "idle"}]}]

        result = self.start("E1S1", "in-analysis", "in-development")

        self.assertEqual(result["result"], "already_running")
        self.assertTrue(self.ready("E1S1"))

    def test_a_refused_or_failed_start_keeps_ready(self) -> None:
        sdlc.set_story_ready(self.root.config(), "E1S1")
        self.app.spaces[0]["tabs"] = [{"id": "tb1", "name": "E1S1 · Analyst", "terminals": [{"status": "working"}]}]
        with self.assertRaises(herdr.TabBusy):
            self.start("E1S1", "in-analysis", "in-development")
        self.app.spaces[0]["tabs"] = []
        self.app.fail = "tab.new"
        with self.assertRaises(herdr.HerdrError):
            self.start("E1S1", "in-analysis", "in-development")
        self.assertTrue(self.ready("E1S1"))

    def test_refusals_raise_before_any_herdr_command(self) -> None:
        self.root.persona("in-review", "---\nname: Reviewer\nmodel:\n---\n\n## Role\nReviewer {{nope}}\n\n## Start\nReview\n")
        cases = [
            ("unknown space", ("E1S1", "in-analysis", "in-development", "nope"), sdlc.NotFound, "Space nope"),
            ("unknown story", ("E1S9", "in-analysis", "in-development"), sdlc.NotFound, "E1S9 does not exist"),
            ("no specification", ("E1S2", "todo", "in-analysis"), sdlc.NotFound, "E1S2 has no specification"),
            ("stale from", ("E1S1", "todo", "in-development"), sdlc.SpecificationConflict, "now in In analysis"),
            ("no persona", ("E1S3", "in-development", "in-analysis"), session.Refused, "is not allowed"),
            ("column without persona", ("E1S1", "in-analysis", "in-analysis"), session.Refused, "has no persona"),
            ("invalid persona", ("E1S3", "in-development", "in-review"), sdlc.PersonaError, "unknown variable"),
        ]
        for name, args, error, message in cases:
            with self.subTest(name), self.assertRaisesRegex(error, message):
                self.start(*args)
        self.assertEqual(self.app.commands, [])

    def test_a_working_tab_of_another_persona_is_busy(self) -> None:
        self.app.spaces[0]["tabs"] = [{"id": "tb1", "name": "E1S1 · Analyst", "terminals": [{"status": "working"}]}]
        with self.assertRaises(herdr.TabBusy):
            self.start("E1S1", "in-analysis", "in-development")


class SpaceAtTest(unittest.TestCase):
    def test_finds_the_registered_space_by_its_folder(self) -> None:
        root = Root()
        self.addCleanup(root.cleanup)
        folder = root.space([])
        state = sdlc.load_state(root.path)

        self.assertEqual(sdlc.space_at(state, f"{folder}/")["id"], "demo")
        with self.assertRaisesRegex(sdlc.NotFound, "No registered space"):
            sdlc.space_at(state, str(root.path))


if __name__ == "__main__":
    unittest.main()
