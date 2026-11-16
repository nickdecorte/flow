import unittest

from support import Root

import sdlc
import session

FIELDS = {
    "name": "Reviewer",
    "model": "opus",
    "role": "You review in {{path}}.\n\n- line one\n- line two",
    "start": "Review {{specification_path}} (from {{from}}).",
    "continue": "Continue with {{story_id}}: {{specification_title}} ({{execution}}).",
}


class TransitionTest(unittest.TestCase):
    def test_from_todo_only_onto_in_analysis(self) -> None:
        self.assertTrue(sdlc.drop_allowed("todo", "in-analysis"))
        self.assertFalse(sdlc.drop_allowed("todo", "in-development"))
        self.assertFalse(sdlc.drop_allowed("todo", "in-review"))

    def test_forward_onto_persona_columns_from_in_analysis_on(self) -> None:
        self.assertTrue(sdlc.drop_allowed("in-analysis", "in-development"))
        self.assertTrue(sdlc.drop_allowed("in-analysis", "in-review"))
        self.assertTrue(sdlc.drop_allowed("in-development", "in-review"))

    def test_the_board_has_five_columns(self) -> None:
        self.assertEqual(sdlc.COLUMN_KEYS, ["todo", "in-analysis", "in-development", "in-review", "done"])

    def test_only_back_from_in_review_to_in_development(self) -> None:
        self.assertTrue(sdlc.drop_allowed("in-review", "in-development"))
        self.assertFalse(sdlc.drop_allowed("in-review", "in-analysis"))
        self.assertFalse(sdlc.drop_allowed("in-development", "in-analysis"))
        self.assertFalse(sdlc.drop_allowed("done", "in-development"))

    def test_no_drop_on_own_column_todo_or_done(self) -> None:
        self.assertFalse(sdlc.drop_allowed("in-analysis", "in-analysis"))
        self.assertFalse(sdlc.drop_allowed("in-development", "in-development"))
        self.assertFalse(sdlc.drop_allowed("in-review", "done"))
        self.assertFalse(sdlc.drop_allowed("todo", "done"))
        self.assertFalse(sdlc.drop_allowed("in-analysis", "todo"))


class PersonaFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.specification = {"path": "/repo/.flow/specifications/p.md", "title": "P", "story": "E5S4", "execution": "autonomous"}
        self.space = {"path": "/repo", "config": "/repo/.flow/config.json"}

    def tearDown(self) -> None:
        self.root.cleanup()

    def test_markdown_round_trip_keeps_every_field(self) -> None:
        fields, problem = sdlc.parse_persona(sdlc.persona_markdown(FIELDS))
        self.assertIsNone(problem)
        self.assertEqual(fields, FIELDS)

    def test_create_then_conflict_on_stale_version(self) -> None:
        created = sdlc.save_persona(self.root.path, "in-review", FIELDS, None)

        with self.assertRaises(sdlc.PersonaConflict):
            sdlc.save_persona(self.root.path, "in-review", FIELDS, None)
        updated = sdlc.save_persona(self.root.path, "in-review", {**FIELDS, "model": ""}, created["version"])
        with self.assertRaises(sdlc.PersonaConflict):
            sdlc.save_persona(self.root.path, "in-review", FIELDS, created["version"])

        self.assertEqual(updated["model"], "")
        self.assertNotEqual(updated["version"], created["version"])

    def test_delete_needs_the_current_version(self) -> None:
        created = sdlc.save_persona(self.root.path, "in-review", FIELDS, None)
        with self.assertRaises(sdlc.PersonaConflict):
            sdlc.delete_persona(self.root.path, "in-review", "stale")
        sdlc.delete_persona(self.root.path, "in-review", created["version"])
        self.assertIsNone(sdlc.load_persona(self.root.path, "in-review"))

    def test_file_with_unknown_section_is_never_overwritten(self) -> None:
        self.root.persona("in-development", sdlc.persona_markdown(FIELDS) + "\n## Notes\nmy notes\n")
        persona = sdlc.load_persona(self.root.path, "in-development")

        self.assertFalse(persona["editable"])
        with self.assertRaises(sdlc.PersonaError):
            sdlc.save_persona(self.root.path, "in-development", FIELDS, persona["version"])
        self.assertIn("my notes", (self.root.path / "personas" / "in-development.md").read_text())

    def test_validation_names_each_problem(self) -> None:
        with self.assertRaises(sdlc.PersonaError) as raised:
            sdlc.validate_persona({**FIELDS, "role": " ", "model": "two words", "start": "Hi {{boss}}"}, "in-review")
        message = str(raised.exception)
        self.assertIn("Role is empty", message)
        self.assertIn("Model", message)
        self.assertIn("{{boss}}", message)

    def test_the_old_variable_names_are_unknown(self) -> None:
        with self.assertRaises(sdlc.PersonaError) as raised:
            sdlc.validate_persona({**FIELDS, "role": "In {{brief_path}}", "start": "Read {{space_file}} for {{story_ids}}"}, "in-review")
        for old in ("{{brief_path}}", "{{space_file}}", "{{story_ids}}"):
            self.assertIn(old, str(raised.exception))

    def test_keys_without_persona_cannot_get_one(self) -> None:
        for key in ("todo", "done", "unknown"):
            self.assertIsNone(sdlc.load_persona(self.root.path, key))
            with self.assertRaises(sdlc.PersonaError):
                sdlc.save_persona(self.root.path, key, FIELDS, None)

    def test_renders_start_or_continue_with_the_source_column(self) -> None:
        persona = sdlc.save_persona(self.root.path, "in-review", FIELDS, None)

        dropped = sdlc.render_persona(persona, self.specification, self.space, "in-development", "start")
        continued = sdlc.render_persona(persona, self.specification, self.space, "in-review", "continue")

        self.assertEqual(dropped["task"], "Review /repo/.flow/specifications/p.md (from In development).")
        self.assertTrue(dropped["role"].startswith("You review in /repo."))
        self.assertEqual(continued["task"], "Continue with E5S4: P (autonomous).")

    def test_fills_the_config_file(self) -> None:
        persona = sdlc.save_persona(self.root.path, "in-analysis", {**FIELDS, "start": "Read {{config_file}}."}, None)

        rendered = sdlc.render_persona(persona, self.specification, self.space, "todo", "start")

        self.assertEqual(rendered["task"], "Read /repo/.flow/config.json.")

    def test_continue_without_continue_section_is_refused(self) -> None:
        persona = sdlc.save_persona(self.root.path, "in-review", {**FIELDS, "continue": ""}, None)
        with self.assertRaises(sdlc.PersonaError):
            sdlc.render_persona(persona, self.specification, self.space, "in-review", "continue")


PRODUCT_OWNER = {
    "name": "Product Owner",
    "model": "",
    "role": "You break down ideas in {{path}}; spaces are in {{spaces_file}}.",
    "start": "Read {{config_file}} and ask for the idea.",
    "continue": "",
}


class ProductOwnerPersonaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()

    def tearDown(self) -> None:
        self.root.cleanup()

    def test_saves_loads_and_deletes(self) -> None:
        created = sdlc.save_persona(self.root.path, sdlc.PRODUCT_OWNER, PRODUCT_OWNER, None)

        loaded = sdlc.load_persona(self.root.path, sdlc.PRODUCT_OWNER)
        self.assertEqual(loaded["key"], "product-owner")
        self.assertEqual(loaded["start"], PRODUCT_OWNER["start"])
        sdlc.delete_persona(self.root.path, sdlc.PRODUCT_OWNER, created["version"])
        self.assertIsNone(sdlc.load_persona(self.root.path, sdlc.PRODUCT_OWNER))

    def test_story_variables_and_continue_are_refused(self) -> None:
        with self.assertRaises(sdlc.PersonaError) as raised:
            sdlc.save_persona(self.root.path, sdlc.PRODUCT_OWNER, {**PRODUCT_OWNER, "start": "Do {{story_id}} in {{specification_path}}", "continue": "Go on."}, None)
        message = str(raised.exception)
        self.assertIn("{{story_id}}", message)
        self.assertIn("{{specification_path}}", message)
        self.assertIn("Continue", message)
        self.assertFalse((self.root.path / "personas" / "product-owner.md").exists())

    def test_product_owner_variables_are_refused_for_a_column(self) -> None:
        with self.assertRaises(sdlc.PersonaError) as raised:
            sdlc.validate_persona({**FIELDS, "start": "Read {{spaces_file}}."}, "in-analysis")
        self.assertIn("{{spaces_file}}", str(raised.exception))

    def test_renders_the_home_space_and_the_registry(self) -> None:
        persona = sdlc.save_persona(self.root.path, sdlc.PRODUCT_OWNER, PRODUCT_OWNER, None)

        rendered = sdlc.render_product_owner(self.root.path, persona, {"path": "/repo", "config": "/repo/.flow/config.json"})

        self.assertEqual(rendered["role"], f"You break down ideas in /repo; spaces are in {self.root.path / 'spaces.json'}.")
        self.assertEqual(rendered["task"], "Read /repo/.flow/config.json and ask for the idea.")
        self.assertEqual((rendered["name"], rendered["model"]), ("Product Owner", None))


class HandoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.space = {"path": "/my repo", "config": "/my repo/.flow/config.json"}
        self.specification = {"path": "/my repo/.flow/specifications/p.md", "title": "P", "story": "E5S4", "execution": "autonomous"}
        sdlc.save_persona(self.root.path, "in-development", {**FIELDS, "name": "Engineer"}, None)

    def tearDown(self) -> None:
        self.root.cleanup()

    def handover(self, column: str) -> str | None:
        return session.handover_text(self.root.path, column, self.space, self.specification)

    def test_next_target_is_the_next_persona_column(self) -> None:
        self.assertEqual(session.next_target("in-analysis"), "in-development")
        self.assertEqual(session.next_target("in-development"), "in-review")
        for status in ("todo", "in-review", "done"):
            self.assertIsNone(session.next_target(status))

    def test_in_analysis_asks_to_continue_with_the_next_persona_and_names_the_command(self) -> None:
        text = self.handover("in-analysis")

        self.assertIn(f"you have run `python3 {sdlc.FLOW_SCRIPT} ready '/my repo' E5S4` and finished your report", text)
        self.assertIn('"Shall I continue with Engineer?"', text)
        self.assertIn(f"`python3 {sdlc.FLOW_SCRIPT} next '/my repo' E5S4`", text)
        self.assertIn("end your turn without any further output", text)

    def test_in_development_says_to_drag_when_in_review_has_no_persona(self) -> None:
        text = self.handover("in-development")

        self.assertIn(f"you have run `python3 {sdlc.FLOW_SCRIPT} ready '/my repo' E5S4`", text)
        self.assertIn("In review has no persona", text)
        self.assertIn("dragging the card", text)
        self.assertNotIn(f"{sdlc.FLOW_SCRIPT} next", text)

    def test_in_review_gets_no_handover(self) -> None:
        self.assertIsNone(self.handover("in-review"))

    def test_the_paragraph_is_appended_to_the_rendered_role(self) -> None:
        persona = sdlc.load_persona(self.root.path, "in-development")

        rendered = sdlc.render_persona(persona, self.specification, self.space, "in-analysis", "start", "Handover: ask.")

        self.assertEqual(rendered["role"], "You review in /my repo.\n\n- line one\n- line two\n\nHandover: ask.")


if __name__ == "__main__":
    unittest.main()
