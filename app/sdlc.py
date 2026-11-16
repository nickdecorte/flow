"""The SDLC domain: spaces, their specifications and the Pipeline built from them.

Everything is read from disk on each call, so a change to a specification or a
space's config shows on the next request.

Layout:
    <root>/spaces.json                         the registry: `[{"path": "~/repo"}, …]`
    <path>/.flow/config.json                   a space: its ID, name, epics and stories
    <path>/.flow/specifications/*.md           its specifications, at most one per story
    <path>/.flow/sessions/<story>/             the story's `omp` session, resumed by every persona

A story's `status` puts its specification in a Pipeline column; a story's
`specification` field names its file in `.flow/specifications/`.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shlex
import shutil
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
# Flow's CLI, wherever this checkout lives; personas call it through `{{flow}}`.
FLOW_SCRIPT = ROOT / "app" / "flow.py"
FLOW_COMMAND = shlex.join(["python3", str(FLOW_SCRIPT)])

# The Pipeline's columns in pipeline order. A column's key is the story status that puts a
# card in it; `persona` says whether a persona handles the cards dropped on it.
COLUMNS = [
    {"key": "todo", "label": "Todo", "persona": False},
    {"key": "in-analysis", "label": "In analysis", "persona": True},
    {"key": "in-development", "label": "In development", "persona": True},
    {"key": "in-review", "label": "In review", "persona": True},
    {"key": "done", "label": "Done", "persona": False},
]
COLUMN_KEYS = [column["key"] for column in COLUMNS]
COLUMN_LABELS = {column["key"]: column["label"] for column in COLUMNS}
# `waiting-for-analysis` is a story without a specification yet: it has no column.
STATUS_ORDER = ["waiting-for-analysis", *COLUMN_KEYS]
STATUS_LABELS = {"waiting-for-analysis": "Waiting for analysis", **COLUMN_LABELS}
TASK_STATES = ["done", "waiting", "blocked", "pending", "dropped"]
TASK_LABELS = {
    "done": "Done",
    "waiting": "Waiting for manual action",
    "blocked": "Blocked",
    "pending": "To do",
    "dropped": "Dropped",
}
EXECUTION_MODES = ["per-task", "autonomous"]
DEFAULT_EXECUTION = "per-task"
REGISTRY = "spaces.json"
FLOW = ".flow"

TASK_LINE = re.compile(r"^\s*-\s+\[( |x|X)\]\s+(.*)$")
VARIABLE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class PersonaError(Exception):
    """A persona file that cannot be used: a missing section or an unknown variable."""


def expand_path(path: str) -> Path:
    return Path(path).expanduser()


def strip_md(text: str) -> str:
    return re.sub(r"[*`]", "", text).strip()


def meta() -> dict:
    """The fixed vocabulary the dashboard draws with."""
    return {
        "columns": [{"key": key, "label": COLUMN_LABELS[key]} for key in COLUMN_KEYS],
        "statusOrder": STATUS_ORDER,
        "statusLabels": STATUS_LABELS,
        "taskStates": TASK_STATES,
        "taskLabels": TASK_LABELS,
        "executionModes": EXECUTION_MODES,
        "personaColumns": PERSONA_COLUMNS,
        "personaKeys": PERSONAS,
        "personaVariables": PERSONA_VARIABLES,
        "transitions": transitions(),
        "todoColumn": TODO_COLUMN,
        "doneColumn": DONE_COLUMN,
    }


# --- Markdown to HTML, for showing specifications in the dashboard ------------------

def md_inline(text: str) -> str:
    """Code spans are set aside first, so bold and links may wrap them."""
    codes: list[str] = []

    def stash(match: re.Match) -> str:
        codes.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = html.escape(re.sub(r"`([^`]+)`", stash, text))
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2" target="_blank">\1</a>', text)
    return re.sub(r"\x00(\d+)\x00", lambda match: codes[int(match.group(1))], text)


def md_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def md_to_html(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    lists: list[tuple[int, str]] = []
    i = 0

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{md_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_lists(indent: int = -1) -> None:
        while lists and lists[-1][0] > indent:
            out.append(f"</li></{lists.pop()[1]}>")

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            close_lists()
            language = html.escape(stripped[3:].strip())
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(f'<pre><code class="lang-{language}">{html.escape(chr(10).join(code))}</code></pre>')
            i += 1
            continue

        if not stripped:
            flush_paragraph()
            close_lists()
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{md_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,})", stripped):
            flush_paragraph()
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|?[\s:|-]*-{2,}[\s:|-]*", lines[i + 1].strip()):
            flush_paragraph()
            close_lists()
            header = md_cells(stripped)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(md_cells(lines[i]))
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{md_inline(c)}</th>" for c in header) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{md_inline(c)}</td>" for c in row) + "</tr>" for row in rows)
                       + "</tbody></table>")
            continue

        item = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if item:
            flush_paragraph()
            indent = len(item.group(1).expandtabs(4))
            tag = "ol" if item.group(2)[0].isdigit() else "ul"
            if lists and indent > lists[-1][0]:
                out.append(f"<{tag}><li>")
                lists.append((indent, tag))
            else:
                close_lists(indent)
                if lists and lists[-1][0] == indent:
                    out.append("</li><li>")
                else:
                    out.append(f"<{tag}><li>")
                    lists.append((indent, tag))
            body = item.group(3)
            checkbox = re.match(r"^\[( |x|X)\]\s+(.*)$", body)
            if checkbox:
                done = checkbox.group(1) != " "
                body = checkbox.group(2)
                out.append(f'<span class="cb {"cb-done" if done else ""}">{"✓" if done else ""}</span>')
            out.append(md_inline(body))
            i += 1
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            close_lists()
            out.append(f"<blockquote>{md_inline(stripped.lstrip('> '))}</blockquote>")
            i += 1
            continue

        if lists and line.startswith(" "):
            out.append(" " + md_inline(stripped))
            i += 1
            continue

        close_lists()
        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    close_lists()
    return "\n".join(out)


# --- Specifications -----------------------------------------------------------------

def parse_front_matter(text: str) -> tuple[dict, str]:
    """A minimal subset: `key: value` and `key: [a, b]` lines between `---` fences."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    front_matter: dict = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            front_matter[key] = [part.strip().strip("'\"") for part in value[1:-1].split(",") if part.strip()]
        else:
            front_matter[key] = value.strip("'\"")
    return front_matter, text[end + 4:]


