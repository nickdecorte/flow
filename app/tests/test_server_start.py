import threading
import unittest

from support import Client, Root
from test_herdr import FakeHerdrApp

import server

ENGINEER = "---\nname: Engineer\nmodel:\n---\n\n## Role\nEngineer in {{path}}\n\n## Start\nImplement {{specification_title}} (from {{from}})\n\n## Continue\nContinue with {{story_id}}\n"
REVIEWER_WITHOUT_CONTINUE = "---\nname: Reviewer\nmodel:\n---\n\n## Role\nReviewer\n\n## Start\nReview {{specification_title}}\n"
ANALYST = "---\nname: Analyst\nmodel:\n---\n\n## Role\nAnalyst\n\n## Start\nAnalyse {{specification_path}} with {{config_file}} (from {{from}})\n"
TOKEN = "secret-token"


class StartApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.repo = self.root.space([
            {"id": "E1S1", "title": "Ready"},
            {"id": "E1S2", "title": "Building"},
            {"id": "E1S3", "title": "Review"},
            {"id": "E1S4", "title": "Todo"},
            {"id": "E1S5", "title": "Without", "status": "waiting-for-analysis"},
        ])
        self.root.specification("E1S1", "ready.md", "Ready (E1S1)", status="in-analysis")
        self.root.specification("E1S2", "building.md", "Building (E1S2)", status="in-development")
        self.root.specification("E1S3", "review.md", "Review (E1S3)", status="in-review")
        self.todo = self.root.specification("E1S4", "todo.md", "Todo (E1S4)", status="todo")
        self.root.persona("in-development", ENGINEER)
        self.app = FakeHerdrApp([{"id": "sp1", "name": "Demo", "tabs": []}])
        self.httpd = server.make_server(self.root.path, 0, TOKEN, self.app)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.client = Client(self.httpd.server_address[1], TOKEN)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.root.cleanup()

    def start(self, story: str, source: str, target: str, **options) -> tuple[int, dict]:
        return self.client.request("POST", f"/api/spaces/demo/stories/{story}/specification/start", {"from": source, "to": target}, **options)

    def started(self) -> dict:
        command, payload = self.app.commands[-1]
        self.assertEqual(command, "tab.new")
        return payload

    def test_drop_starts_the_target_columns_persona_in_a_tab_named_after_the_story(self) -> None:
        before = self.root.config().read_bytes()

        status, body = self.start("E1S1", "in-analysis", "in-development")

        self.assertEqual(status, 200)
        self.assertEqual((body["result"], body["tab"]), ("started", "E1S1 · Engineer"))
        self.assertEqual(self.started()["task"], "Implement Ready (E1S1) (from In analysis)")
        argv = self.started()["argv"]
        self.assertEqual(argv[:2], ["omp", "--append-system-prompt"])
        self.assertTrue(argv[2].startswith(f"Engineer in {self.repo}\n\nHandover: "))
        self.assertEqual(argv[3:], ["--session-dir", str(self.repo / ".flow" / "sessions" / "E1S1")])
        self.assertEqual(self.root.config().read_bytes(), before)

    def test_back_from_in_review_to_in_development_is_allowed(self) -> None:
        status, _ = self.start("E1S3", "in-review", "in-development")
        self.assertEqual(status, 200)
        self.assertEqual(self.started()["task"], "Implement Review (E1S3) (from In review)")

    def test_same_column_continues_with_continue(self) -> None:
        status, _ = self.start("E1S2", "in-development", "in-development")
        self.assertEqual(status, 200)
        self.assertEqual(self.started()["task"], "Continue with E1S2")

    def test_continue_without_continue_section_is_refused(self) -> None:
        self.root.persona("in-review", REVIEWER_WITHOUT_CONTINUE)
        status, body = self.start("E1S3", "in-review", "in-review")
        self.assertEqual(status, 422)
        self.assertIn("Continue", body["error"])

    def test_drop_from_todo_on_in_analysis_starts_the_analyst_with_the_config_file(self) -> None:
        self.root.persona("in-analysis", ANALYST)
        status, _ = self.start("E1S4", "todo", "in-analysis")
        self.assertEqual(status, 200)
        self.assertEqual(self.started()["task"], f"Analyse {self.todo} with {self.root.config()} (from Todo)")

    def test_drop_from_todo_past_in_analysis_is_refused(self) -> None:
        status, body = self.start("E1S4", "todo", "in-development")
        self.assertEqual(status, 422)
        self.assertIn("not allowed", body["error"])
        self.assertEqual(self.app.commands, [])

    def test_drop_on_column_without_persona_is_refused(self) -> None:
        status, body = self.start("E1S2", "in-development", "in-review")
        self.assertEqual(status, 422)
        self.assertIn("has no persona", body["error"])

    def test_a_story_status_other_than_from_is_a_conflict(self) -> None:
        status, body = self.start("E1S1", "todo", "in-development")
        self.assertEqual(status, 409)
        self.assertIn("In analysis", body["error"])
        self.assertEqual(self.app.commands, [])

    def test_a_story_without_specification_is_not_found(self) -> None:
        self.assertEqual(self.start("E1S5", "todo", "in-analysis")[0], 404)
        self.assertEqual(self.start("E1S9", "todo", "in-analysis")[0], 404)

    def test_refuses_wrong_token_and_foreign_origin(self) -> None:
        self.assertEqual(self.start("E1S1", "in-analysis", "in-development", token="guess")[0], 403)
        self.assertEqual(self.start("E1S1", "in-analysis", "in-development", origin="https://evil.example")[0], 403)
        self.assertEqual(self.app.commands, [])

    def test_reports_herdr_app_failures(self) -> None:
        self.app.fail = "tab.new"
        status, body = self.start("E1S1", "in-analysis", "in-development")
        self.assertEqual(status, 502)
        self.assertIn("nope", body["error"])

    def test_working_tab_of_another_persona_is_a_conflict(self) -> None:
        busy = {"id": "tb1", "name": "E1S1 · Analyst", "terminals": [{"status": "working"}]}
        self.app.spaces = [{"id": "sp1", "name": "Demo", "tabs": [busy]}]
        status, body = self.start("E1S1", "in-analysis", "in-development")
        self.assertEqual(status, 409)
        self.assertIn("E1S1 · Analyst", body["error"])
        self.assertEqual(self.app.commands, [])


