"""Live updates for the dashboard, pushed to every open page over server-sent events.

One `Hub` per server. It follows `hc events` and, on every event other than a terminal's
title, asks herdr-app (`ls`) for the story tabs and their agent states: the `agents` event.
It also looks at the modification times of `spaces.json`, every space's `config.json` and
every specification file once per second: the `changed` event, after which the page reloads.

herdr can be gone: while `hc events` is not running or `herdr-app ls` fails, `agents` says
`available: false` with no agents. A stopped `hc events` is started again after a few
seconds; an unavailable herdr-app is asked again every few seconds.
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

import herdr
import sdlc

Events = Callable[[], Iterable[str]]
# Ignored `hc events` types: the agent's spinner changes its title many times per second.
IGNORED_EVENTS = {"title"}
RESTART_SECONDS = 5
# The shortest time between two `herdr-app ls` calls; a later event is answered after it.
REFRESH_SECONDS = 0.25
WATCH_SECONDS = 1
OFFLINE = {"available": False, "agents": {}}


def hc_events() -> Iterator[str]:
    """The lines `hc events --json` prints, until it ends; the process ends with the iteration."""
    process = subprocess.Popen(["hc", "events", "--json"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        yield from process.stdout
    finally:
        process.kill()
        process.wait()


def relevant(line: str) -> bool:
    """Whether an `hc events` line can change an agent state: anything but an ignored event type."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return False
    return not (isinstance(event, dict) and (event.get("params") or {}).get("type") in IGNORED_EVENTS)


def agents_map(opened: list[dict], spaces: list[dict], specifications: list[dict]) -> dict:
    """`<space id>|<story>` → `{persona, state}` for every story with an agent in its tabs.

    `opened` are the herdr-app spaces from `ls`, matched to a Flow space by name. Only terminals
    with an agent state count; of several, a working one wins, else the first. `persona` is the
    part of the tab name after ` · `, None for a tab with the old name (the story ID only).
    """
    ids = {space["name"]: space["id"] for space in spaces}
    agents: dict[str, dict] = {}
    for space in opened:
        space_id = ids.get(space["name"])
        if space_id is None:
            continue
        for specification in (s for s in specifications if s["space"] == space_id):
            found = [
                {"persona": tab["name"].partition(" · ")[2] or None, "state": terminal["status"]}
                for tab in herdr.story_tabs(space.get("tabs", []), specification)
                for terminal in tab.get("terminals", []) if terminal.get("status")
            ]
            if found:
                agents[f"{space_id}|{specification['story']}"] = next((a for a in found if a["state"] == "working"), found[0])
    return agents


def file_stamps(root: Path) -> dict[str, tuple[int, int]]:
    """Modification time and size of `spaces.json`, every registered config and every specification file."""
    paths = [root / sdlc.REGISTRY]
    for entry in sdlc.read_registry(root):
        folder = sdlc.expand_path(entry["path"])
        paths.append(sdlc.config_file(folder))
        directory = sdlc.specifications_dir(folder)
        if directory.is_dir():
            paths.extend(directory.glob("*.md"))
    stamps = {}
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        stamps[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return stamps


class Hub:
    """Fans `agents` and `changed` out to every subscriber's queue."""

    def __init__(self, root: Path, runner: herdr.Runner = herdr.run_herdr_app, events: Events = hc_events,
                 sleep: Callable[[float], None] = time.sleep):
        self.root = root
        self.runner = runner
        self.events = events
        self.sleep = sleep
        self.lock = threading.Lock()
        self.subscribers: set[queue.Queue] = set()
        self.agents: dict = OFFLINE
        self.following = False
        self.stamps: dict | None = None
        self.dirty = threading.Event()

    def start(self) -> None:
        for target in (self.follow_herdr, self.refresh_loop, self.watch_files):
            threading.Thread(target=target, daemon=True).start()

    def subscribe(self) -> queue.Queue:
        """A queue that first holds the current `agents`, then every later event."""
        subscriber: queue.Queue = queue.Queue()
        with self.lock:
            subscriber.put(("agents", self.agents))
            self.subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self.lock:
            self.subscribers.discard(subscriber)

    def publish(self, kind: str, data: dict) -> None:
        with self.lock:
            if kind == "agents":
                if data == self.agents:
                    return
                self.agents = data
            for subscriber in self.subscribers:
                subscriber.put((kind, data))

    # --- herdr ---------------------------------------------------------------------

    def follow_herdr(self) -> None:
        """Follow `hc events` for good: start it again a while after it stops or cannot start."""
        while True:
            self.follow_once()
            self.sleep(RESTART_SECONDS)

    def follow_once(self) -> None:
        """Read `hc events` until it ends; every relevant line asks for a refresh. Offline after."""
        try:
            for line in self.events():
                self.following = True
                if relevant(line):
                    self.dirty.set()
        except OSError:
            pass
        self.following = False
        self.publish("agents", OFFLINE)

    def refresh_loop(self) -> None:
        """Answer refresh requests at most every REFRESH_SECONDS; retry an offline herdr-app now and then."""
        while True:
            self.dirty.wait(None if self.agents["available"] else RESTART_SECONDS)
            self.dirty.clear()
            if self.following:
                self.refresh_agents()
            self.sleep(REFRESH_SECONDS)

    def refresh_agents(self) -> None:
        """Ask herdr-app for the story tabs and push `agents` when they changed."""
        try:
            opened = herdr.call(self.runner, ["ls"]).get("spaces", [])
        except herdr.HerdrError:
            return self.publish("agents", OFFLINE)
        try:
            state = sdlc.load_state(self.root)
        except (OSError, ValueError):
            return None
        self.publish("agents", {"available": True, "agents": agents_map(opened, state["spaces"], state["specifications"])})

    # --- files ---------------------------------------------------------------------

    def watch_files(self) -> None:
        while True:
            self.check_files()
            self.sleep(WATCH_SECONDS)

    def check_files(self) -> None:
        """Push `changed` when a watched file changed since the last look; the first look only remembers."""
        try:
            stamps = file_stamps(self.root)
        except (OSError, ValueError):
            return
        if self.stamps is not None and stamps != self.stamps:
            self.publish("changed", {})
            self.dirty.set()
        self.stamps = stamps
