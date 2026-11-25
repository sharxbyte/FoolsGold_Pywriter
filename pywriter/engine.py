"""Interview session: walks a pack's questions, branching on answers, and commits
answers to the project store (creating linked entities as needed)."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches

from .library import Pack, Question, evaluate, render
from .store import KINDS, RELATIONS, Link, ProjectStore, split_list


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


# ------------------------------------------------------------------ relationships
#
# Relationship answers ("Who are her siblings?") are not stored as text. The links
# between entries are the single source of truth, whether they were made in an
# interview, in Talk mode, with "Add connection", or on the Edit tab. Each
# relationship question shows the links that fit it, and saving an answer adds or
# removes exactly those links, so every way of entering information stays in step.

def ref_questions(pack: Pack) -> list[Question]:
    return [q for q in pack.questions if q.type in ("entity", "entities") and q.key != "parent"]


def _seen_relation(q: Question) -> str:
    """The relation as read from the entry that owns the question."""
    return RELATIONS.get(q.relation, q.relation) if q.reverse else q.relation


def linked_refs(store: ProjectStore, pack: Pack, entity_id: str | None) -> dict[str, list[tuple[Link, str]]]:
    """For each relationship question, the existing links (and the other entry) that answer it."""
    qs = ref_questions(pack)
    out: dict[str, list[tuple[Link, str]]] = {q.key: [] for q in qs}
    if not qs or not entity_id:
        return out
    for link, other, seen in store.links_for(entity_id):
        o = store.get(other, with_fields=False)
        if not o:
            continue
        q = pack.question(link.via) if link.via else None
        mine = q is not None and q in qs and (link.dst == entity_id if q.reverse else link.src == entity_id)
        if not mine:
            cands = [c for c in qs if _seen_relation(c) == seen and (c.kind or "character") == o.kind]
            if len(cands) > 1:  # e.g. "participants" (a list) and "point of view" (one) both use "involves"
                cands = [c for c in cands if c.type == "entities"] or cands
            if len(cands) != 1:
                continue  # ambiguous: it still shows under Connections
            q = cands[0]
        out[q.key].append((link, other))
    for q in qs:
        # links made by this very question first, then the oldest
        out[q.key].sort(key=lambda lo: (lo[0].via != q.key, lo[0].id))
        if q.type == "entity":
            out[q.key] = out[q.key][:1]
    return out


def linked_answers(store: ProjectStore, pack: Pack, entity_id: str | None) -> dict[str, str]:
    """Relationship answers as text ("Tomas Venn, Elda Rhee"), read from the links."""
    out = {}
    for key, items in linked_refs(store, pack, entity_id).items():
        names = []
        for _, other in items:
            o = store.get(other, with_fields=False)
            if o and o.name not in names:
                names.append(o.name)
        out[key] = ", ".join(names)
    return out


def effective_fields(store: ProjectStore, library, e) -> dict[str, str]:
    """An entry's answers as everyone should see them, with relationship answers taken from links."""
    fields = dict(e.fields)
    if e.kind != "project":
        pack = library.pack_for_kind(e.kind, store.project_type)
        if pack:
            fields.update(linked_answers(store, pack, e.id))
    return fields


def set_answer(store: ProjectStore, library, entity_id: str, key: str, value: str,
               source: str = "edit") -> None:
    """Save one answer from anywhere (Edit tab, Talk mode, the assistant). Relationship
    answers become links exactly as they would in an interview."""
    e = store.get(entity_id, with_fields=False)
    if not e:
        return
    pack = library.pack_for_kind(e.kind, store.project_type) if e.kind != "project" else None
    q = pack.question(key) if pack else None
    if q and q.type in ("entity", "entities"):
        iv = Interview(pack, store, entity_id)
        iv.answers[key] = value
        with store.batch():
            res = CommitResult(entity_id)
            iv._commit_refs(q, value, res, source)
    else:
        store.set_field(entity_id, key, value, source=source)


def split_names(text: str, known: list[str]) -> list[str]:
    """Split a list of names, keeping known names whole even when they contain
    "and" or "&" ("Bread and Butter Inn")."""
    import re
    found: list[tuple[int, str]] = []
    rest = text or ""
    for name in sorted({n for n in known if n}, key=len, reverse=True):
        pat = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.I)
        m = pat.search(rest)
        if m:
            found.append((m.start(), name))
            rest = rest[:m.start()] + "," + " " * (len(m.group(0)) - 1) + rest[m.end():]
    found += [(text.find(p) if text else 0, p) for p in split_list(rest)]
    out = []
    for _, n in sorted(found):
        if n.lower() not in (x.lower() for x in out):
            out.append(n)
    return out


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
                self.answers.update(linked_answers(store, pack, self.entity_id))
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
        for k, v in linked_answers(self.store, self.pack, e.id).items():
            if v and not self.answers.get(k):
                self.answers[k] = v
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
                    continue  # relationships live in links (see linked_refs), not text
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
        current = [] if q.key == "parent" else linked_refs(store, self.pack, self.entity_id).get(q.key, [])
        by_name = {}
        for _, other in current:
            o = store.get(other, with_fields=False)
            if o:
                by_name.setdefault(o.name.lower(), other)
        if q.type == "entities":
            names = split_names(value, [n for _, k, n in store.all_names() if k == kind] +
                                [store.get(o, with_fields=False).name for _, o in current])
        else:
            names = [value.strip()] if value.strip() else []
        ids = []
        for n in names:
            eid = by_name.get(n.strip().lower()) or resolve_name(store, n, kind)
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
        # remove links this answer no longer lists (wherever they were made), add the new ones
        for link, other in current:
            if other not in ids:
                store.unlink(link.src, link.dst, link.relation, source=source)
        have = {other for _, other in current}
        for t in ids:
            if t in have or t == self.entity_id:
                continue
            a, b = (t, self.entity_id) if q.reverse else (self.entity_id, t)
            store.link(a, b, q.relation, via=q.key, source=source)