def split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## "):
            current = sections.setdefault(line[3:].strip().lower(), [])
        elif current is not None:
            current.append(line)
    return sections


def task_state(done: bool, note: str) -> str:
    note = note.lower()
    if done:
        return "done"
    if "blocked" in note or "geblokkeerd" in note:
        return "blocked"
    if any(word in note for word in ("dropped", "not needed", "replaced by", "changed task", "geschrapt", "vervallen")):
        return "dropped"
    if any(word in note for word in ("waiting", "manual", "sign-off", "wacht")):
        return "waiting"
    return "pending"


def parse_specification(path: Path) -> dict:
    """A specification's facts. `body` is its markdown without front-matter, for `specification_html`."""
    front_matter, body = parse_front_matter(path.read_text(encoding="utf-8"))
    lines = body.splitlines()
    sections = split_sections(lines)

    heading = next((line[2:].strip() for line in lines if line.startswith("# ")), path.stem)
    execution = front_matter.get("execution", DEFAULT_EXECUTION)

    tasks = []
    for line in sections.get("implementation checklist", []):
        match = TASK_LINE.match(line)
        if not match:
            continue
        task_title, _, note = strip_md(match.group(2)).partition(" - ")
        tasks.append({"title": task_title.strip(), "note": note.strip(), "state": task_state(match.group(1) != " ", note)})

    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", path.name)

    return {
        "file": path.name,
        "path": str(path),
        "title": re.sub(r"\s+Specification$", "", heading),
        "execution": execution if execution in EXECUTION_MODES else DEFAULT_EXECUTION,
        "date": date_match.group(1) if date_match else "",
        "tasks": tasks,
        "counts": {state: sum(1 for task in tasks if task["state"] == state) for state in TASK_STATES},
        "body": body,
    }


def specification_html(specification: dict) -> str:
    return md_to_html(specification["body"])


# --- Personas -----------------------------------------------------------------------
# A persona is `personas/<key>.md` with front-matter `name` and `model`, and the sections
# `## Role` (appended to the system prompt), `## Start` (the first message) and `## Continue`
# (optional, the first message when continuing in the same column). The column personas
# handle the specifications dropped on their column; the Product Owner belongs to no
# column, is started from the header and has no Continue.
PERSONA_COLUMNS = [column["key"] for column in COLUMNS if column["persona"]]
PRODUCT_OWNER = "product-owner"
PERSONAS = [*PERSONA_COLUMNS, PRODUCT_OWNER]
PERSONA_LABELS = {**{key: COLUMN_LABELS[key] for key in PERSONA_COLUMNS}, PRODUCT_OWNER: "Product Owner"}
STORY_VARIABLES = ["specification_path", "specification_title", "story_id", "path", "execution", "from", "config_file", "flow"]
PERSONA_VARIABLES = {**{key: STORY_VARIABLES for key in PERSONA_COLUMNS}, PRODUCT_OWNER: ["path", "config_file", "spaces_file", "flow"]}
PERSONA_SECTIONS = {"role": "role", "start": "start", "continue": "continue"}
SECTION_TITLES = {field: title.capitalize() for title, field in PERSONA_SECTIONS.items()}
PERSONA_KEYS = ("name", "model")
BACKWARD_DROPS = {("in-review", "in-development")}
TODO_COLUMN = "todo"
ANALYSIS_COLUMN = "in-analysis"


class PersonaConflict(Exception):
    """The persona file changed since it was read, or already exists."""


def drop_allowed(source: str, target: str) -> bool:
    """From Todo only onto In analysis; otherwise forward onto a persona column, or back from In review to In development."""
    if source not in COLUMN_KEYS or target not in PERSONA_COLUMNS or source == target:
        return False
    if source == TODO_COLUMN:
        return target == ANALYSIS_COLUMN
    return (source, target) in BACKWARD_DROPS or COLUMN_KEYS.index(source) < COLUMN_KEYS.index(target)


def transitions() -> list[dict]:
    return [{"from": s, "to": t} for s in COLUMN_KEYS for t in PERSONA_COLUMNS if drop_allowed(s, t)]


def persona_path(root: Path, key: str) -> Path:
    if key not in PERSONAS:
        raise PersonaError(f"{key} cannot have a persona")
    return root / "personas" / f"{key}.md"


def file_version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_persona(text: str) -> tuple[dict, str | None]:
    """The form fields in a persona file, and why the form may not overwrite it (or None)."""
    front_matter, body = parse_front_matter(text)
    fields = {key: str(front_matter.get(key, "")).strip() for key in PERSONA_KEYS}
    content = {field: [] for field in PERSONA_SECTIONS.values()}
    problems = [f"unknown field '{key}'" for key in front_matter if key not in PERSONA_KEYS]
    current = None
    seen_heading = False
    for line in body.splitlines():
        if line.startswith("## "):
            seen_heading = True
            title = line[3:].strip()
            current = PERSONA_SECTIONS.get(title.lower())
            if current is None:
                problems.append(f"unknown section '## {title}'")
        elif current is not None:
            content[current].append(line)
        elif line.strip() and not seen_heading:
            problems.append("text outside the sections")
    fields.update({field: "\n".join(lines).strip() for field, lines in content.items()})
    return fields, (", ".join(dict.fromkeys(problems)) or None)


