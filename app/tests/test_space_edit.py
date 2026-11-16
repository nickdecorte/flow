import json
import os
import unittest
from unittest import mock

from support import Root

import sdlc

SPACE = {
    "schemaVersion": 2,
    "space": {"id": "demo", "name": "Demo", "title": "Demo title"},
    "notes": ["keep this"],
    "risks": [{"id": "R1", "text": "and this"}],
    "epics": [
        {
            "id": "E1",
            "title": "Preferences",
            "context": "epic-context",
            "stories": [
                {"id": "SET-05", "title": "Prices", "description": "Old", "status": "in-review", "labels": ["mail"], "specification": "prices.md"},
                {"id": "SET-06", "title": "Vat", "status": "done", "labels": [], "specification": "vat.md"},
            ],
        },
        {"id": "E3", "title": "Admin", "stories": [{"id": "E3S4", "title": "Roles", "status": "in-analysis", "labels": [], "specification": "roles.md"}]},
    ],
}


class SpaceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.folder = self.root.space([])
        self.path = self.root.config()
        self.path.write_text(json.dumps(SPACE), encoding="utf-8")
        self.specifications = self.folder / ".flow" / "specifications"

    def tearDown(self) -> None:
        self.root.cleanup()

    def data(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def version(self) -> str:
        return sdlc.space_version(self.path)

    def story(self, story_id: str) -> dict:
        return sdlc.find_story(self.data(), story_id)[1]

    def create_story(self, epic_id: str = "E1", **fields) -> dict:
        return sdlc.create_story(self.root.path, "demo", epic_id, {"title": "New", **fields}, self.version())


class SpaceEditTest(SpaceFixture):
    def test_load_spaces_gives_the_config_version(self) -> None:
        space = sdlc.load_spaces(self.root.path)[0][0]
        self.assertEqual(space["version"], self.version())

    def test_first_new_story_in_an_epic_with_only_old_ids_is_e_n_s1(self) -> None:
        self.assertEqual(self.create_story()["story"], "E1S1")
        self.assertEqual(self.create_story()["story"], "E1S2")
        self.assertEqual(self.data()["epics"][0]["nextStory"], 3)

    def test_new_story_skips_numbers_in_use_and_follows_the_counter(self) -> None:
        self.assertEqual(self.create_story("E3")["story"], "E3S5")

        data = self.data()
        data["epics"][1]["nextStory"] = 9
        self.path.write_text(json.dumps(data), encoding="utf-8")

        self.assertEqual(self.create_story("E3")["story"], "E3S9")

    def test_new_epic_follows_the_highest_id_and_the_counter(self) -> None:
        result = sdlc.create_epic(self.root.path, "demo", "  Reports ", self.version())

        self.assertEqual(result["epic"], "E4")
        self.assertEqual(result["version"], self.version())
        self.assertEqual(self.data()["epics"][-1], {"id": "E4", "title": "Reports", "stories": []})
        self.assertEqual(self.data()["space"]["nextEpic"], 5)

        data = self.data()
        data["space"]["nextEpic"] = 7
        self.path.write_text(json.dumps(data), encoding="utf-8")

        self.assertEqual(sdlc.create_epic(self.root.path, "demo", "Later", self.version())["epic"], "E7")

    def test_creating_a_story_writes_no_specification_and_waits_for_analysis(self) -> None:
        story_id = self.create_story(description=" *Why* \n", labels="ui, api-v2, ui")["story"]

        self.assertEqual(self.story(story_id), {
            "id": story_id, "title": "New", "description": "*Why*", "status": "waiting-for-analysis", "labels": ["ui", "api-v2"],
        })
        self.assertEqual(list(self.specifications.iterdir()), [])
        state_story = next(s for e in sdlc.load_state(self.root.path)["spaces"][0]["epics"] for s in e["stories"] if s["id"] == story_id)
        self.assertEqual((state_story["status"], state_story["specification"]), ("waiting-for-analysis", None))

    def test_editing_changes_only_title_description_and_labels(self) -> None:
        before = self.data()

        sdlc.update_story(self.root.path, "demo", "SET-05", {"title": "Manage prices", "description": "New", "labels": ["a"]}, self.version())
        sdlc.update_epic(self.root.path, "demo", "E1", "Settings", self.version())

        story = before["epics"][0]["stories"][0]
        story.update(title="Manage prices", description="New", labels=["a"])
        before["epics"][0]["title"] = "Settings"
        self.assertEqual(self.data(), before)

    def test_editing_leaves_fields_that_are_not_sent(self) -> None:
        sdlc.update_story(self.root.path, "demo", "SET-05", {"labels": ""}, self.version())

        self.assertEqual(self.story("SET-05")["title"], "Prices")
        self.assertEqual(self.story("SET-05")["description"], "Old")
        self.assertEqual(self.story("SET-05")["labels"], [])

    def test_moving_an_epic_changes_only_the_order(self) -> None:
        before = self.data()

        result = sdlc.move_epic(self.root.path, "demo", "E3", 0, self.version())

        self.assertEqual(result["version"], self.version())
        before["epics"].reverse()
        self.assertEqual(self.data(), before)
        sdlc.move_epic(self.root.path, "demo", "E3", 1, self.version())
        self.assertEqual([e["id"] for e in self.data()["epics"]], ["E1", "E3"])

    def test_invalid_fields_are_refused_and_change_nothing(self) -> None:
        before = self.path.read_bytes()
        cases = [
            ("empty title", lambda: self.create_story(title="  ")),
            ("title on two lines", lambda: self.create_story(title="One\nTwo")),
            ("invalid label", lambda: self.create_story(labels="Uppercase")),
            ("label with space", lambda: self.create_story(labels=["with space"])),
            ("status not editable", lambda: sdlc.update_story(self.root.path, "demo", "SET-05", {"status": "done"}, self.version())),
            ("empty epic title", lambda: sdlc.create_epic(self.root.path, "demo", "", self.version())),
            ("epic title on two lines", lambda: sdlc.update_epic(self.root.path, "demo", "E1", "A\r\nB", self.version())),
            ("position past the end", lambda: sdlc.move_epic(self.root.path, "demo", "E1", 2, self.version())),
            ("negative position", lambda: sdlc.move_epic(self.root.path, "demo", "E1", -1, self.version())),
            ("position as text", lambda: sdlc.move_epic(self.root.path, "demo", "E1", "1", self.version())),
        ]
        for name, action in cases:
            with self.subTest(name), self.assertRaises(sdlc.SpaceError):
                action()
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_stale_version_is_a_conflict_and_changes_nothing(self) -> None:
        before = self.path.read_bytes()
        actions = [
            lambda: sdlc.create_epic(self.root.path, "demo", "X", "stale"),
            lambda: sdlc.update_epic(self.root.path, "demo", "E1", "X", "stale"),
            lambda: sdlc.move_epic(self.root.path, "demo", "E3", 0, "stale"),
            lambda: sdlc.create_story(self.root.path, "demo", "E1", {"title": "X"}, "stale"),
            lambda: sdlc.update_story(self.root.path, "demo", "SET-05", {"title": "X"}, None),
        ]
        for action in actions:
            with self.assertRaises(sdlc.SpaceConflict):
                action()
        self.assertEqual(self.path.read_bytes(), before)

    def test_unknown_space_epic_or_story_is_not_found(self) -> None:
        with self.assertRaises(sdlc.NotFound):
            sdlc.create_epic(self.root.path, "nope", "X", self.version())
        with self.assertRaises(sdlc.NotFound):
            self.create_story("E9")
        with self.assertRaises(sdlc.NotFound):
            sdlc.update_story(self.root.path, "demo", "SET-99", {"title": "X"}, self.version())


class DeleteTest(SpaceFixture):
    def setUp(self) -> None:
        super().setUp()
        self.files = {file: self.root.specification(None, file, file) for file in ("prices.md", "vat.md", "roles.md", "loose.md")}

    def remaining(self) -> list[str]:
        return sorted(name for name, path in self.files.items() if path.exists())

    def stories(self) -> list[str]:
        return [s["id"] for e in self.data()["epics"] for s in e["stories"]]

    def parked(self) -> list[str]:
        return [p.name for p in (self.folder / ".flow").iterdir() if p.name.startswith(".deleting-")]

    def test_deleting_a_story_removes_its_specification(self) -> None:
        result = sdlc.delete_story(self.root.path, "demo", "SET-05", self.version())

        self.assertEqual((result["stories"], result["specifications"]), (["SET-05"], ["prices.md"]))
        self.assertEqual(result["version"], self.version())
        self.assertEqual(self.stories(), ["SET-06", "E3S4"])
        self.assertEqual(self.remaining(), ["loose.md", "roles.md", "vat.md"])
        self.assertEqual(self.parked(), [])

    def test_deleting_an_epic_removes_the_specifications_of_all_its_stories(self) -> None:
        result = sdlc.delete_epic(self.root.path, "demo", "E1", self.version())

        self.assertEqual(result["stories"], ["SET-05", "SET-06"])
        self.assertEqual(sorted(result["specifications"]), ["prices.md", "vat.md"])
        self.assertEqual(self.remaining(), ["loose.md", "roles.md"])
        self.assertEqual([e["id"] for e in self.data()["epics"]], ["E3"])
        self.assertEqual((self.data()["notes"], self.data()["risks"]), (SPACE["notes"], SPACE["risks"]))

    def test_the_preview_lists_the_stories_and_their_specifications_with_status(self) -> None:
        preview = sdlc.deletion_preview(self.root.path, "demo", epic_id="E1")

        self.assertEqual([s["id"] for s in preview["stories"]], ["SET-05", "SET-06"])
        self.assertEqual([(s["file"], s["status"]) for s in preview["specifications"]], [("prices.md", "in-review"), ("vat.md", "done")])

    def test_the_specifications_return_when_the_config_cannot_be_written(self) -> None:
        before = self.path.read_bytes()

        with mock.patch.object(sdlc, "write_json", side_effect=OSError("disk full")), self.assertRaises(OSError):
            sdlc.delete_epic(self.root.path, "demo", "E1", self.version())

        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.remaining(), sorted(self.files))
        self.assertEqual(self.parked(), [])

    def test_deleted_numbers_are_not_reused(self) -> None:
        sdlc.delete_story(self.root.path, "demo", "E3S4", self.version())
        self.assertEqual(self.create_story("E3")["story"], "E3S5")

        sdlc.delete_epic(self.root.path, "demo", "E3", self.version())
        self.assertEqual(sdlc.create_epic(self.root.path, "demo", "Again", self.version())["epic"], "E4")

    def test_a_stale_version_deletes_nothing(self) -> None:
        before = self.path.read_bytes()
        for action in (sdlc.delete_story, sdlc.delete_epic):
            with self.assertRaises(sdlc.SpaceConflict):
                action(self.root.path, "demo", "E1" if action is sdlc.delete_epic else "SET-05", "stale")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.remaining(), sorted(self.files))


