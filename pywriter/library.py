"""Question packs (YAML) and the safe condition language used to branch interviews.

A pack looks like::

    pack: character
    kind: character            # entity kind it fills (or "project" for project-level packs)
    project_types: [Fiction]
    title: Character Interview
    another: "Is there another character you'd like to add?"
    sections:
      - id: basics
        title: The Basics
        when: "..."            # optional condition for the whole section
        tiers: [primary]       # optional shorthand for tier in [...]
        questions:
          - key: name
            label: Name
            ask: "What is this character's full name?"
            type: text         # text | long | choice | yesno | number | entity | entities
            options: [...]     # for choice: strings or {value, label}
            kind: character    # for entity/entities
            relation: sibling  # link created for entity/entities answers
            reverse: false     # store link as target -> this entity
            when: "tier != 'tertiary'"
            spawn: location    # for yesno: answering yes queues another interview

Conditions are tiny Python-like expressions, evaluated safely (no eval):
names refer to answers in the current interview, ``project.x`` to project-level
answers, and helpers ``rank(level)``, ``answered(key)``, ``has(key, 'word')`` exist.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import packs_dir

# Ordered scale of setting levels used by location interviews and world scale.
LEVELS: list[tuple[str, str]] = [
    ("room", "Room or small space"),
    ("building", "Building, vehicle or vessel"),
    ("site", "Outdoor site or landmark"),
    ("district", "Neighborhood or district"),
    ("settlement", "Village, town or city"),
    ("region", "Region, province or wilderness"),
    ("country", "Country, nation or kingdom"),
    ("continent", "Continent"),
    ("planet", "Planet or world"),
    ("star_system", "Star system"),
    ("galaxy", "Galaxy"),
    ("universe", "Universe or reality"),
    ("dimension", "Dimension or plane of existence"),
    ("timeline", "Timeline"),
    ("multiverse", "Multiverse"),
]
LEVEL_RANK = {k: i for i, (k, _) in enumerate(LEVELS)}
LEVEL_LABELS = dict(LEVELS)

QUESTION_TYPES = {"text", "long", "choice", "yesno", "number", "entity", "entities"}


@dataclass
class Option:
    value: str
    label: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class Question:
    key: str
    ask: str
    label: str = ""
    type: str = "long"
    options: list[Option] = field(default_factory=list)
    allow_other: bool = True
    kind: str = ""
    relation: str = "related to"
    reverse: bool = False
    when: str = ""
    help: str = ""
    required: bool = False
    spawn: str = ""
    section: "Section | None" = None

    @property
    def display_label(self) -> str:
        return self.label or self.key.replace("_", " ").capitalize()

    def option_label(self, value: str) -> str:
        for o in self.options:
            if o.value == value:
                return o.label
        return value

    def match_option(self, text: str) -> str | None:
        """Map free text (typed or spoken) onto an option value."""
        t = text.strip().lower()
        if not t:
            return None
        if self.type == "yesno":
            if re.search(r"\b(yes|yeah|yep|yup|sure|correct|affirmative|it does|they do|i do|true)\b", t):
                return "yes"
            if re.search(r"\b(no|nope|nah|not|negative|false|never)\b", t):
                return "no"
            return None
        for o in self.options:
            if t == o.value.lower() or t == o.label.lower():
                return o.value
        best = None
        for o in self.options:
            words = [o.value.lower().replace("_", " "), o.label.lower(), *[a.lower() for a in o.aliases]]
            for w in words:
                if re.search(rf"\b{re.escape(w)}\b", t):
                    if best is None or len(w) > best[1]:
                        best = (o.value, len(w))
        return best[0] if best else None


@dataclass
class Section:
    id: str
    title: str
    when: str = ""
    intro: str = ""
    questions: list[Question] = field(default_factory=list)


@dataclass
class Pack:
    id: str
    kind: str
    title: str
    project_types: list[str]
    intro: str = ""
    outro: str = ""
    another: str = ""
    sections: list[Section] = field(default_factory=list)
    source_file: str = ""

    @property
    def questions(self) -> list[Question]:
        return [q for s in self.sections for q in s.questions]

    def question(self, key: str) -> Question | None:
        for q in self.questions:
            if q.key == key:
                return q
        return None


# ---------------------------------------------------------------- condition language

class ConditionError(ValueError):
    pass


_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.Compare,
    ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Name, ast.Load, ast.Attribute, ast.Constant, ast.List, ast.Tuple, ast.Call,
)
_compiled: dict[str, ast.Expression] = {}


def _parse(expr: str) -> ast.Expression:
    tree = _compiled.get(expr)
    if tree is None:
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            raise ConditionError(f"Bad condition {expr!r}: {e}") from e
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                raise ConditionError(f"Not allowed in condition {expr!r}: {type(node).__name__}")
        _compiled[expr] = tree
    return tree


def evaluate(expr: str, answers: dict[str, str], project: dict[str, str]) -> bool:
    if not expr or not expr.strip():
        return True
    tree = _parse(expr)

    def rank(v: Any) -> int:
        return LEVEL_RANK.get(str(v), -1)

    funcs = {
        "rank": rank,
        "answered": lambda k: bool(str(answers.get(k, "")).strip()),
        "has": lambda k, word: str(word).lower() in str(answers.get(k, "")).lower(),
        "project_has": lambda k, word: str(word).lower() in str(project.get(k, "")).lower(),
    }

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BoolOp):
            vals = (ev(v) for v in node.values)
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp):
            return not ev(node.operand)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = ev(comp)
                ok = {
                    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
                    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
                    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
                    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
                }[type(op)](left, right)
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Name):
            if node.id in ("True", "False"):
                return node.id == "True"
            return answers.get(node.id, "")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "project":
                return project.get(node.attr, "")
            raise ConditionError("Only project.<key> attributes are allowed")
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(e) for e in node.elts]
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in funcs:
                raise ConditionError("Unknown function in condition")
            return funcs[node.func.id](*[ev(a) for a in node.args])
        raise ConditionError(f"Unsupported: {type(node).__name__}")

    try:
        return bool(ev(tree))
    except ConditionError:
        raise
    except Exception:
        return False


# ---------------------------------------------------------------- templating

PRONOUNS = {
    "she/her": ("she", "her", "her", "herself"),
    "he/him": ("he", "him", "his", "himself"),
    "they/them": ("they", "them", "their", "themselves"),
    "it/its": ("it", "it", "its", "itself"),
}


class _Fmt(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, answers: dict[str, str], project: dict[str, str], default_name: str,
           short_repeats: bool = False) -> str:
    name = (answers.get("name") or "").strip() or default_name
    pro = PRONOUNS.get(answers.get("pronouns", ""), PRONOUNS["they/them"])
    values = _Fmt({k: v for k, v in answers.items() if isinstance(v, str)})
    values.update({
        "name": name,
        "Name": name[:1].upper() + name[1:],
        "them": pro[1], "their": pro[2], "themself": pro[3],
        "title": project.get("name", "your story") or "your story",
        "subject": project.get("subject", "") or "the subject",
        "level": LEVEL_LABELS.get(answers.get("level", ""), "place").split(",")[0].split(" or ")[0].lower(),
    })
    try:
        out = template.format_map(values)
    except (ValueError, IndexError):
        return template
    # "How does Mara Venn ... the way Mara Venn moves" -> second mention uses "Mara"
    if short_repeats and " " in name and out.count(name) > 1:
        first = out.index(name) + len(name)
        out = out[:first] + out[first:].replace(name, name.split()[0])
    return out


# ---------------------------------------------------------------- loading

def _build_question(raw: dict, section: Section, pack_id: str) -> Question:
    if "key" not in raw or "ask" not in raw:
        raise ValueError(f"[{pack_id}] question missing key/ask: {raw}")
    qtype = raw.get("type", "long")
    if qtype not in QUESTION_TYPES:
        raise ValueError(f"[{pack_id}] {raw['key']}: unknown type {qtype}")
    opts: list[Option] = []
    for o in raw.get("options") or []:
        if isinstance(o, dict):
            opts.append(Option(str(o["value"]), str(o.get("label", o["value"])), list(o.get("aliases", []))))
        else:
            opts.append(Option(str(o), str(o)))
    if raw.get("options") == "levels":
        opts = [Option(k, v) for k, v in LEVELS]
    if qtype == "yesno":
        opts = [Option("yes", "Yes"), Option("no", "No")]
    conds = []
    if raw.get("when"):
        conds.append(f"({raw['when']})")
    if raw.get("tiers"):
        conds.append(f"(tier in {list(raw['tiers'])!r} or tier == '')")
    return Question(
        key=raw["key"], ask=" ".join(str(raw["ask"]).split()), label=raw.get("label", ""), type=qtype,
        options=opts, allow_other=raw.get("allow_other", True), kind=raw.get("kind", ""),
        relation=raw.get("relation", "related to"), reverse=bool(raw.get("reverse", False)),
        when=" and ".join(conds), help=raw.get("help", ""), required=bool(raw.get("required", False)),
        spawn=raw.get("spawn", ""), section=section,
    )


def load_pack(path: Path) -> Pack:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    pid = data["pack"]
    pack = Pack(id=pid, kind=data["kind"], title=data.get("title", pid),
                project_types=list(data.get("project_types") or ["Fiction", "Non-Fiction", "Biography"]),
                intro=data.get("intro", ""), outro=data.get("outro", ""), another=data.get("another", ""),
                source_file=str(path))
    for s in data.get("sections", []):
        conds = []
        if s.get("when"):
            conds.append(f"({s['when']})")
        if s.get("tiers"):
            conds.append(f"(tier in {list(s['tiers'])!r} or tier == '')")
        sec = Section(id=s["id"], title=s.get("title", s["id"]), when=" and ".join(conds),
                      intro=s.get("intro", ""))
        for q in s.get("questions", []):
            sec.questions.append(_build_question(q, sec, pid))
        pack.sections.append(sec)
    # validate conditions eagerly so typos surface at start-up
    for q in pack.questions:
        for expr in (q.when, q.section.when if q.section else ""):
            if expr:
                _parse(expr)
    keys = [q.key for q in pack.questions]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise ValueError(f"[{pid}] duplicate question keys: {sorted(dupes)}")
    return pack


class Library:
    """All packs, plus helpers to pick the right one for a project type and kind."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder or packs_dir()
        self.packs: dict[str, Pack] = {}
        self.errors: list[str] = []
        self.flows: dict[str, list[dict]] = {}
        self.reload()

    def reload(self) -> None:
        self.packs.clear()
        self.errors.clear()
        for p in sorted(self.folder.glob("*.yaml")):
            if p.name == "flows.yaml":
                self.flows = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                continue
            try:
                pack = load_pack(p)
                self.packs[pack.id] = pack
            except Exception as e:  # keep going; report in the UI
                self.errors.append(f"{p.name}: {e}")

    def pack(self, pack_id: str) -> Pack | None:
        return self.packs.get(pack_id)

    def packs_for(self, project_type: str) -> list[Pack]:
        return [p for p in self.packs.values() if project_type in p.project_types]

    def pack_for_kind(self, kind: str, project_type: str) -> Pack | None:
        for p in self.packs_for(project_type):
            if p.kind == kind:
                return p
        return None

    def project_packs(self, project_type: str) -> list[Pack]:
        return [p for p in self.packs_for(project_type) if p.kind == "project"]

    def labels_for(self, kind: str, project_type: str) -> list[tuple[str, list[tuple[str, str]]]]:
        """[(section title, [(key, label), ...]), ...] for display/export ordering."""
        out = []
        packs = self.project_packs(project_type) if kind == "project" else \
            [p for p in [self.pack_for_kind(kind, project_type)] if p]
        for pack in packs:
            for s in pack.sections:
                out.append((s.title, [(q.key, q.display_label) for q in s.questions]))
        return out

    def flow(self, project_type: str) -> list[dict]:
        return list(self.flows.get(project_type, []))
