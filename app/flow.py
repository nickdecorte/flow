#!/usr/bin/env python3
"""Change a space's data from the command line, for agents.

    python3 app/flow.py status <space-path> <story-id> <status>

sets the story's status in `<space-path>/.flow/config.json`, with the same rules as the
dashboard: a known status, and a story without specification only on waiting-for-analysis
or done, one with a specification never on waiting-for-analysis. Transitions between
columns are not checked. A status change clears the story's `ready` flag.

    python3 app/flow.py ready <space-path> <story-id>

marks the story's current step as finished (`"ready": true`), for a story with a
specification on a persona column (In analysis, In development, In review). The card stays
in its column and shows green; a status change or a newly started agent clears the flag.

    python3 app/flow.py next <space-path> <story-id>

hands a ready story (`flow.py ready`) over to the persona of the next persona column, the
way a drop on the Board does: In analysis → In development, In development → In review.
Run by an agent in herdr (`HC_TERMINAL_ID` set), it only schedules the
handover: a detached worker (`flow.py _handover`) waits until that agent's turn has ended,
at most 30 minutes, starts the persona and writes every outcome to
`<space-path>/.flow/sessions/<story-id>/next.log`. When it fails while the agent's tab is
still open, it also tells that agent. Run from a shell, `next` starts the persona at once.

    python3 app/flow.py install

copies the omp extensions Flow ships (`omp/extensions/*.ts`) into omp's user extensions
folder, `~/.omp/agent/extensions` (or `$PI_CODING_AGENT_DIR/extensions`). omp sessions
load them when they start.

    python3 app/flow.py breakdown < breakdown.json

adds an approved breakdown into epics and stories, read as JSON from stdin:
`{"epics": [{"space": "<space path>", "epic": "E11" | null, "title": "<new epic title>",
"stories": [{"title": "…", "description": "…", "labels": ["…"]}]}]}`. Per entry exactly one
of `epic` (add to that existing epic) or `title` (a new epic), and at least one story. The
space is any space registered in `spaces.json` (`~` allowed). New stories get the next
`E<n>S<m>` and go on waiting-for-analysis. Every entry is checked before anything is
written; then each space's config is written once and the created IDs are printed, one
line per space: `<space>: E12 <title> (E12S1, E12S2); E11 (+E11S2)`.

On an error nothing is written or started; the message goes to stderr and the exit code is 1.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import herdr  # noqa: E402
import sdlc  # noqa: E402
import session  # noqa: E402

Spawn = Callable[[list[str], Path], None]
Wait = Callable[[str, float, herdr.Runner], str]
NEXT_LOG = "next.log"
EXTENSIONS = Path(__file__).resolve().parent.parent / "omp" / "extensions"
WAIT_SECONDS = 30 * 60
# How long herdr-app may take to show the agent's turn as ended too.
SETTLE_SECONDS = 60
ERRORS = (sdlc.NotFound, sdlc.SpaceError, sdlc.SpecificationConflict, sdlc.PersonaError, session.Refused,
          herdr.TabBusy, herdr.HerdrError, OSError, json.JSONDecodeError)


def breakdown(root: Path, text: str) -> str:
    """Apply the breakdown JSON `text`; the created IDs, one line per space, for stdout."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise sdlc.SpaceError(f"Invalid JSON: {error}") from error
    lines = []
    for space in sdlc.apply_breakdown(root, parsed):
        parts = [
            f"{epic['epic']} {epic['title']} ({', '.join(epic['stories'])})" if epic["title"] is not None
            else f"{epic['epic']} (+{', '.join(epic['stories'])})"
            for epic in space["epics"]
        ]
        lines.append(f"{space['space']}: {'; '.join(parts)}")
    return "\n".join(lines)


def status(path: str, story_id: str, value: str) -> str:
    config = sdlc.config_file(sdlc.expand_path(path))
    if not config.is_file():
        raise sdlc.NotFound(f"{config} does not exist")
    old, new = sdlc.set_story_status(config, story_id, value)
    return f"{story_id}: {old} → {new}"


def ready(path: str, story_id: str) -> str:
    config = sdlc.config_file(sdlc.expand_path(path))
    if not config.is_file():
        raise sdlc.NotFound(f"{config} does not exist")
    sdlc.set_story_ready(config, story_id)
    return f"{story_id}: ready"


def omp_extensions_dir() -> Path:
    """omp's user extensions folder: its agent folder (`PI_CODING_AGENT_DIR`, else `~/.omp/agent`) + `extensions`."""
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or "~/.omp/agent").expanduser() / "extensions"


def install(target: Path, source: Path = EXTENSIONS) -> str:
    """Copy every extension in `source` into `target`; one line per file, for stdout."""
    target.mkdir(parents=True, exist_ok=True)
    lines = []
    for file in sorted(source.glob("*.ts")):
        destination = target / file.name
        content = file.read_bytes()
        if destination.is_file() and destination.read_bytes() == content:
            lines.append(f"unchanged: {destination}")
            continue
        state = "updated" if destination.exists() else "installed"
        destination.write_bytes(content)
        lines.append(f"{state}: {destination}")
    if any(not line.startswith("unchanged") for line in lines):
        lines.append("Open omp sessions load the change when they start again.")
    return "\n".join(lines)