class CreateSpaceTest(unittest.TestCase):
    """`~` is the temporary root's `home/`, and the existing space Demo lives in `work/demo`."""

    def setUp(self) -> None:
        self.root = Root()
        self.home = self.root.path / "home"
        self.home.mkdir()
        self.work = self.root.path / "work"
        self.root.space([], path=str(self.work / "demo"))
        home = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        home.start()
        self.addCleanup(home.stop)

    def tearDown(self) -> None:
        self.root.cleanup()

    def registry(self) -> list[str]:
        return [entry["path"] for entry in sdlc.read_registry(self.root.path)]

    def test_writes_the_config_and_adds_the_path_as_typed_to_the_registry(self) -> None:
        result = sdlc.create_space(self.root.path, "  My Café ", "~/work/my-cafe")

        config = self.home / "work" / "my-cafe" / ".flow" / "config.json"
        self.assertEqual(result, {"space": "my-cafe", "version": sdlc.space_version(config)})
        self.assertEqual(json.loads(config.read_text(encoding="utf-8")), {
            "schemaVersion": 2,
            "space": {"id": "my-cafe", "name": "My Café", "nextEpic": 1},
            "epics": [],
        })
        self.assertEqual(self.registry(), [str(self.work / "demo"), "~/work/my-cafe"])
        space = next(s for s in sdlc.load_state(self.root.path)["spaces"] if s["id"] == "my-cafe")
        self.assertEqual((space["title"], space["path"], space["config"]), ("My Café", str(self.home / "work" / "my-cafe"), str(config)))

    def test_invalid_names_are_refused_and_write_nothing(self) -> None:
        for name in ("", "   ", "One\nTwo", "All", "!!!", None):
            with self.subTest(name=name), self.assertRaises(sdlc.SpaceError):
                sdlc.create_space(self.root.path, name, str(self.work / "new"))
        self.assertEqual(self.registry(), [str(self.work / "demo")])
        self.assertFalse((self.work / "new").exists())

    def test_same_name_id_or_path_as_another_space_is_a_conflict(self) -> None:
        cases = {
            "name in other case": ("DEMO", str(self.work / "x")),
            "same ID": ("Demo!", str(self.work / "y")),
            "same path, absolute": ("Other", str(self.work / "demo") + "/"),
            "same path, with ~": ("Other", "~/../work/demo"),
        }
        for name, (space_name, path) in cases.items():
            with self.subTest(name), self.assertRaises(sdlc.SpaceConflict):
                sdlc.create_space(self.root.path, space_name, path)
        self.assertEqual(self.registry(), [str(self.work / "demo")])
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["demo"])

    def test_an_existing_config_is_a_conflict_and_stays(self) -> None:
        config = self.work / "new" / ".flow" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text("{}", encoding="utf-8")

        with self.assertRaises(sdlc.SpaceConflict):
            sdlc.create_space(self.root.path, "New", str(self.work / "new"))

        self.assertEqual(config.read_text(encoding="utf-8"), "{}")
        self.assertEqual(self.registry(), [str(self.work / "demo")])

    def test_a_relative_path_or_a_file_is_refused(self) -> None:
        self.work.joinpath("notes.txt").write_text("x", encoding="utf-8")
        for path in ("work/new", "./new", "~unknown-user-xyz/new", "", str(self.work / "notes.txt")):
            with self.subTest(path=path), self.assertRaises(sdlc.SpaceError):
                sdlc.create_space(self.root.path, "New", path)
        self.assertEqual(self.registry(), [str(self.work / "demo")])

    def test_a_missing_nested_path_is_made_and_a_path_inside_another_space_is_allowed(self) -> None:
        sdlc.create_space(self.root.path, "Deep", str(self.work / "a" / "b" / "c"))
        sdlc.create_space(self.root.path, "Inside", str(self.work / "demo" / "sub"))

        self.assertTrue((self.work / "a" / "b" / "c" / ".flow" / "config.json").is_file())
        self.assertTrue((self.work / "demo" / "sub" / ".flow" / "config.json").is_file())
        self.assertEqual([s["id"] for s in sdlc.load_state(self.root.path)["spaces"]], ["demo", "deep", "inside"])

    def test_a_failed_write_removes_the_config_and_only_the_folders_it_made(self) -> None:
        existing = self.work / "existing"
        existing.mkdir()
        registry = (self.root.path / sdlc.REGISTRY).read_bytes()
        failures = {
            "config": mock.patch.object(sdlc, "json_text", side_effect=OSError("disk full")),
            "registry": mock.patch.object(sdlc, "write_json", side_effect=OSError("disk full")),
        }
        for step, failure in failures.items():
            for path in (existing / "a" / "b", existing):
                with self.subTest(step=step, path=path):
                    with failure, self.assertRaises(OSError):
                        sdlc.create_space(self.root.path, "New", str(path))
                    self.assertEqual((self.root.path / sdlc.REGISTRY).read_bytes(), registry)
                    self.assertFalse((existing / "a").exists())
                    self.assertEqual(list(existing.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
