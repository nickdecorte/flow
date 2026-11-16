#!/usr/bin/env python3
"""The SDLC dashboard: a JSON API over spaces and their specifications, the page that shows them,
starting an agent session for a story's specification in the Herdr desktop app, and live updates
(agent states, changed files) as server-sent events on `/api/events`.

Listens on 127.0.0.1 only and refuses any other Host header, so a web page
elsewhere cannot reach it through DNS rebinding. It sends no CORS headers. Every write
(POST, PUT, PATCH, DELETE) also needs this page's Origin and the token the server put in the page.

Usage: python3 app/server.py [--port 8765]
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import secrets
import shutil
import sys
import threading
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import herdr  # noqa: E402
import live  # noqa: E402
import sdlc  # noqa: E402
import session  # noqa: E402

DEFAULT_PORT = 8765
STATIC = Path(__file__).resolve().parent / "static"
PAGE = STATIC / "index.html"
ASSETS = STATIC / "assets"
# The hashed bundles Vite writes next to the page; everything else is served as a download.
CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
}
# Only a guard against a runaway request: persona saves carry the whole Role, Start and Continue,
# and a Role can reach about 1 MiB before macOS refuses to start the agent (ARG_MAX).
MAX_BODY = 16 * 1024 * 1024
# How long Done waits for the programs in the story's closed tabs to exit before it deletes the session.
CLOSE_SECONDS = 10
# How often `/api/events` writes a comment when nothing happened, so a dead connection is noticed.
KEEPALIVE_SECONDS = 15
SPACE = re.compile(r"/api/spaces/([^/]+)")
SPECIFICATION = re.compile(r"/api/spaces/([^/]+)/stories/([^/]+)/specification")
SPECIFICATION_ACTION = re.compile(r"/api/spaces/([^/]+)/stories/([^/]+)/specification/(start|complete)")
EPICS = re.compile(r"/api/spaces/([^/]+)/epics")
EPIC = re.compile(r"/api/spaces/([^/]+)/epics/([^/]+)")
EPIC_STORIES = re.compile(r"/api/spaces/([^/]+)/epics/([^/]+)/stories")
STORY = re.compile(r"/api/spaces/([^/]+)/stories/([^/]+)")
DELETION = re.compile(r"/api/spaces/([^/]+)/deletion")
PRODUCT_OWNER = re.compile(r"/api/spaces/([^/]+)/product-owner")


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def specification_summary(specification: dict) -> dict:
    return {key: value for key, value in specification.items() if key != "body"}


def persona_summary(root: Path, key: str) -> dict:
    persona = sdlc.load_persona(root, key)
    empty = {"name": "", "model": "", "role": "", "start": "", "continue": "", "version": None, "editable": True, "problem": None}
    return {"key": key, "label": sdlc.PERSONA_LABELS[key], "exists": persona is not None, **(persona or empty)}


def space_summary(space: dict) -> dict:
    stories = [story for epic in space["epics"] for story in epic["stories"]]
    return {
        "id": space["id"],
        "name": space["name"],
        "title": space["title"],
        "path": space["path"],
        "counts": {s: sum(1 for story in stories if story["status"] == s) for s in sdlc.STATUS_ORDER},
    }


def find_space(state: dict, space_id: str) -> dict:
    try:
        return sdlc.state_space(state, space_id)
    except sdlc.NotFound as error:
        raise ApiError(HTTPStatus.NOT_FOUND, str(error)) from error


def find_specification(state: dict, space_id: str, story_id: str) -> dict:
    """The specification of `story_id` in `space_id`; 404 when the space or story does not exist or has none."""
    try:
        return sdlc.state_specification(state, space_id, story_id)
    except sdlc.NotFound as error:
        raise ApiError(HTTPStatus.NOT_FOUND, str(error)) from error


def make_handler(root: Path, token: str, runner: herdr.Runner, hc: herdr.Runner,
                 hub: live.Hub | None) -> type[BaseHTTPRequestHandler]:
    write_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "sdlc-dashboard"

        def allowed_hosts(self) -> set[str]:
            port = self.server.server_address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self) -> None:
            self.handle_request(self.route_get)

        def do_POST(self) -> None:
            self.handle_request(self.route_post)

        def do_PUT(self) -> None:
            self.handle_request(self.route_put)

        def do_PATCH(self) -> None:
            self.handle_request(self.route_patch)

        def do_DELETE(self) -> None:
            self.handle_request(self.route_delete)

        def handle_request(self, route) -> None:
            try:
                if self.headers.get("Host") not in self.allowed_hosts():
                    raise ApiError(HTTPStatus.FORBIDDEN, "Unknown Host")
                route(unquote(urlsplit(self.path).path))
            except ApiError as error:
                self.send_json({"error": error.message}, error.status)

        def route_get(self, path: str) -> None:
            if path == "/":
                page = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", token)
                return self.send_body(page.encode("utf-8"), "text/html; charset=utf-8")
            if path.startswith("/assets/"):
                return self.send_asset(path.removeprefix("/assets/"))
            if path == "/api/meta":
                return self.send_json(sdlc.meta())
            if path == "/api/events":
                return self.stream_events()
            if path == "/api/personas":
                return self.send_json([persona_summary(root, key) for key in sdlc.PERSONAS])
            deletion = DELETION.fullmatch(path)
            if deletion:
                return self.deletion(deletion.group(1))
            state = sdlc.load_state(root)
            if path == "/api/spaces":
                return self.send_json([space_summary(s) for s in state["spaces"]])
            if path == "/api/specifications":
                return self.send_json([specification_summary(s) for s in state["specifications"]])
            specification = SPECIFICATION.fullmatch(path)
            if specification:
                found = find_specification(state, *specification.groups())
                return self.send_json({**specification_summary(found), "html": sdlc.specification_html(found)})
            space = SPACE.fullmatch(path)
            if space:
                return self.send_json(find_space(state, space.group(1)))
            raise ApiError(HTTPStatus.NOT_FOUND, "Unknown route")

        def route_post(self, path: str) -> None:
            action = SPECIFICATION_ACTION.fullmatch(path)
            if action:
                self.check_origin_and_token()
                space_id, story_id, verb = action.groups()
                if verb == "start":
                    return self.start(space_id, story_id, self.read_json())
                return self.complete(space_id, story_id, self.read_json())
            if path == "/api/spaces":
                self.check_origin_and_token()
                payload = self.read_json()
                return self.change_space(sdlc.create_space, payload.get("name"), payload.get("path"))
            product_owner = PRODUCT_OWNER.fullmatch(path)
            if product_owner:
                self.check_origin_and_token()
                return self.start_product_owner(product_owner.group(1))
            specification = SPECIFICATION.fullmatch(path)
            if specification:
                self.check_origin_and_token()
                return self.create_specification(*specification.groups())
            epics = EPICS.fullmatch(path)
            epic_stories = EPIC_STORIES.fullmatch(path)
            if epics or epic_stories:
                self.check_origin_and_token()
                payload = self.read_json()
                version = payload.pop("version", None)
                if epics:
                    return self.change_space(sdlc.create_epic, epics.group(1), payload.get("title"), version)
                return self.change_space(sdlc.create_story, *epic_stories.groups(), payload, version)
            raise ApiError(HTTPStatus.NOT_FOUND, "Unknown route")

        def route_patch(self, path: str) -> None:
            epic, story = EPIC.fullmatch(path), STORY.fullmatch(path)
            if not (epic or story):
                raise ApiError(HTTPStatus.NOT_FOUND, "Unknown route")
            self.check_origin_and_token()
            payload = self.read_json()
            version = payload.pop("version", None)
            if epic and "position" in payload:
                return self.change_space(sdlc.move_epic, *epic.groups(), payload["position"], version)
            if epic:
                return self.change_space(sdlc.update_epic, *epic.groups(), payload.get("title"), version)
            return self.change_space(sdlc.update_story, *story.groups(), payload, version)

        def change_space(self, action, *args) -> None:
            """Run a change to a space file under the write lock. A change to an existing file checks the `version` it gets."""
            with write_lock:
                try:
                    result = action(root, *args)
                except sdlc.NotFound as error:
                    raise ApiError(HTTPStatus.NOT_FOUND, str(error)) from error
                except sdlc.SpaceConflict as error:
                    raise ApiError(HTTPStatus.CONFLICT, str(error)) from error
                except sdlc.SpaceError as error:
                    raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
                except OSError as error:
                    raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, f"Saving failed: {error}") from error
            self.send_json(result)

        def deletion(self, space_id: str) -> None:
            """What `DELETE` of `?epic=` or `?story=` would remove, for the confirmation."""
            query = parse_qs(urlsplit(self.path).query)
            epic_id, story_id = query.get("epic", [None])[0], query.get("story", [None])[0]
            if (epic_id is None) == (story_id is None):
                raise ApiError(HTTPStatus.BAD_REQUEST, "Give exactly one of epic or story")
            try:
                self.send_json(sdlc.deletion_preview(root, space_id, epic_id, story_id))
            except sdlc.NotFound as error:
                raise ApiError(HTTPStatus.NOT_FOUND, str(error)) from error

        def create_specification(self, space_id: str, story_id: str) -> None:
            """An empty specification for the story, linked through its `specification` field; the story goes to todo."""
            with write_lock:
                try:
                    result = sdlc.create_specification(root, space_id, story_id, date.today())
                except sdlc.NotFound as error:
                    raise ApiError(HTTPStatus.NOT_FOUND, str(error)) from error
                except sdlc.SpecificationConflict as error:
                    raise ApiError(HTTPStatus.CONFLICT, str(error)) from error
                except OSError as error:
                    raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, f"Creating the specification failed: {error}") from error
            self.send_json(result)

        def complete(self, space_id: str, story_id: str, payload: dict) -> None:
            """Set the story to done. `from` is the column the page saw its specification in.

            After the status checks, the story's tabs in herdr-app close and its session folder
            goes; while one of its tabs is working (409) or herdr-app fails (502), nothing changes.
            """

            def end_session(space: dict) -> None:
                closed = herdr.close_story({"story": story_id}, space, runner)
                herdr.wait_finished(herdr.tab_terminals(closed), CLOSE_SECONDS, hc)
                try:
                    shutil.rmtree(sdlc.session_dir(Path(space["path"]), story_id))
                except FileNotFoundError:
                    pass

            with write_lock:
                try:
                    result = sdlc.complete_specification(root, space_id, story_id, payload.get("from"), end_session)
                except sdlc.NotFound as error:
                    raise ApiError(HTTPStatus.NOT_FOUND, str(error)) from error
                except (sdlc.SpecificationConflict, herdr.TabBusy) as error:
                    raise ApiError(HTTPStatus.CONFLICT, str(error)) from error
                except herdr.HerdrError as error:
                    raise ApiError(HTTPStatus.BAD_GATEWAY, str(error)) from error
                except OSError as error:
                    raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, f"Closing failed: {error}") from error
            self.send_json(result)

        def persona_key(self, path: str) -> str:
            key = path.removeprefix("/api/personas/")
            if not path.startswith("/api/personas/") or key not in sdlc.PERSONAS:
                raise ApiError(HTTPStatus.NOT_FOUND, "Unknown persona")
            return key

        def route_put(self, path: str) -> None:
            key = self.persona_key(path)
            self.check_origin_and_token()
            payload = self.read_json()
            with write_lock:
                try:
                    sdlc.save_persona(root, key, payload, payload.get("version"))
                except sdlc.PersonaConflict as error:
                    raise ApiError(HTTPStatus.CONFLICT, str(error)) from error
                except sdlc.PersonaError as error:
                    raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
            self.send_json(persona_summary(root, key))

        def route_delete(self, path: str) -> None:
            epic, story = EPIC.fullmatch(path), STORY.fullmatch(path)
            if epic or story:
                self.check_origin_and_token()
                version = parse_qs(urlsplit(self.path).query).get("version", [None])[0]
                if epic:
                    return self.change_space(sdlc.delete_epic, *epic.groups(), version)
                return self.change_space(sdlc.delete_story, *story.groups(), version)
            key = self.persona_key(path)
            self.check_origin_and_token()
            version = parse_qs(urlsplit(self.path).query).get("version", [""])[0]
            with write_lock:
                try:
                    sdlc.delete_persona(root, key, version)
                except sdlc.PersonaConflict as error:
                    raise ApiError(HTTPStatus.CONFLICT, str(error)) from error
            self.send_json(persona_summary(root, key))

        def check_origin_and_token(self) -> None:
            if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                raise ApiError(HTTPStatus.FORBIDDEN, "Unknown Origin")
            if not secrets.compare_digest(self.headers.get("X-SDLC-Token", ""), token):
                raise ApiError(HTTPStatus.FORBIDDEN, "Invalid token")

        def read_json(self) -> dict:
            length_header = self.headers.get("Content-Length") or "0"
            if not length_header.isdigit():
                raise ApiError(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            length = int(length_header)
            if length > MAX_BODY:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Body too large")
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as error:
                raise ApiError(HTTPStatus.BAD_REQUEST, f"Invalid JSON: {error}") from error
            if not isinstance(payload, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "Body must be a JSON object")
            return payload

        def start(self, space_id: str, story_id: str, payload: dict) -> None:
            """Start the persona of the column the story's specification was dropped on (`to`).

            `from` is the column the page saw the specification in; the story's status must
            still be that. `to == from` continues in that column with the persona's Continue;
            any other pair must be an allowed drop.
            """
            try:
                result = session.start_story(root, space_id, story_id, payload.get("from"), payload.get("to"), runner, write_lock)
            except sdlc.NotFound as error:
                raise ApiError(HTTPStatus.NOT_FOUND, str(error)) from error
            except (sdlc.SpecificationConflict, herdr.TabBusy) as error:
                raise ApiError(HTTPStatus.CONFLICT, str(error)) from error
            except (session.Refused, sdlc.PersonaError) as error:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
            except herdr.HerdrError as error:
                raise ApiError(HTTPStatus.BAD_GATEWAY, str(error)) from error
            self.send_json(result)

        def start_product_owner(self, space_id: str) -> None:
            """Start the Product Owner in the herdr-app space of `space_id`, or select its open tab."""
            try:
                result = session.start_product_owner(root, space_id, runner)
            except sdlc.NotFound as error:
                raise ApiError(HTTPStatus.NOT_FOUND, str(error)) from error
            except (session.Refused, sdlc.PersonaError) as error:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
            except herdr.HerdrError as error:
                raise ApiError(HTTPStatus.BAD_GATEWAY, str(error)) from error
            self.send_json(result)

        def stream_events(self) -> None:
            """Server-sent events from the hub: first the current `agents`, then every `agents` and `changed`."""
            if hub is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "Live updates are off")
            subscriber = hub.subscribe()
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                while True:
                    try:
                        kind, data = subscriber.get(timeout=KEEPALIVE_SECONDS)
                        chunk = f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        chunk = ": keep-alive\n\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                hub.unsubscribe(subscriber)

        def send_asset(self, name: str) -> None:
            """A file from the Vite build. Anything that resolves outside `static/assets/` is a 404."""
            file = (ASSETS / name).resolve()
            if ASSETS.resolve() not in file.parents or not file.is_file():
                raise ApiError(HTTPStatus.NOT_FOUND, "Unknown file")
            self.send_body(file.read_bytes(), CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

        def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_body(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def send_body(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            sys.stderr.write(f"{self.log_date_time_string()} {format % args}\n")

    return Handler


def make_server(root: Path, port: int, token: str, runner: herdr.Runner = herdr.run_herdr_app,
                hc: herdr.Runner = herdr.run_hc, hub: live.Hub | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(root, token, runner, hc, hub))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    hub = live.Hub(sdlc.ROOT)
    hub.start()
    server = make_server(sdlc.ROOT, args.port, secrets.token_urlsafe(32), hub=hub)
    for warning in sdlc.load_state(sdlc.ROOT)["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Flow at http://127.0.0.1:{server.server_address[1]}/ (root {sdlc.ROOT})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
