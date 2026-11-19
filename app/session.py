"""Starting a persona: a story's persona (a drop on the Board, `flow.py next`, `flow.py start`) and the Product Owner.

A drop and `flow.py next` open a herdr-app tab; `flow.py start`, behind the `flow-persona-*` omp
skills, hands the rendered persona to the agent that runs it, in its own conversation.
"""
from __future__ import annotations

import contextlib
import shlex
from datetime import date
from pathlib import Path

import herdr
import sdlc


class Refused(Exception):
    """The move between the columns is not allowed, or the persona does not exist."""


def next_target(status: str) -> str | None:
    """The persona column after the persona column `status`; None for In review and any other status."""
    if status not in sdlc.PERSONA_COLUMNS[:-1]:
        return None
    return sdlc.PERSONA_COLUMNS[sdlc.PERSONA_COLUMNS.index(status) + 1]


def handover_text(root: Path, column: str, space: dict, specification: dict, in_session: bool = False) -> str | None:
    """The paragraph appended to the role of `column`'s persona about handing over to the next persona.

    Only a persona column followed by another persona column gets one: once the step is marked
    ready, it asks the human whether the next persona may continue and then runs `flow.py next`
    (a new tab) or, `in_session`, follows the next persona's skill in the same conversation;
    when that column has no persona or no skill, it tells the human to drag the card.
    """
    target = next_target(column)
    if target is None:
        return None
    ready = flow_command("ready", space, specification)
    done = f"Handover: when your step is complete, that is, you have run `{ready}` and finished your report,"
    persona = sdlc.load_persona(root, target)
    if persona is None:
        return (
            f"{done} tell the human that {sdlc.COLUMN_LABELS[target]} has no persona, "
            "so they continue by dragging the card on the Board."
        )
    name = persona["name"]
    if not in_session:
        command = flow_command("next", space, specification)
        return (
            f"{done} end the report with the question \"Shall I continue with {name}?\". "
            f"Only when the human answers yes, run `{command}` and end your turn without any further output: "
            f"{name} then takes over this conversation in a new tab and this tab closes. "
            "Never run that command without that yes, and never before your step is complete."
        )
    skill = sdlc.PERSONA_SKILLS.get(target)
    if skill is None:
        return (
            f"{done} tell the human that {name} has no skill, "
            f"so they continue by dragging the card to {sdlc.COLUMN_LABELS[target]} on the Board."
        )
    return (
        f"{done} end the report with the question \"Shall I continue with {name}?\". "
        f"Only when the human answers yes, read `skill://{skill}` and follow it for story {specification['story']} "
        f"in `{space['path']}`: {name} then takes over in this conversation. "
        "Never do that without that yes, and never before your step is complete."
    )


def flow_command(command: str, space: dict, specification: dict) -> str:
    """`python3 <flow.py> <command> <space path> <story>`, quoted for a shell."""
    return " ".join(shlex.quote(part) for part in ("python3", str(sdlc.FLOW_SCRIPT), command, space["path"], specification["story"]))


def prepare_story(root: Path, space_id: str, story_id: str, source: str, target: str,
                  in_session: bool = False) -> tuple[dict, dict, dict]:
    """Every check before a start: the specification, its space and the rendered persona of `target`.

    `source` is the column the caller saw the specification in; the story's status must still be
    that. `target == source` continues in that column with the persona's Continue; any other pair
    must be an allowed drop. Raises `sdlc.NotFound`, `sdlc.SpecificationConflict`, `Refused` or
    `sdlc.PersonaError`. `in_session` renders the handover for a start in the same conversation.
    """
    state = sdlc.load_state(root)
    specification = sdlc.state_specification(state, space_id, story_id)
    space = sdlc.state_space(state, space_id)
    if source != specification["status"]:
        raise sdlc.SpecificationConflict(
            f"The specification is now in {sdlc.COLUMN_LABELS[specification['status']]}. Refresh the dashboard."
        )
    mode = "continue" if target == source else "start"
    target_label = sdlc.COLUMN_LABELS.get(target, str(target))
    if mode == "start" and not sdlc.drop_allowed(source, target):
        raise Refused(f"{sdlc.COLUMN_LABELS[source]} → {target_label} is not allowed")
    persona = sdlc.load_persona(root, target)
    if persona is None:
        raise Refused(f"{target_label} has no persona")
    handover = handover_text(root, target, space, specification, in_session)
    return specification, space, sdlc.render_persona(persona, specification, space, source, mode, handover)


def start_story(root: Path, space_id: str, story_id: str, source: str, target: str,
                runner: herdr.Runner = herdr.run_herdr_app,
                write_lock: contextlib.AbstractContextManager = contextlib.nullcontext()) -> dict:
    """Start the persona of `target` for the story's specification, on the story's session folder.

    A newly started agent begins a new step, so it clears the story's `ready` (under `write_lock`);
    selecting an already open tab leaves it. Raises what `prepare_story` raises before any
    herdr-app command, then `herdr.TabBusy` or `herdr.HerdrError`.
    """
    specification, space, rendered = prepare_story(root, space_id, story_id, source, target)
    result = herdr.start_session(specification, space, rendered, sdlc.session_dir(Path(space["path"]), story_id), runner)
    if result["result"] == "started":
        with write_lock:
            sdlc.clear_story_ready(Path(space["config"]), story_id)
    return result


def start_in_session(root: Path, path: str, story_id: str, target: str, today: date) -> dict:
    """Start `target`'s persona for the story in the space at `path` in the caller's own conversation.

    The story's current status is the source of a drop onto `target`, with every check of a drop;
    the same status continues with the persona's Continue. The Analyst first creates the empty
    specification of a story without one (the story goes to Todo). A new step clears `ready`.
    Returns the rendered persona; raises what `prepare_story` and `sdlc.create_specification` raise.
    """
    state = sdlc.load_state(root)
    space = sdlc.space_at(state, path)
    story = next((s for e in space["epics"] for s in e["stories"] if s["id"] == story_id), None)
    if target == sdlc.ANALYSIS_COLUMN and story is not None and story["specification"] is None:
        sdlc.create_specification(root, space["id"], story_id, today)
        state = sdlc.load_state(root)
    source = sdlc.state_specification(state, space["id"], story_id)["status"]
    space, rendered = prepare_story(root, space["id"], story_id, source, target, in_session=True)[1:]
    sdlc.clear_story_ready(Path(space["config"]), story_id)
    return rendered


def product_owner_persona(root: Path, space: dict) -> dict:
    """The Product Owner rendered with `space` as its home space; `Refused` without a persona."""
    persona = sdlc.load_persona(root, sdlc.PRODUCT_OWNER)
    if persona is None:
        raise Refused("Product Owner has no persona")
    return sdlc.render_product_owner(root, persona, space)


def start_product_owner(root: Path, space_id: str, runner: herdr.Runner = herdr.run_herdr_app) -> dict:
    """Start the Product Owner with `space_id` as its home space, or select its open tab.

    Raises `sdlc.NotFound`, `Refused` or `sdlc.PersonaError` before any herdr-app command,
    then `herdr.HerdrError`.
    """
    space = sdlc.registered_space(root, space_id)
    return herdr.start_product_owner(space, product_owner_persona(root, space), runner)
