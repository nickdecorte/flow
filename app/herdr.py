"""Starting an agent session in the Herdr desktop app (herdr-app).

A story's session opens as a tab named after the story and the persona, in the herdr-app
space named after the specification's space. When that tab already exists, it is
selected instead, so dragging twice never starts the same persona twice on one story.
A new session first closes the story's tabs of another persona or with the old name
(the story ID only); when the agent in one of them is still working, nothing starts.
Every persona of a story runs `omp` on the story's session folder, so the next persona
resumes the same conversation with its own role and model.

The Product Owner belongs to no story: its tab is named after the persona, opens with a
fresh `omp` conversation (no session folder) and closes no other tab.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str]], subprocess.CompletedProcess]
TIMEOUT_SECONDS = 30
# One `hc wait` checks in after this many seconds; the caller's deadline decides when to give up.
HC_WAIT_SECONDS = 60
# How often a blocked terminal (a question or permission prompt) is looked at again.
BLOCKED_POLL_SECONDS = 5
# Agent states that mean its turn has not ended yet.
BUSY_STATES = ("working", "blocked")
# Agent states in which it waits for input: `done` is the state right after a turn.
IDLE_STATES = ("idle", "done", "error")


class HerdrError(Exception):
    """herdr-app or hc refused a command or could not be reached."""


class TabBusy(Exception):
    """A matching tab of another persona or with the old name still has a working agent."""


def run_herdr_app(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["herdr-app", *args], capture_output=True, text=True, timeout=TIMEOUT_SECONDS)


def run_hc(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["hc", *args], capture_output=True, text=True, timeout=HC_WAIT_SECONDS + TIMEOUT_SECONDS)


def tab_name(specification: dict, persona: dict) -> str:
    """`E5S4 · Engineer`: the specification's story, then the persona's name."""
    return f"{story_part(specification)} · {persona['name']}"


def story_part(specification: dict) -> str:
    return specification["story"]


def agent_argv(persona: dict, session_dir: Path | None) -> list[str]:
    """`omp` with the persona's role and model, on the story's session folder `session_dir` when given.

    `--continue` resumes the folder's session once it holds one (a `*.jsonl` file). Without
    `session_dir`, omp starts a fresh conversation in its default session folder.
    """
    argv = ["omp", "--append-system-prompt", persona["role"]]
    if persona["model"]:
        argv += ["--model", persona["model"]]
    if session_dir is None:
        return argv
    argv += ["--session-dir", str(session_dir)]
    if any(session_dir.glob("*.jsonl")):
        argv.append("--continue")
    return argv


def story_tabs(tabs: list[dict], specification: dict) -> list[dict]:
    """The story's tabs: `<story> · <persona>`, or the old name (story ID only).

    The ` · ` boundary keeps `E8S1` from matching `E8S10`.
    """
    part = story_part(specification)
    return [t for t in tabs if t["name"] == part or t["name"].startswith(f"{part} · ")]


def matching_tabs(tabs: list[dict], specification: dict, tab: str) -> list[dict]:
    """The story's tabs other than `tab`: the old name or another persona."""
    return [t for t in story_tabs(tabs, specification) if t["name"] != tab]


def is_working(tab: dict) -> bool:
    return any(t.get("status") == "working" for t in tab.get("terminals", []))


def refuse_busy(tabs: list[dict], opened: dict) -> None:
    """`TabBusy` when one of `tabs` in the herdr-app space `opened` still has a working agent."""
    busy = [t["name"] for t in tabs if is_working(t)]
    if busy:
        raise TabBusy(
            f"Tab {', '.join(busy)} in {opened['name']} is still working. Close it or wait until it is done."
        )


def opened_space(runner: Runner, space: dict) -> dict | None:
    """The herdr-app space named after `space`, or None when herdr-app has none."""
    return next((s for s in call(runner, ["ls"]).get("spaces", []) if s["name"] == space["name"]), None)


def call(runner: Runner, args: list[str], program: str = "herdr-app") -> dict:
    try:
        result = runner(args)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HerdrError(f"{program} unreachable: {error}") from error
    output = result.stdout.strip()
    try:
        payload = json.loads(output) if output else {}
    except json.JSONDecodeError:
        payload = {}
    if result.returncode != 0 or "error" in payload:
        error = payload.get("error")
        message = (error.get("message") if isinstance(error, dict) else error) or result.stderr.strip() or f"exit {result.returncode}"
        raise HerdrError(f"{program} {' '.join(args[:2])}: {message}")
    return payload


def do(runner: Runner, command: str, args: dict) -> dict:
    return call(runner, ["do", command, json.dumps(args)])


def start_tab(runner: Runner, space: dict, tab: str, session: dict, opened: dict | None) -> dict:
    """Select the tab named `tab` in the herdr-app space `opened`, or open it with `session`.

    `opened` is the herdr-app space named after `space` (from `opened_space`); None creates it.
    """
    if opened is None:
        return new_space(runner, space, tab, session)
    existing = next((t for t in opened["tabs"] if t["name"] == tab), None)
    if existing is not None:
        do(runner, "tab.select", {"id": existing["id"]})
        return {"result": "already_running", "space": opened["name"], "tab": tab}
    do(runner, "tab.new", {"space": opened["id"], "name": tab, **session})
    return {"result": "started", "space": opened["name"], "tab": tab}


