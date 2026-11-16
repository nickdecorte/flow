"""Starting a persona in herdr-app: a story's persona (a drop on the Board, `flow.py next`) and the Product Owner."""
from __future__ import annotations

import contextlib
import shlex
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


def handover_text(root: Path, column: str, space: dict, specification: dict) -> str | None:
    """The paragraph appended to the role of `column`'s persona about handing over to the next persona.

    Only a persona column followed by another persona column gets one: once the step is marked
    ready, it asks the human whether the next persona may continue and then runs `flow.py next`,
    or, when that column has no persona, tells the human to drag the card.
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
    command = flow_command("next", space, specification)
    return (
        f"{done} end the report with the question \"Shall I continue with {persona['name']}?\". "
        f"Only when the human answers yes, run `{command}` and end your turn without any further output: "
        f"{persona['name']} then takes over this conversation in a new tab and this tab closes. "
        "Never run that command without that yes, and never before your step is complete."
    )


def flow_command(command: str, space: dict, specification: dict) -> str:
    """`python3 <flow.py> <command> <space path> <story>`, quoted for a shell."""
    return " ".join(shlex.quote(part) for part in ("python3", str(sdlc.FLOW_SCRIPT), command, space["path"], specification["story"]))


def prepare_story(root: Path, space_id: str, story_id: str, source: str, target: str) -> tuple[dict, dict, dict]:
    """Every check before a start: the specification, its space and the rendered persona of `target`.

    `source` is the column the caller saw the specification in; the story's status must still be
    that. `target == source` continues in that column with the persona's Continue; any other pair
    must be an allowed drop. Raises `sdlc.NotFound`, `sdlc.SpecificationConflict`, `Refused` or
    `sdlc.PersonaError`.
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
    handover = handover_text(root, target, space, specification)
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


def start_product_owner(root: Path, space_id: str, runner: herdr.Runner = herdr.run_herdr_app) -> dict:
    """Start the Product Owner with `space_id` as its home space, or select its open tab.

    Raises `sdlc.NotFound`, `Refused` or `sdlc.PersonaError` before any herdr-app command,
    then `herdr.HerdrError`.
    """
    space = sdlc.registered_space(root, space_id)
    persona = sdlc.load_persona(root, sdlc.PRODUCT_OWNER)
    if persona is None:
        raise Refused("Product Owner has no persona")
    return herdr.start_product_owner(space, sdlc.render_product_owner(root, persona, space), runner)