PRODUCT_OWNER = "---\nname: Product Owner\nmodel:\n---\n\n## Role\nBreak ideas down in {{path}}\n\n## Start\nRead {{config_file}} and {{spaces_file}}\n"


class ProductOwnerApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.repo = self.root.space([], name="Demo")
        self.app = FakeHerdrApp([{"id": "sp1", "name": "Demo", "tabs": [{"id": "tb1", "name": "E1S1 · Analyst", "terminals": []}]}])
        self.httpd = server.make_server(self.root.path, 0, TOKEN, self.app)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.client = Client(self.httpd.server_address[1], TOKEN)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.root.cleanup()

    def start(self, space: str = "demo", **options) -> tuple[int, dict]:
        return self.client.request("POST", f"/api/spaces/{space}/product-owner", {}, **options)

    def test_starts_a_fresh_conversation_in_the_home_space(self) -> None:
        self.root.persona("product-owner", PRODUCT_OWNER)

        status, body = self.start()

        self.assertEqual((status, body), (200, {"result": "started", "space": "Demo", "tab": "Product Owner"}))
        self.assertEqual(len(self.app.commands), 1)
        command, payload = self.app.commands[0]
        self.assertEqual(command, "tab.new")
        self.assertEqual(payload["folder"], str(self.repo))
        self.assertEqual(payload["argv"], ["omp", "--append-system-prompt", f"Break ideas down in {self.repo}"])
        self.assertEqual(payload["task"], f"Read {self.root.config()} and {self.root.path / 'spaces.json'}")

    def test_unknown_space_is_not_found(self) -> None:
        self.root.persona("product-owner", PRODUCT_OWNER)
        self.assertEqual(self.start("nope")[0], 404)
        self.assertEqual(self.app.commands, [])

    def test_missing_or_invalid_persona_is_refused(self) -> None:
        status, body = self.start()
        self.assertEqual(status, 422)
        self.assertIn("Product Owner has no persona", body["error"])

        self.root.persona("product-owner", PRODUCT_OWNER.replace("{{spaces_file}}", "{{story_id}}"))
        status, body = self.start()
        self.assertEqual(status, 422)
        self.assertIn("{{story_id}}", body["error"])
        self.assertEqual(self.app.commands, [])

    def test_refuses_wrong_token_and_foreign_origin(self) -> None:
        self.root.persona("product-owner", PRODUCT_OWNER)
        self.assertEqual(self.start(token="guess")[0], 403)
        self.assertEqual(self.start(origin="https://evil.example")[0], 403)
        self.assertEqual(self.app.commands, [])

    def test_reports_herdr_app_failures(self) -> None:
        self.root.persona("product-owner", PRODUCT_OWNER)
        self.app.fail = "tab.new"
        self.assertEqual(self.start()[0], 502)


if __name__ == "__main__":
    unittest.main()
