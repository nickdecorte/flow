"""The page and the Vite build it loads: `/` with the token, `/assets/<file>` and nothing outside it."""
import http.client
import threading
import unittest

from support import Root

import server


class PageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Root()
        self.root.space([{"id": "SET-05", "title": "Products"}])
        self.httpd = server.make_server(self.root.path, 0, "secret")
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.root.cleanup()

    def get(self, path: str) -> tuple[int, bytes, str]:
        """A raw request, so a path with `..` reaches the server unnormalised."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        connection.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", f"127.0.0.1:{self.port}")
        connection.endheaders()
        response = connection.getresponse()
        body = response.read()
        content_type = response.headers.get("Content-Type", "")
        connection.close()
        return response.status, body, content_type

    def test_page_carries_the_session_token(self) -> None:
        status, body, content_type = self.get("/")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('<meta name="sdlc-token" content="secret" />', page)
        self.assertNotIn("__TOKEN__", page)

    def test_bundles_are_served_with_their_content_type(self) -> None:
        for file in sorted(server.ASSETS.iterdir()):
            if file.suffix in (".js", ".css"):
                with self.subTest(file.name):
                    status, body, content_type = self.get(f"/assets/{file.name}")
                    self.assertEqual(status, 200)
                    self.assertEqual(content_type, server.CONTENT_TYPES[file.suffix])
                    self.assertEqual(body, file.read_bytes())

    def test_the_token_is_not_in_the_bundle(self) -> None:
        for file in server.ASSETS.iterdir():
            with self.subTest(file.name):
                self.assertNotIn(b"__TOKEN__", file.read_bytes())

    def test_paths_outside_the_assets_folder_are_not_found(self) -> None:
        for path in ("/assets/../sdlc.py", "/assets/../../spaces.json", "/assets/nope.js", "/assets/"):
            with self.subTest(path):
                status, body, _ = self.get(path)
                self.assertEqual(status, 404)
                self.assertIn(b"error", body)


if __name__ == "__main__":
    unittest.main()
