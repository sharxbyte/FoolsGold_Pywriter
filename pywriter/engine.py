"""Interview session: walks a pack's questions, branching on answers, and commits
answers to the project store (creating linked entities as needed)."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches

from .library import Pack, Question, evaluate, render
from .store import KINDS, ProjectStore, split_list


@dataclass
class CommitResult:
    entity_id: str
    created: list[str] = field(default_factory=list)   # stub entities created from answers
    spawns: list[tuple[str, dict]] = field(default_factory=list)  # (pack kind, preset answers)


def resolve_name(store: ProjectStore, name: str, kind: str | None) -> str | None:
    """Find an existing entity by exact name/alias, or a very close fuzzy match."""
    name = name.strip()
    if not name:
        return None
    rows = [r for r in store.all_names() if not kind or r[1] == kind]
    for eid, _, n in rows:
        if n.lower() == name.lower():
            return eid
    names = [n for _, _, n in rows]
    close = get_close_matches(name, names, n=1, cutoff=0.88)
    if close:
        for eid, _, n in rows:
            if n == close[0]:
                return eid
    # a lone first name matching the start of a full name ("Mara" -> "Mara Venn")
    first = [eid for eid, _, n in rows if n.lower().split()[0] == name.lower()]
    if len(first) == 1 and " " not in name:
        return first[0]
    return None


class Interview:
    def __init__(self, pack: Pack, store: ProjectStore, entity_id: str | None = None,
                 preset: dict[str, str] | None = None):
        self.pack = pack
        self.store = store
        self.entity_id = entity_id
        self.answers: dict[str, str] = {}
        self.spawned: set[str] = set()
        self.adopted: str | None = None
        if pack.kind == "project":
            self.entity_id = store.project_entity().id
        if self.entity_id:
            e = store.get(self.entity_id)
            if e:
                self.answers.update(e.fields)
                self.answers["name"] = e.name
                self.answers["tier"] = e.tier
                if e.parent_id:
                    parent = store.get(e.parent_id, with_fields=False)
                    self.answers["parent"] = parent.name if parent else ""
        if preset:
            self.answers.update({k: v for k, v in preset.items() if v and not self.answers.get(k)})
        self.current: Question | None = None
        visible = self.visible()
        self.current = visible[0] if visible else None

    # ------------------------------------------------------------ context
    @property
    def project(self) -> dict[str, str]:
        p = self.store.project_entity()
        d = dict(p.fields)
        d["name"] = p.name
        d["type"] = self.store.project_type
        if self.pack.kind == "project":  # answers in progress count for project.x too
            d.update(self.answers)
        return d

    @property
    def default_name(self) -> str:
        if self.pack.kind == "project":
            return "your story"
        return f"this {KINDS.get(self.pack.kind, ('', 'entry'))[1].lower()}"

    def is_visible(self, q: Question) -> bool:
        proj = self.project
        if q.section and q.section.when and not evaluate(q.section.when, self.answers, proj):
            return False
        return evaluate(q.when, self.answers, proj)

    def visible(self) -> list[Question]:
        return [q for q in self.pack.questions if self.is_visible(q)]

    def text(self, q: Question | None = None) -> str:
        q = q or self.current
        return render(q.ask, self.answers, self.project, self.default_name,
                      short_repeats=self.pack.kind == "character") if q else ""

    def section_title(self, q: Question | None = None) -> str:
        q = q or self.current
        return render(q.section.title, self.answers, self.project, self.default_name) if q and q.section else ""

    def progress(self) -> tuple[int, int]:
        vis = self.visible()
        if self.current in vis:
            return vis.index(self.current) + 1, len(vis)
        return 0, len(vis)

    # ------------------------------------------------------------ navigation
    def answer(self, value: str) -> None:
        if not self.current:
            return
        q = self.current
        value = value.strip()
        if q.type in ("choice", "yesno") and value:
            matched = q.match_option(value)
            if matched:
                value = matched
            elif q.type == "yesno":
                pass  # keep free text; conditions simply won't match
        self.answers[q.key] = value
        if q.key == "name" and value and not self.entity_id and self.pack.kind != "project":
            self.adopt_existing(value)

    def adopt_existing(self, name: str) -> str | None:
        """If an entry with this name already exists (often a stub created from another
        interview), continue filling in that entry instead of making a duplicate."""
        e = self.store.find_by_name(name, self.pack.kind)
        if not e:
            return None
        self.entity_id = e.id
        for k, v in e.fields.items():
            if v and not self.answers.get(k):
                self.answers[k] = v
        if e.tier and not self.answers.get("tier"):
            self.answers["tier"] = e.tier
        if e.parent_id and not self.answers.get("parent"):
            parent = self.store.get(e.parent_id, with_fields=False)
            self.answers["parent"] = parent.name if parent else ""
        self.adopted = e.id
        return e.id

    def next(self) -> Question | None:
        all_q = self.pack.questions
        start = all_q.index(self.current) + 1 if self.current in all_q else 0
        for q in all_q[start:]:
            if self.is_visible(q):
                self.current = q
                return q
        self.current = None
        return None

    def back(self) -> Question | None:
        all_q = self.pack.questions
        if self.current is None:
            vis = self.visible()
            self.current = vis[-1] if vis else None
            return self.current
        idx = all_q.index(self.current)
        for q in reversed(all_q[:idx]):
            if self.is_visible(q):
                self.current = q
                return q
        return self.current

    def jump(self, key: str) -> None:
        q = self.pack.question(key)
        if q:
            self.current = q

    @property
    def finished(self) -> bool:
        return self.current is None

    # ------------------------------------------------------------ persistence
    def commit(self, source: str = "interview", final: bool = False) -> CommitResult | None:
        """Write answers to the store. Safe to call repeatedly (incremental autosave)."""
        store = self.store
        res = None
        with store.batch():
            if not self.entity_id:
                name = self.answers.get("name", "").strip()
                if not name and not any(v.strip() for v in self.answers.values()):
                    return None
                self.entity_id = store.create_entity(
                    self.pack.kind, name or f"New {KINDS[self.pack.kind][1].lower()}",
                    tier=self.answers.get("tier", ""), source=source)
            res = CommitResult(self.entity_id)
            plain: dict[str, str] = {}
            for q in self.pack.questions:
                if q.key not in self.answers:
                    continue
                val = self.answers[q.key]
                if q.type in ("entity", "entities"):
                    self._commit_refs(q, val, res, source)
                    if q.key == "parent":
                        continue
                if q.key == "name" and not val.strip():
                    continue
                plain[q.key] = val
            # preserve extra preset keys that aren't questions (e.g. map position)
            store.set_fields(self.entity_id, plain, source=source)
            if final:
                for q in self.visible():
                    if q.spawn and self.answers.get(q.key) == "yes" and q.key not in self.spawned:
                        self.spawned.add(q.key)
                        res.spawns.append((q.spawn, {"parent": self.answers.get("name", "")}))
        return res

    def _commit_refs(self, q: Question, value: str, res: CommitResult, source: str) -> None:
        store = self.store
        kind = q.kind or "character"
        names = split_list(value) if q.type == "entities" else ([value.strip()] if value.strip() else [])
        ids = []
        for n in names:
            eid = resolve_name(store, n, kind)
            if not eid:
                me = store.get(self.entity_id, with_fields=False)
                eid = store.create_entity(kind, n, source=source)
                store.add_note(eid, f"Created from {me.name if me else 'an'} interview "
                                    f"({q.display_label}).", source="system")
                res.created.append(eid)
            ids.append(eid)
        if q.key == "parent":
            store.set_field(self.entity_id, "parent", ids[0] if ids else "", source=source)
            return
        store.sync_links(self.entity_id, via=q.key, relation=q.relation, targets=ids,
                         source=source, reverse=q.reverse)