def load_persona(root: Path, key: str) -> dict | None:
    """The persona `key` with its `version`, or None when it has no file or `key` is no persona."""
    if key not in PERSONAS:
        return None
    path = root / "personas" / f"{key}.md"
    if not path.is_file():
        return None
    data = path.read_bytes()
    fields, problem = parse_persona(data.decode("utf-8"))
    return {"key": key, **fields, "version": file_version(data), "editable": problem is None, "problem": problem}


def validate_persona(fields: dict, key: str) -> dict:
    """The fields of persona `key`, stripped, or PersonaError naming what is wrong."""
    clean = {name: str(fields.get(name) or "").strip() for name in (*PERSONA_KEYS, *PERSONA_SECTIONS.values())}
    problems = []
    if not clean["name"]:
        problems.append("Name is empty")
    if "\n" in clean["name"]:
        problems.append("Name must be on one line")
    if re.search(r"\s", clean["model"]):
        problems.append("Model must not contain spaces")
    for field in ("role", "start"):
        if not clean[field]:
            problems.append(f"{SECTION_TITLES[field]} is empty")
    if key == PRODUCT_OWNER and clean["continue"]:
        problems.append(f"{PERSONA_LABELS[key]} has no Continue")
    for field in PERSONA_SECTIONS.values():
        if any(line.startswith("## ") for line in clean[field].splitlines()):
            problems.append(f"{SECTION_TITLES[field]} must not contain a line starting with '## '")
        unknown = sorted({name for name in VARIABLE.findall(clean[field]) if name not in PERSONA_VARIABLES[key]})
        if unknown:
            problems.append(f"{SECTION_TITLES[field]} uses unknown variable(s): " + ", ".join(f"{{{{{n}}}}}" for n in unknown))
    if problems:
        raise PersonaError("; ".join(problems))
    return clean


def persona_markdown(fields: dict) -> str:
    text = f"---\nname: {fields['name']}\nmodel: {fields['model']}\n---\n"
    for field in PERSONA_SECTIONS.values():
        if fields[field]:
            text += f"\n## {SECTION_TITLES[field]}\n{fields[field]}\n"
    return text


