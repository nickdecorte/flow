"""A throwaway SDLC root on disk, and a client for the dashboard server, for tests."""
from __future__ import annotations

import http.client
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sdlc  # noqa: E402


class Root:
    """`path` holds `spaces.json` and `personas/`; each space lives in `work/<id>/` unless given a path."""

    def __init__(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name)
        (self.path / "personas").mkdir()
        self.folders: dict[str, Path] = {}

    def cleanup(self) -> None:
        self._dir.cleanup()

    def space(self, stories: list[dict], path: str | None = None, space_id: str = "demo", name: str = "Demo") -> Path:
        """A space with one epic E1 holding `stories`, registered under `path` as typed."""
        typed = path or str(self.path / "work" / space_id)
        folder = sdlc.expand_path(typed)
        sdlc.specifications_dir(folder).mkdir(parents=True, exist_ok=True)
        data = {
            "schemaVersion": 2,
            "space": {"id": space_id, "name": name, "title": f"{name} title"},
            "epics": [{"id": "E1", "title": "Epic", "stories": stories}],
        }
        self.write_config(folder, data)
        self.register(typed)
        self.folders[space_id] = folder
        return folder

    def register(self, typed: str) -> None:
        registry = sdlc.read_registry(self.path)
        if not any(entry["path"] == typed for entry in registry):
            (self.path / sdlc.REGISTRY).write_text(json.dumps([*registry, {"path": typed}]), encoding="utf-8")

    def config(self, space_id: str = "demo") -> Path:
        return sdlc.config_file(self.folders[space_id])

    def write_config(self, folder: Path, data: dict) -> None:
        sdlc.config_file(folder).write_text(json.dumps(data), encoding="utf-8")

    def specification(self, story: str | None, file: str, title: str, status: str | None = None, space_id: str = "demo",
                      front_matter: str = "", body: str = "", tasks: str = "- [ ] Task 1: Do it") -> Path:
        """A specification file; with `story`, that story links to it and gets `status` when given."""
        text = f"---\n{front_matter}\n---\n\n" if front_matter else ""
        text += f"# {title} Specification\n\n{body}\n\n## Implementation Checklist\n{tasks}\n"
        path = sdlc.specifications_dir(self.folders[space_id]) / file
        path.write_text(text, encoding="utf-8")
        if story is not None:
            data = json.loads(self.config(space_id).read_text(encoding="utf-8"))
            found = sdlc.find_story(data, story)[1]
            found["specification"] = file
            if status is not None:
                found["status"] = status
            self.write_config(self.folders[space_id], data)
        return path

    def persona(self, column: str, text: str) -> None:
        (self.path / "personas" / f"{column}.md").write_text(text, encoding="utf-8")


class Client:
    """Sends requests the way the dashboard page does: own Host and Origin, and the token."""

    def __init__(self, port: int, token: str):
        self.port = port
        self.token = token

    def request(self, method: str, path: str, body: dict | None = None, token: str | None = None, origin: str | None = None) -> tuple[int, dict]:
        host = f"127.0.0.1:{self.port}"
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        headers = {"Host": host, "Origin": origin or f"http://{host}", "X-SDLC-Token": self.token if token is None else token}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        result = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, result