def start_session(specification: dict, space: dict, persona: dict, session_dir: Path, runner: Runner = run_herdr_app) -> dict:
    """Open the story's tab for the persona with `omp`, or select it when it is already open.

    `persona` is rendered: its role and start text hold the specification's values. The tab is
    named after the story and the persona, so one session runs per story and persona.
    The session starts in `space["path"]`, in the herdr-app space named `space["name"]`, with
    `session_dir` as its `omp` session folder.
    Before a new session opens, the story's tabs of another persona or with the old name
    are closed; when that empties the herdr-app space, the space is created again.
    Raises `TabBusy`, before any command runs, when such a tab still has a working agent.
    """
    tab = tab_name(specification, persona)
    opened = opened_space(runner, space)
    session = {"folder": space["path"], "argv": agent_argv(persona, session_dir), "task": persona["task"]}

    if opened is not None and not any(t["name"] == tab for t in opened["tabs"]):
        matching = matching_tabs(opened["tabs"], specification, tab)
        refuse_busy(matching, opened)
        for t in matching:
            do(runner, "tab.close", {"id": t["id"], "confirmed": True})
        if matching and len(matching) == len(opened["tabs"]):
            opened = None
    return start_tab(runner, space, tab, session, opened)


def start_product_owner(space: dict, persona: dict, runner: Runner = run_herdr_app) -> dict:
    """Open the Product Owner's tab, named after the persona, in the herdr-app space of its home `space`,
    or select it when it is already open.

    `persona` is rendered (`sdlc.render_product_owner`). The session is a fresh `omp`
    conversation in `space["path"]`; no other tab is closed.
    """
    session = {"folder": space["path"], "argv": agent_argv(persona, None), "task": persona["task"]}
    return start_tab(runner, space, persona["name"], session, opened_space(runner, space))


def close_story(specification: dict, space: dict, runner: Runner = run_herdr_app) -> list[dict]:
    """Close every tab of the story in the herdr-app space named `space["name"]`; the closed tabs.

    Raises `TabBusy`, before any command runs, when one of them still has a working agent.
    Without that herdr-app space there is nothing to close.
    """
    opened = opened_space(runner, space)
    if opened is None:
        return []
    tabs = story_tabs(opened["tabs"], specification)
    refuse_busy(tabs, opened)
    for t in tabs:
        do(runner, "tab.close", {"id": t["id"], "confirmed": True})
    return tabs


def tab_terminals(tabs: list[dict]) -> list[str]:
    """The hc addresses of the terminals in `tabs`."""
    return [t["terminal"] for tab in tabs for t in tab.get("terminals", []) if t.get("terminal")]


def new_space(runner: Runner, space: dict, tab: str, session: dict) -> dict:
    do(runner, "space.new", {"name": space["name"], "tab": tab, **session})
    return {"result": "started", "space": space["name"], "tab": tab}


# --- An agent's own terminal, through hc -------------------------------------------

def terminal_status(terminal: str, runner: Runner = run_hc) -> str:
    """The agent state of `terminal`: idle, working, done, blocked or error; `finished` once it has ended."""
    payload = call(runner, ["get", terminal, "--json"], "hc")
    if payload.get("state") != "live":
        return "finished"
    return (payload.get("status") or {}).get("state", "idle")


def wait_terminal(terminal: str, timeout: float, runner: Runner = run_hc,
                  sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> str:
    """Wait until `terminal` is no longer working or blocked, at most `timeout` seconds; its state then.

    A working terminal is waited on with `hc wait`; a blocked one is looked at again every few seconds.
    Raises `HerdrError` when the time is up or hc fails.
    """
    deadline = clock() + timeout
    while True:
        state = terminal_status(terminal, runner)
        if state not in BUSY_STATES:
            return state
        remaining = deadline - clock()
        if remaining <= 0:
            raise HerdrError(f"{terminal} is still {state} after {round(timeout / 60)} minutes")
        if state == "working":
            seconds = max(1, int(min(remaining, HC_WAIT_SECONDS)))
            call(runner, ["wait", terminal, "--json", "--timeout", str(seconds)], "hc")
        else:
            sleep(min(remaining, BLOCKED_POLL_SECONDS))


def wait_finished(terminals: list[str], timeout: float, runner: Runner = run_hc,
                  sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
    """Wait until every one of `terminals` has ended (or is gone), at most `timeout` seconds.

    herdr-app's `tab.close` returns before the program in the tab has exited. Raises `HerdrError`
    when the time is up.
    """
    deadline = clock() + timeout
    for terminal in terminals:
        while True:
            try:
                if terminal_status(terminal, runner) == "finished":
                    break
            except HerdrError:
                break
            if clock() >= deadline:
                raise HerdrError(f"{terminal} has not ended {round(timeout)} seconds after its tab closed")
            sleep(0.2)


def wait_app_settled(terminal: str, timeout: float, runner: Runner = run_herdr_app,
                     sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
    """Wait until herdr-app no longer shows `terminal` as working, at most `timeout` seconds.

    herdr-app takes an agent's status over from hc a few seconds later, and `start_session`
    refuses a story tab that herdr-app still shows as working. Raises `HerdrError` when the time is up.
    """
    deadline = clock() + timeout
    while any(
        t.get("terminal") == terminal and t.get("status") == "working"
        for space in call(runner, ["ls"]).get("spaces", []) for tab in space["tabs"] for t in tab.get("terminals", [])
    ):
        if clock() >= deadline:
            raise HerdrError(f"herdr-app still shows {terminal} as working after {round(timeout)} seconds")
        sleep(1)


def send_if_idle(terminal: str, text: str, runner: Runner = run_hc) -> dict:
    """Type `text` into `terminal` and press Enter, only when its agent waits for input.

    `hc send --if idle` refuses `done`, the state an agent has right after its turn, so the
    state is checked here instead. Raises `HerdrError` when nothing was typed.
    """
    state = terminal_status(terminal, runner)
    if state not in IDLE_STATES:
        raise HerdrError(f"{terminal} is {state}; nothing was typed")
    return call(runner, ["send", "--json", terminal, text], "hc")