def save_persona(root: Path, key: str, fields: dict, version: str | None) -> dict:
    """Write the persona `key`. `version` None creates it; otherwise it must match the file."""
    path = persona_path(root, key)
    clean = validate_persona(fields, key)
    current = path.read_bytes() if path.is_file() else None
    if version is None and current is not None:
        raise PersonaConflict("This persona already exists. Reload the dashboard.")
    if version is not None and (current is None or file_version(current) != version):
        raise PersonaConflict("The persona has changed in the meantime. Reload the dashboard.")
    if current is not None:
        problem = parse_persona(current.decode("utf-8"))[1]
        if problem:
            raise PersonaError(f"{path.name} cannot be edited from the dashboard: {problem}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(persona_markdown(clean), encoding="utf-8")
    os.replace(temporary, path)
    return load_persona(root, key)


def delete_persona(root: Path, key: str, version: str) -> None:
    path = persona_path(root, key)
    if not path.is_file() or file_version(path.read_bytes()) != version:
        raise PersonaConflict("The persona has changed or been deleted in the meantime. Reload the dashboard.")
    path.unlink()


def usable_persona(persona: dict) -> None:
    """PersonaError when the persona file cannot be used as it is."""
    if persona["problem"]:
        raise PersonaError(f"Persona {persona['key']} is invalid: {persona['problem']}")
    validate_persona(persona, persona["key"])


def fill_variables(text: str, values: dict) -> str:
    return VARIABLE.sub(lambda match: values[match.group(1)], text)


def render_persona(persona: dict, specification: dict, space: dict, source: str, mode: str, handover: str | None = None) -> dict:
    """The persona's role and first message for `specification`. `mode` is "start" (a drop) or "continue" (▶).

    `handover`, when given, is a rendered paragraph appended to the role as is.
    """
    usable_persona(persona)
    message = persona["start"] if mode == "start" else persona["continue"]
    if not message:
        raise PersonaError(f"Persona {persona['key']} has no Continue section")
    values = {
        "specification_path": specification["path"],
        "specification_title": specification["title"],
        "story_id": specification["story"],
        "path": space["path"],
        "execution": specification["execution"],
        "from": COLUMN_LABELS[source],
        "config_file": space["config"],
        "flow": FLOW_COMMAND,
    }
    role = fill_variables(persona["role"], values)
    if handover:
        role += f"\n\n{handover}"
    return {"name": persona["name"], "model": persona["model"] or None, "role": role, "task": fill_variables(message, values)}


def render_product_owner(root: Path, persona: dict, space: dict) -> dict:
    """The Product Owner's role and first message for a session in its home `space`."""
    usable_persona(persona)
    values = {"path": space["path"], "config_file": space["config"], "spaces_file": str(root / REGISTRY), "flow": FLOW_COMMAND}
    return {
        "name": persona["name"],
        "model": persona["model"] or None,
        "role": fill_variables(persona["role"], values),
        "task": fill_variables(persona["start"], values),
    }


# --- Spaces and derived state -------------------------------------------------------

def config_file(folder: Path) -> Path:
    return folder / FLOW / "config.json"


def specifications_dir(folder: Path) -> Path:
    return folder / FLOW / "specifications"


def session_dir(folder: Path, story_id: str) -> Path:
    """The `omp` session folder every persona of `story_id` in the space at `folder` resumes."""
    return folder / FLOW / "sessions" / story_id


def read_registry(root: Path) -> list[dict]:
    """The entries of `spaces.json`, each with the `path` as typed; none when the file is missing."""
    path = root / REGISTRY
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def load_spaces(root: Path) -> tuple[list[dict], list[str]]:
    """Each registered space with `version`, the sha256 of its config, which every write must send back.

    `path` is the space's folder, with `~` expanded; `config` its `.flow/config.json`. A path
    without a config, or a second space with the same ID, is skipped with a warning.
    """
    spaces: list[dict] = []
    warnings: list[str] = []
    for entry in read_registry(root):
        typed = entry["path"]
        folder = expand_path(typed)
        config = config_file(folder)
        if not config.is_file():
            warnings.append(f"{typed}: no {FLOW}/config.json, skipped")
            continue
        raw = config.read_bytes()
        data = json.loads(raw)
        space = data["space"]
        if any(s["id"] == space["id"] for s in spaces):
            warnings.append(f"{typed}: a space with ID {space['id']} already exists, skipped")
            continue
        spaces.append({
            "id": space["id"],
            "name": space["name"],
            "title": space.get("title", space["name"]),
            "path": str(folder),
            "config": str(config),
            "version": file_version(raw),
            "epics": data.get("epics", []),
        })
    return spaces, warnings


def load_specifications(folder: Path) -> dict[str, dict]:
    """The specifications in `<folder>/.flow/specifications/`, parsed, by file name."""
    directory = specifications_dir(folder)
    if not directory.is_dir():
        return {}
    return {path.name: parse_specification(path) for path in sorted(directory.glob("*.md"))}


def story_status(story: dict) -> str:
    """The status that places the story. An unknown one counts as waiting-for-analysis;
    a story with a specification on waiting-for-analysis is in Todo."""
    status = story.get("status", NEW_STORY_STATUS)
    if status not in STATUS_ORDER:
        status = NEW_STORY_STATUS
    if story.get("specification") and status == NEW_STORY_STATUS:
        return TODO_COLUMN
    return status


def status_problem(story: dict, status: str) -> str | None:
    """Why `story` may not be on `status`, or None: without a specification it is only on
    waiting-for-analysis or done, with one never on waiting-for-analysis."""
    if status not in STATUS_ORDER:
        return f"{story['id']}: unknown status {status}, choose from {', '.join(STATUS_ORDER)}"
    if story.get("specification") and status == NEW_STORY_STATUS:
        return f"{story['id']} has a specification and cannot be on {NEW_STORY_STATUS}"
    if not story.get("specification") and status not in (NEW_STORY_STATUS, DONE_COLUMN):
        return f"{story['id']} has no specification and can only be on {NEW_STORY_STATUS} or {DONE_COLUMN}"
    return None


def load_state(root: Path = ROOT) -> dict:
    """Spaces with their stories' statuses, the specifications for the Pipeline, and warnings.

    A story links to a specification only through its `specification` field; the story's
    status puts the specification in a column. Each specification carries its `space` (ID),
    `spaceName`, `story` and `status`. Inconsistent data gives a warning: a story with a
    specification on waiting-for-analysis shows in Todo, a story without one gets no card.
    """
    spaces, warnings = load_spaces(root)
    specifications: list[dict] = []
    for space in spaces:
        files = load_specifications(Path(space["path"]))
        linked: set[str] = set()
        for epic in space["epics"]:
            for story in epic["stories"]:
                story["specification"] = story.get("specification") or None
                problem = status_problem(story, story.get("status", NEW_STORY_STATUS))
                if problem:
                    warnings.append(f"{space['name']}: {problem}")
                story["status"] = story_status(story)
                story["ready"] = bool(story.get("ready"))
                story["descriptionHtml"] = md_inline(story.get("description", ""))
                file = story["specification"]
                if file is None:
                    continue
                if file not in files:
                    warnings.append(f"{space['name']}: specification {file} of {story['id']} is not in {FLOW}/specifications/")
                    continue
                linked.add(file)
                specifications.append({
                    **files[file], "space": space["id"], "spaceName": space["name"], "story": story["id"],
                    "status": story["status"], "ready": story["ready"],
                })
            epic["counts"] = {s: sum(1 for story in epic["stories"] if story["status"] == s) for s in STATUS_ORDER}
        for file in sorted(files.keys() - linked):
            warnings.append(f"{space['name']}: specification {file} belongs to no story")
    return {"spaces": spaces, "specifications": specifications, "warnings": warnings}


# --- Closing a specification --------------------------------------------------------

DONE_COLUMN = "done"


class SpecificationConflict(Exception):
    """The story is not on the status the caller saw, or cannot get a specification."""


class NotFound(Exception):
    """The space or story does not exist."""


def json_text(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json_text(data), encoding="utf-8")
    os.replace(temporary, path)


def registered_space(root: Path, space_id: str) -> dict:
    space = next((s for s in load_spaces(root)[0] if s["id"] == space_id), None)
    if space is None:
        raise NotFound(f"Space {space_id} does not exist")
    return space


def state_space(state: dict, space_id: str) -> dict:
    """The space `space_id` in `state` (from `load_state`)."""
    space = next((s for s in state["spaces"] if s["id"] == space_id), None)
    if space is None:
        raise NotFound(f"Space {space_id} does not exist")
    return space


def space_at(state: dict, path: str) -> dict:
    """The space in `state` whose folder is `path` (`~` allowed)."""
    folder = expand_path(path).resolve()
    space = next((s for s in state["spaces"] if Path(s["path"]).resolve() == folder), None)
    if space is None:
        raise NotFound(f"No registered space at {path}")
    return space


def state_specification(state: dict, space_id: str, story_id: str) -> dict:
    """The specification of `story_id` in `space_id`; NotFound when the space or story does not exist or has none."""
    space = state_space(state, space_id)
    if not any(s["id"] == story_id for e in space["epics"] for s in e["stories"]):
        raise NotFound(f"Story {story_id} does not exist in {space['name']}")
    specification = next((s for s in state["specifications"] if s["space"] == space_id and s["story"] == story_id), None)
    if specification is None:
        raise NotFound(f"{story_id} has no specification")
    return specification


def complete_specification(root: Path, space_id: str, story_id: str, source: str,
                           before_done: Callable[[dict], None] | None = None) -> dict:
    """Set the story to done in its space's config; the specification stays where it is.

    `source` is the column the caller saw the story's specification in. `before_done` gets the
    space after every check and before the status is written; when it raises, nothing is written.
    """
    space = registered_space(root, space_id)
    path = Path(space["config"])
    data = json.loads(path.read_text(encoding="utf-8"))
    story = find_story(data, story_id)[1]
    if not story.get("specification"):
        raise SpecificationConflict(f"{story_id} has no specification.")
    status = story_status(story)
    if status == DONE_COLUMN:
        raise SpecificationConflict(f"{story_id} is already Done.")
    if status != source:
        raise SpecificationConflict(f"The specification of {story_id} is now in {COLUMN_LABELS[status]}. Refresh the dashboard.")
    if before_done is not None:
        before_done(space)
    story["status"] = DONE_COLUMN
    story.pop("ready", None)
    write_json(path, data)
    return {"story": story_id, "specification": story["specification"]}


def set_story_status(config: Path, story_id: str, status: str) -> tuple[str, str]:
    """Set the status of `story_id` in the space config at `config`, atomically; the old and new status.

    The status must be one of STATUS_ORDER and keep the specification rule; a transition between
    columns is not checked. Any status change ends a finished step, so it clears `ready`.
    Raises NotFound or SpaceError, and then writes nothing.
    """
    data = json.loads(config.read_text(encoding="utf-8"))
    story = find_story(data, story_id)[1]
    problem = status_problem(story, status)
    if problem:
        raise SpaceError(problem)
    old = story.get("status", NEW_STORY_STATUS)
    story["status"] = status
    story.pop("ready", None)
    write_json(config, data)
    return old, status


def set_story_ready(config: Path, story_id: str) -> None:
    """Mark the step of `story_id` in the space config at `config` as finished: `"ready": true`.

    Only a story with a specification on a persona column can be ready. Raises NotFound or
    SpaceError, and then writes nothing; an already ready story is left as it is.
    """
    data = json.loads(config.read_text(encoding="utf-8"))
    story = find_story(data, story_id)[1]
    if not story.get("specification"):
        raise SpaceError(f"{story_id} has no specification and cannot be ready")
    status = story_status(story)
    if status not in PERSONA_COLUMNS:
        columns = ", ".join(COLUMN_LABELS[column] for column in PERSONA_COLUMNS)
        raise SpaceError(f"{story_id} is in {STATUS_LABELS[status]}; only a story in {columns} can be ready")
    if story.get("ready"):
        return
    story["ready"] = True
    write_json(config, data)


def clear_story_ready(config: Path, story_id: str) -> None:
    """Remove `ready` from `story_id` in the space config at `config`; nothing to write when it is not set."""
    data = json.loads(config.read_text(encoding="utf-8"))
    story = find_story(data, story_id)[1]
    if story.pop("ready", None) is not None:
        write_json(config, data)


# --- A new specification for a story ------------------------------------------------

SLUG_LENGTH = 60


def slug(text: str) -> str:
    """Lowercase kebab-case without accents, only `a-z0-9-`, at most SLUG_LENGTH characters."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:SLUG_LENGTH].rstrip("-")


def create_specification(root: Path, space_id: str, story_id: str, today: date) -> dict:
    """Create an empty specification for a story without one, link it through the story's
    `specification` field and put the story on todo.

    The file is created exclusively in `.flow/specifications/` first; when the config cannot
    be written, it is removed again.
    """
    space = registered_space(root, space_id)
    path = Path(space["config"])
    data = json.loads(path.read_text(encoding="utf-8"))
    story = find_story(data, story_id)[1]
    if story.get("specification"):
        raise SpecificationConflict(f"{story_id} already has a specification. Refresh the dashboard.")
    if story_status(story) == DONE_COLUMN:
        raise SpecificationConflict(f"{story_id} is Done.")

    title = story.get("title", "")
    file = "-".join(part for part in (today.isoformat(), slug(story_id), slug(title), "specification") if part) + ".md"
    target = specifications_dir(Path(space["path"])) / file
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(f"---\nexecution: {DEFAULT_EXECUTION}\n---\n\n# {title} ({story_id}) Specification\n")
    except FileExistsError as error:
        raise SpecificationConflict(f"A specification {file} already exists.") from error

    story["specification"] = file
    story["status"] = TODO_COLUMN
    try:
        write_json(path, data)
    except OSError:
        target.unlink()
        raise
    return {"specification": file, "story": story_id}


# --- Managing epics and stories -----------------------------------------------------
# A new epic gets `E<n>`, a new story `E<n>S<m>`; existing IDs stay as they are. A number
# is never reused: the space keeps `nextEpic`, each epic `nextStory`, and the next number
# is always past the highest in use. Every change reads the raw file, checks `version`,
# touches only the fields it is about, and writes atomically.

EPIC_ID = re.compile(r"E(\d+)")
LABEL = re.compile(r"[a-z0-9-]+")
STORY_FIELDS = ("title", "description", "labels")
NEW_STORY_STATUS = "waiting-for-analysis"


class SpaceConflict(Exception):
    """The space file changed since the caller read it."""


class SpaceError(Exception):
    """Fields that cannot be stored."""


def space_version(path: Path) -> str:
    return file_version(path.read_bytes())


def read_space(root: Path, space_id: str, version: str | None) -> tuple[Path, dict]:
    """The config file and raw data of `space_id`, when it is still at `version`."""
    path = Path(registered_space(root, space_id)["config"])
    raw = path.read_bytes()
    if file_version(raw) != version:
        raise SpaceConflict("The space has changed in the meantime. Reload the dashboard.")
    return path, json.loads(raw)


def write_space(path: Path, data: dict) -> dict:
    write_json(path, data)
    return {"version": space_version(path)}


def find_epic(data: dict, epic_id: str) -> dict:
    epic = next((e for e in data.get("epics", []) if e["id"] == epic_id), None)
    if epic is None:
        raise NotFound(f"Epic {epic_id} does not exist in {data['space']['name']}")
    return epic


def find_story(data: dict, story_id: str) -> tuple[dict, dict]:
    """The epic holding `story_id`, and the story."""
    for epic in data.get("epics", []):
        for story in epic.get("stories", []):
            if story["id"] == story_id:
                return epic, story
    raise NotFound(f"Story {story_id} does not exist in {data['space']['name']}")


def next_number(counter: object, ids: list[str], pattern: re.Pattern) -> int:
    """The stored counter, but past every number `pattern` finds in `ids`; 1 without either."""
    used = [int(match.group(1)) for match in map(pattern.fullmatch, ids) if match]
    return max([counter if isinstance(counter, int) else 1, *(number + 1 for number in used)])


def clean_title(value: object) -> str:
    title = value.strip() if isinstance(value, str) else ""
    if not title:
        raise SpaceError("Title is empty")
    if "\n" in title or "\r" in title:
        raise SpaceError("Title must be on one line")
    return title


def clean_labels(value: object) -> list[str]:
    """Labels as a list or comma-separated text: lowercase letters, digits and dashes."""
    parts = value.split(",") if isinstance(value, str) else value
    if not isinstance(parts, list) or not all(isinstance(part, str) for part in parts):
        raise SpaceError("Labels must be text")
    labels = list(dict.fromkeys(part.strip() for part in parts if part.strip()))
    wrong = [label for label in labels if not LABEL.fullmatch(label)]
    if wrong:
        raise SpaceError(f"Invalid label: {', '.join(wrong)} (only lowercase letters, digits and dashes)")
    return labels


def clean_story(fields: dict, new: bool) -> dict:
    """The story fields present in `fields`, cleaned. A new story needs a title."""
    unknown = sorted(set(fields) - set(STORY_FIELDS))
    if unknown:
        raise SpaceError(f"Not editable: {', '.join(unknown)}")
    clean = {}
    if new or "title" in fields:
        clean["title"] = clean_title(fields.get("title"))
    if "description" in fields:
        if not isinstance(fields["description"], str):
            raise SpaceError("Description must be text")
        clean["description"] = fields["description"].strip()
    if "labels" in fields:
        clean["labels"] = clean_labels(fields["labels"])
    return clean


def add_epic(data: dict, title: object) -> str:
    """Append a new epic `E<n>` titled `title` to the loaded space `data`; its ID."""
    title = clean_title(title)
    epics = data.setdefault("epics", [])
    number = next_number(data["space"].get("nextEpic"), [e["id"] for e in epics], EPIC_ID)
    epics.append({"id": f"E{number}", "title": title, "stories": []})
    data["space"]["nextEpic"] = number + 1
    return f"E{number}"


def add_story(data: dict, epic_id: str, fields: dict) -> str:
    """Append a story `E<n>S<m>` on waiting-for-analysis to epic `epic_id` of the loaded space `data`; its ID."""
    clean = clean_story(fields, new=True)
    epic = find_epic(data, epic_id)
    if not EPIC_ID.fullmatch(epic_id):
        raise SpaceError(f"Epic {epic_id} has no ID like E1, so no new story IDs")
    number = next_story_number(data, epic)
    story_id = f"{epic_id}S{number}"
    epic.setdefault("stories", []).append({
        "id": story_id,
        "title": clean["title"],
        "description": clean.get("description", ""),
        "status": NEW_STORY_STATUS,
        "labels": clean.get("labels", []),
    })
    epic["nextStory"] = number + 1
    return story_id


def create_epic(root: Path, space_id: str, title: object, version: str | None) -> dict:
    title = clean_title(title)
    path, data = read_space(root, space_id, version)
    return {"epic": add_epic(data, title), **write_space(path, data)}


def update_epic(root: Path, space_id: str, epic_id: str, title: object, version: str | None) -> dict:
    title = clean_title(title)
    path, data = read_space(root, space_id, version)
    find_epic(data, epic_id)["title"] = title
    return {"epic": epic_id, **write_space(path, data)}


def move_epic(root: Path, space_id: str, epic_id: str, position: object, version: str | None) -> dict:
    """Put the epic at index `position` of `epics`; that order is the priority, first on top."""
    path, data = read_space(root, space_id, version)
    epics = data.get("epics", [])
    epic = find_epic(data, epic_id)
    if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position < len(epics):
        raise SpaceError(f"Position must be a number from 0 to {len(epics) - 1}")
    epics.remove(epic)
    epics.insert(position, epic)
    return {"epic": epic_id, **write_space(path, data)}


def create_story(root: Path, space_id: str, epic_id: str, fields: dict, version: str | None) -> dict:
    """A story `E<n>S<m>` in epic `E<n>`, on waiting-for-analysis. It writes no specification."""
    clean_story(fields, new=True)
    path, data = read_space(root, space_id, version)
    return {"story": add_story(data, epic_id, fields), **write_space(path, data)}


def update_story(root: Path, space_id: str, story_id: str, fields: dict, version: str | None) -> dict:
    """Set the title, description and labels present in `fields`; every other field stays."""
    clean = clean_story(fields, new=False)
    path, data = read_space(root, space_id, version)
    find_story(data, story_id)[1].update(clean)
    return {"story": story_id, **write_space(path, data)}


def next_story_number(data: dict, epic: dict) -> int:
    used = [s["id"] for e in data["epics"] for s in e.get("stories", [])]
    return next_number(epic.get("nextStory"), used, re.compile(rf"{re.escape(epic['id'])}S(\d+)"))


# --- A breakdown: epics and stories for several spaces in one go --------------------
# The Product Owner's approved breakdown, `{"epics": [{"space", "epic" | "title", "stories"}]}`.
# Every entry is applied to each space's config in memory first; only when all of them
# are valid is each touched config written, once. Like `flow.py status`, it does not
# check a `version`: an open dashboard gets a conflict on its next write and reloads.

BREAKDOWN_ENTRY = ("space", "epic", "title", "stories")


def breakdown_entry(entry: object) -> tuple[str, str | None, object, list]:
    """The space path, existing epic ID or None, new title and stories of one entry."""
    if not isinstance(entry, dict):
        raise SpaceError("must be an object")
    unknown = sorted(set(entry) - set(BREAKDOWN_ENTRY))
    if unknown:
        raise SpaceError(f"unknown field(s): {', '.join(unknown)}")
    space, epic, title, stories = (entry.get(key) for key in BREAKDOWN_ENTRY)
    if not isinstance(space, str) or not space.strip():
        raise SpaceError("space must be the path of a registered space")
    if (epic is None) == (title is None):
        raise SpaceError("give exactly one of epic (an existing epic) or title (a new epic)")
    if epic is not None and not isinstance(epic, str):
        raise SpaceError("epic must be an epic ID like E1")
    if not isinstance(stories, list) or not stories:
        raise SpaceError("stories must be a list with at least one story")
    return space, epic, title, stories


def apply_breakdown(root: Path, breakdown: object) -> list[dict]:
    """Add the epics and stories of `breakdown` to their spaces, all or nothing.

    Per space, in order of first mention: `{"space": name, "epics": [{"epic", "title", "stories"}]}`,
    where `title` is None for an existing epic. Raises SpaceError or NotFound naming the entry
    before anything is written.
    """
    if not isinstance(breakdown, dict) or not isinstance(breakdown.get("epics"), list) or not breakdown["epics"]:
        raise SpaceError('The breakdown must be {"epics": [...]} with at least one epic')
    state = {"spaces": load_spaces(root)[0]}
    loaded: dict[str, tuple[Path, dict, list[dict]]] = {}
    for number, entry in enumerate(breakdown["epics"], start=1):
        where = f"Epic {number}"
        try:
            path, epic_id, title, stories = breakdown_entry(entry)
            space = space_at(state, path)
            if space["id"] not in loaded:
                config = Path(space["config"])
                loaded[space["id"]] = (config, json.loads(config.read_text(encoding="utf-8")), [])
            _, data, created = loaded[space["id"]]
            if epic_id is None:
                epic_id = add_epic(data, title)
                title = data["epics"][-1]["title"]
            else:
                find_epic(data, epic_id)
            story_ids = []
            for index, story in enumerate(stories, start=1):
                where = f"Epic {number}, story {index}"
                if not isinstance(story, dict):
                    raise SpaceError("must be an object")
                story_ids.append(add_story(data, epic_id, story))
        except (SpaceError, NotFound) as error:
            raise type(error)(f"{where}: {error}") from error
        created.append({"epic": epic_id, "title": title, "stories": story_ids})
    for config, data, _ in loaded.values():
        write_json(config, data)
    return [{"space": data["space"]["name"], "epics": created} for _, data, created in loaded.values()]


# --- Deleting epics and stories with their specifications --------------------------

def story_specifications_to_delete(state: dict, space_id: str, story_ids: list[str]) -> list[dict]:
    """The specifications of `story_ids` in `space_id`, with their status."""
    removed = set(story_ids)
    return [
        {"file": s["file"], "title": s["title"], "status": s["status"], "path": s["path"]}
        for s in state["specifications"]
        if s["space"] == space_id and s["story"] in removed
    ]


def deletion_preview(root: Path, space_id: str, epic_id: str | None = None, story_id: str | None = None) -> dict:
    """What deleting the epic or the story would remove: its stories and their specifications."""
    state = load_state(root)
    space = next((s for s in state["spaces"] if s["id"] == space_id), None)
    if space is None:
        raise NotFound(f"Space {space_id} does not exist")
    if epic_id is not None:
        epic = next((e for e in space["epics"] if e["id"] == epic_id), None)
        if epic is None:
            raise NotFound(f"Epic {epic_id} does not exist in {space['name']}")
        stories = epic["stories"]
    else:
        stories = [s for e in space["epics"] for s in e["stories"] if s["id"] == story_id]
        if not stories:
            raise NotFound(f"Story {story_id} does not exist in {space['name']}")
    specifications = story_specifications_to_delete(state, space_id, [s["id"] for s in stories])
    return {"stories": [{"id": s["id"], "title": s.get("title", "")} for s in stories], "specifications": specifications}


def delete_story(root: Path, space_id: str, story_id: str, version: str | None) -> dict:
    path, data = read_space(root, space_id, version)
    epic, story = find_story(data, story_id)
    if EPIC_ID.fullmatch(epic["id"]):
        epic["nextStory"] = next_story_number(data, epic)
    epic["stories"].remove(story)
    return write_without_stories(root, path, data, space_id, version, [story_id])


def delete_epic(root: Path, space_id: str, epic_id: str, version: str | None) -> dict:
    path, data = read_space(root, space_id, version)
    epic = find_epic(data, epic_id)
    data["space"]["nextEpic"] = next_number(data["space"].get("nextEpic"), [e["id"] for e in data["epics"]], EPIC_ID)
    data["epics"].remove(epic)
    return write_without_stories(root, path, data, space_id, version, [s["id"] for s in epic.get("stories", [])])


def write_without_stories(root: Path, path: Path, data: dict, space_id: str, version: str | None, story_ids: list[str]) -> dict:
    """Write `data`, which no longer holds `story_ids`, and remove those stories' specifications.

    The specifications move to a temporary folder `.flow/.deleting-*` first. The folder goes
    once the config is written; when writing fails, the specifications go back where they were.
    """
    state = load_state(root)
    space = next((s for s in state["spaces"] if s["id"] == space_id), None)
    if space is None or space["version"] != version:
        raise SpaceConflict("The space has changed in the meantime. Reload the dashboard.")
    specifications = story_specifications_to_delete(state, space_id, story_ids)
    parking = Path(tempfile.mkdtemp(prefix=".deleting-", dir=Path(space["path"]) / FLOW)) if specifications else None
    parked: list[tuple[Path, Path]] = []
    try:
        for specification in specifications:
            origin = Path(specification["path"])
            target = parking / specification["file"]
            os.replace(origin, target)
            parked.append((origin, target))
        write_json(path, data)
    except OSError:
        for origin, target in reversed(parked):
            os.replace(target, origin)
        if parking:
            shutil.rmtree(parking)
        raise
    if parking:
        shutil.rmtree(parking)
    return {"stories": story_ids, "specifications": [s["file"] for s in specifications], "version": space_version(path)}


# --- Creating a space ---------------------------------------------------------------
# A new space has only a name and a path. Its ID is `slug(name)`. Every check runs before
# anything is written; then the missing folders up to `<path>/.flow/` are made, then
# `config.json`, exclusively, then `spaces.json` is rewritten with the path as typed. When a
# step fails, the config and only the folders made here are removed again.

RESERVED_NAMES = {"all"}


def clean_space_name(value: object) -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not name:
        raise SpaceError("Name is empty")
    if "\n" in name or "\r" in name:
        raise SpaceError("Name must be on one line")
    if name.casefold() in RESERVED_NAMES:
        raise SpaceError(f"{name} is reserved: choose another name")
    if not slug(name):
        raise SpaceError(f"{name} gives no ID: use letters or digits")
    return name


def clean_space_path(value: object) -> str:
    """The path as typed, absolute or starting with `~`, that is not a file."""
    path = value.strip() if isinstance(value, str) else ""
    if not path:
        raise SpaceError("Path is empty")
    try:
        folder = expand_path(path)
    except RuntimeError as error:
        raise SpaceError(f"Path {path}: unknown user after ~") from error
    if not folder.is_absolute():
        raise SpaceError(f"Path {path} must be absolute or start with ~")
    if folder.exists() and not folder.is_dir():
        raise SpaceError(f"Path {path} is a file, not a folder")
    return path


def missing_folders(folder: Path) -> list[Path]:
    """`folder` and its parents that do not exist yet, deepest first."""
    missing = []
    while not folder.exists():
        missing.append(folder)
        folder = folder.parent
    return missing


def remove_empty_folders(folders: list[Path]) -> None:
    """Remove `folders`, deepest first, up to the first one that is not empty."""
    for folder in folders:
        try:
            folder.rmdir()
        except OSError:
            return


def create_json(path: Path, data: dict) -> None:
    """Write `data` to a new file, never over an existing one. A half-written file is removed."""
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise SpaceConflict(f"{path} already exists") from error
    try:
        with handle:
            handle.write(json_text(data))
    except OSError:
        path.unlink(missing_ok=True)
        raise


def create_space(root: Path, name: object, path: object) -> dict:
    """A space `slug(name)` with its `.flow/config.json` in `path`, added to `spaces.json`."""
    name, path = clean_space_name(name), clean_space_path(path)
    space_id = slug(name)
    folder = expand_path(path).resolve()
    registry = read_registry(root)
    spaces = load_spaces(root)[0]
    for space in spaces:
        if space["name"].casefold() == name.casefold():
            raise SpaceConflict(f"A space {space['name']} already exists")
        if space["id"] == space_id:
            raise SpaceConflict(f"A space with ID {space_id} already exists")
        if Path(space["path"]).resolve() == folder:
            raise SpaceConflict(f"Space {space['name']} already uses this path")
    if any(expand_path(entry["path"]).resolve() == folder for entry in registry):
        raise SpaceConflict(f"{path} is already in {REGISTRY}")
    config = config_file(expand_path(path))
    if config.exists():
        raise SpaceConflict(f"{path}/{FLOW}/config.json already exists")

    missing = missing_folders(config.parent)
    data = {"schemaVersion": 2, "space": {"id": space_id, "name": name, "nextEpic": 1}, "epics": []}
    created = False
    try:
        config.parent.mkdir(parents=True, exist_ok=True)
        create_json(config, data)
        created = True
        write_json(root / REGISTRY, [*registry, {"path": path}])
    except (OSError, SpaceConflict):
        if created:
            config.unlink()
        remove_empty_folders(missing)
        raise
    return {"space": space_id, "version": space_version(config)}