def spawn_worker(args: list[str], log: Path) -> None:
    """Run `flow.py _handover <args>` detached from this process and its terminal, output to `log`."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as out:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_handover", *args],
            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
        )


def next_story(root: Path, path: str, story_id: str, terminal: str | None,
               runner: herdr.Runner = herdr.run_herdr_app, spawn: Spawn = spawn_worker) -> str:
    """Hand the story at `path` over to the next persona; what happened, for stdout.

    Every check runs first: the story and its specification, a persona column followed by
    another one, the `ready` flag, a target column with a persona that renders. With `terminal`
    (the agent's own herdr terminal) a worker is spawned that starts the persona once that
    terminal is idle; without, it starts now.
    """
    state = sdlc.load_state(root)
    space = sdlc.space_at(state, path)
    specification = sdlc.state_specification(state, space["id"], story_id)
    source = specification["status"]
    target = session.next_target(source)
    if target is None:
        columns = " or ".join(sdlc.COLUMN_LABELS[column] for column in sdlc.PERSONA_COLUMNS[:-1])
        raise session.Refused(f"{story_id} is in {sdlc.COLUMN_LABELS[source]}; `flow.py next` only hands over from {columns}")
    if not specification["ready"]:
        raise session.Refused(f"{story_id} is not ready; run `flow.py ready` once the step in {sdlc.COLUMN_LABELS[source]} is complete")
    persona = session.prepare_story(root, space["id"], story_id, source, target)[2]
    if terminal:
        log_file = sdlc.session_dir(Path(space["path"]), story_id) / NEXT_LOG
        spawn([space["path"], story_id, terminal, source, target], log_file)
        return f"Handover to {persona['name']} scheduled: it starts when this turn has ended. Log: {log_file}"
    result = session.start_story(root, space["id"], story_id, source, target, runner)
    if result["result"] == "already_running":
        return f"Tab {result['tab']} in {result['space']} is already open; selected it"
    return f"Started {persona['name']} in tab {result['tab']} in {result['space']}"


def log(message: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def handover(root: Path, path: str, story_id: str, terminal: str, source: str, target: str,
             runner: herdr.Runner = herdr.run_herdr_app, hc: herdr.Runner = herdr.run_hc,
             wait: Wait = herdr.wait_terminal) -> int:
    """The worker behind `flow.py next`: start `target`'s persona once `terminal` has ended its turn.

    `source` is the status the story had at `next`; a status changed since is refused. Every
    outcome goes to stdout (the story's `next.log`); a failure is also typed into `terminal`
    while its tab is still open.
    """
    persona = sdlc.load_persona(root, target)
    name = persona["name"] if persona else sdlc.COLUMN_LABELS.get(target, target)
    log(f"Handover of {story_id} to {name}: waiting until {terminal} has ended its turn")
    try:
        state = wait(terminal, WAIT_SECONDS, hc)
        herdr.wait_app_settled(terminal, SETTLE_SECONDS, runner)
        log(f"{terminal} is {state}; starting {name}")
        space = sdlc.space_at(sdlc.load_state(root), path)
        result = session.start_story(root, space["id"], story_id, source, target, runner)
    except ERRORS as error:
        log(f"Handover to {name} failed: {error}")
        notify(terminal, f"Handover to {name} failed: {error}", hc)
        return 1
    log(f"Handover to {name} done: {result['result']} in tab {result['tab']} in {result['space']}")
    return 0


def notify(terminal: str, text: str, hc: herdr.Runner) -> None:
    """Type `text` into `terminal` while it still runs; once its tab has closed only the log remains."""
    try:
        if herdr.terminal_status(terminal, hc) == "finished":
            log(f"{terminal} has ended; the failure is only in this log")
            return
        herdr.send_if_idle(terminal, text, hc)
        log(f"Told {terminal}")
    except herdr.HerdrError as error:
        log(f"Could not tell {terminal}: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flow.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("status", help="set the status of a story")
    command.add_argument("path", help="path of the space (the folder with .flow/)")
    command.add_argument("story", help="story ID, e.g. E5S4")
    command.add_argument("status", help=", ".join(sdlc.STATUS_ORDER))
    command = commands.add_parser("ready", help="mark the story's current step as finished")
    command.add_argument("path", help="path of the space (the folder with .flow/)")
    command.add_argument("story", help="story ID, e.g. E5S4")
    command = commands.add_parser("next", help="hand a ready story over to the persona of the next column")
    command.add_argument("path", help="path of the space (the folder with .flow/)")
    command.add_argument("story", help="story ID, e.g. E5S4")
    commands.add_parser("install", help="install Flow's omp extensions into ~/.omp/agent/extensions")
    commands.add_parser("breakdown", help="add an approved breakdown (JSON on stdin) as epics and stories")
    command = commands.add_parser("_handover", help="internal: the worker `next` spawns")
    for name in ("path", "story", "terminal", "source", "target"):
        command.add_argument(name)
    args = parser.parse_args(argv)
    if args.command == "_handover":
        return handover(sdlc.ROOT, args.path, args.story, args.terminal, args.source, args.target)
    try:
        if args.command == "status":
            print(status(args.path, args.story, args.status))
        elif args.command == "ready":
            print(ready(args.path, args.story))
        elif args.command == "install":
            print(install(omp_extensions_dir()))
        elif args.command == "breakdown":
            print(breakdown(sdlc.ROOT, sys.stdin.read()))
        else:
            print(next_story(sdlc.ROOT, args.path, args.story, os.environ.get("HC_TERMINAL_ID")))
    except ERRORS as error:
        print(f"flow.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
