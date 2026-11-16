import unittest

from support import Root

import sdlc


class StateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()

    def tearDown(self) -> None:
        self.root.cleanup()

    def story(self, state: dict, story_id: str) -> dict:
        return next(s for p in state["spaces"] for e in p["epics"] for s in e["stories"] if s["id"] == story_id)

    def specifications(self, state: dict) -> dict:
        return {s["story"]: s for s in state["specifications"]}

    def test_columns_are_the_statuses_after_waiting_for_analysis(self) -> None:
        meta = sdlc.meta()

        self.assertEqual(meta["statusOrder"][0], "waiting-for-analysis")
        self.assertEqual([c["key"] for c in meta["columns"]], meta["statusOrder"][1:])
        self.assertEqual(len(meta["statusOrder"]), 6)
        self.assertEqual(set(meta["statusLabels"]), set(meta["statusOrder"]))

    def test_the_story_status_is_the_column_of_its_specification(self) -> None:
        self.root.space([{"id": f"S{i}", "title": key} for i, key in enumerate(sdlc.COLUMN_KEYS)])
        for i, key in enumerate(sdlc.COLUMN_KEYS):
            self.root.specification(f"S{i}", f"s{i}.md", key, status=key)

        state = sdlc.load_state(self.root.path)

        self.assertEqual({s["story"]: s["status"] for s in state["specifications"]}, {f"S{i}": key for i, key in enumerate(sdlc.COLUMN_KEYS)})
        self.assertEqual(state["warnings"], [])

    def test_a_specification_carries_its_space_and_story(self) -> None:
        self.root.space([{"id": "E1S1", "title": "A"}])
        self.root.specification("E1S1", "a.md", "Products (E1S1)", status="in-review")

        specification = sdlc.load_state(self.root.path)["specifications"][0]

        self.assertEqual(
            {key: specification[key] for key in ("space", "spaceName", "story", "status", "file", "title")},
            {"space": "demo", "spaceName": "Demo", "story": "E1S1", "status": "in-review", "file": "a.md", "title": "Products (E1S1)"},
        )
        self.assertNotIn("folder", specification)

    def test_stories_name_their_specification_or_none(self) -> None:
        self.root.space([{"id": "E1S1", "title": "A"}, {"id": "E1S2", "title": "B", "status": "done"}])
        self.root.specification("E1S1", "a.md", "A", status="todo")

        state = sdlc.load_state(self.root.path)

        self.assertEqual(self.story(state, "E1S1")["specification"], "a.md")
        self.assertIsNone(self.story(state, "E1S2")["specification"])
        self.assertEqual(self.story(state, "E1S2")["status"], "done")

    def test_without_a_registry_there_are_no_spaces(self) -> None:
        self.assertEqual(sdlc.load_state(self.root.path), {"spaces": [], "specifications": [], "warnings": []})

    def test_a_registered_path_without_config_is_skipped_with_a_warning(self) -> None:
        self.root.space([])
        self.root.register(str(self.root.path / "elsewhere"))

        state = sdlc.load_state(self.root.path)

        self.assertEqual([s["id"] for s in state["spaces"]], ["demo"])
        self.assertEqual(len(state["warnings"]), 1)
        self.assertIn("elsewhere", state["warnings"][0])

    def test_a_second_space_with_the_same_id_is_skipped_with_a_warning(self) -> None:
        self.root.space([], name="First")
        self.root.space([], path=str(self.root.path / "work" / "second"), name="Second")

        state = sdlc.load_state(self.root.path)

        self.assertEqual([s["name"] for s in state["spaces"]], ["First"])
        self.assertEqual(len(state["warnings"]), 1)
        self.assertIn("second", state["warnings"][0])

    def test_a_specification_on_waiting_for_analysis_shows_in_todo_with_a_warning(self) -> None:
        self.root.space([{"id": "E1S1", "title": "A"}])
        self.root.specification("E1S1", "a.md", "A", status="waiting-for-analysis")

        state = sdlc.load_state(self.root.path)

        self.assertEqual(self.specifications(state)["E1S1"]["status"], "todo")
        self.assertEqual(self.story(state, "E1S1")["status"], "todo")
        self.assertEqual(len(state["warnings"]), 1)

    def test_a_story_without_specification_past_analysis_gets_no_card_and_a_warning(self) -> None:
        self.root.space([{"id": "E1S1", "title": "A", "status": "in-development"}])

        state = sdlc.load_state(self.root.path)

        self.assertEqual(state["specifications"], [])
        self.assertEqual(len(state["warnings"]), 1)
        self.assertIn("E1S1", state["warnings"][0])

    def test_a_specification_without_story_is_reported(self) -> None:
        self.root.space([{"id": "E1S1", "title": "A"}])
        self.root.specification(None, "loose.md", "Loose")

        state = sdlc.load_state(self.root.path)

        self.assertEqual(state["specifications"], [])
        self.assertEqual(len(state["warnings"]), 1)
        self.assertIn("loose.md", state["warnings"][0])

    def test_a_story_naming_a_missing_file_is_reported(self) -> None:
        self.root.space([{"id": "E1S1", "title": "A", "status": "in-development", "specification": "gone.md"}])

        state = sdlc.load_state(self.root.path)

        self.assertEqual(state["specifications"], [])
        self.assertEqual(len(state["warnings"]), 1)
        self.assertIn("gone.md", state["warnings"][0])

    def test_execution_defaults_to_per_task_and_rejects_unknown_modes(self) -> None:
        self.root.space([{"id": "A", "title": "A"}, {"id": "B", "title": "B"}, {"id": "C", "title": "C"}])
        self.root.specification("A", "a.md", "A", status="todo", front_matter="execution: autonomous")
        self.root.specification("B", "b.md", "B", status="todo")
        self.root.specification("C", "c.md", "C", status="todo", front_matter="execution: yolo")

        specifications = self.specifications(sdlc.load_state(self.root.path))

        self.assertEqual(specifications["A"]["execution"], "autonomous")
        self.assertEqual(specifications["B"]["execution"], "per-task")
        self.assertEqual(specifications["C"]["execution"], "per-task")


if __name__ == "__main__":
    unittest.main()
