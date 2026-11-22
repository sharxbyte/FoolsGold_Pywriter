"""Project database.

One SQLite file per project holds everything:

* ``entities``  - characters, locations, events, ... each with a readable ID (CHR-0001)
* ``fields``    - key/value answers for each entity (one row per interview answer)
* ``links``     - typed relations between entities ("sibling", "lives in", ...)
* ``notes``     - free notes attached to entities
* ``revisions`` - append-only change log; every change is recorded with old and new
                  values so any single change can be reverted and history is never lost
* ``conversation`` - transcript of Talk-mode conversations
* ``meta``      - project-level settings (type, title, ...)

The store is deliberately free of Qt so it can be tested and reused on its own.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 1

# kind -> (ID prefix, singular label, plural label)
KINDS: dict[str, tuple[str, str, str]] = {
    "project": ("PRJ", "Project", "Project"),
    "character": ("CHR", "Character", "Characters"),
    "location": ("LOC", "Location", "Locations"),
    "group": ("GRP", "Group", "Groups & Factions"),
    "item": ("ITM", "Item", "Items & Artifacts"),
    "event": ("EVT", "Event", "Timeline"),
    "plot": ("PLT", "Plot Thread", "Plot"),
    "theme": ("THM", "Theme", "Themes"),
    "topic": ("TOP", "Topic", "Topics"),
    "source": ("SRC", "Source", "Sources"),
    "scene": ("SCN", "Scene", "Manuscript"),
}

TIERS = ("primary", "secondary", "tertiary")
TIER_LABELS = {"primary": "Main", "secondary": "Secondary", "tertiary": "Minor", "": "Unsorted"}

# relation -> inverse relation (as read from the other end)
RELATIONS: dict[str, str] = {
    "related to": "related to",
    "friend": "friend",
    "ally": "ally",
    "enemy": "enemy",
    "rival": "rival",
    "sibling": "sibling",
    "parent": "child",
    "child": "parent",
    "guardian": "ward",
    "ward": "guardian",
    "spouse": "spouse",
    "partner": "partner",
    "love interest": "love interest",
    "ex-partner": "ex-partner",
    "relative": "relative",
    "mentor": "student",
    "student": "mentor",
    "employer": "employee",
    "employee": "employer",
    "colleague": "colleague",
    "member of": "has member",
    "leader of": "led by",
    "lives in": "home of",
    "born in": "birthplace of",
    "works in": "workplace of",
    "located in": "contains",
    "based in": "base of",
    "involved in": "involves",
    "happens in": "setting of",
    "owns": "owned by",
    "appears in": "features",
    "mentions": "mentioned by",
    "cites": "cited by",
    "explores": "explored in",
}
# make the inverse table symmetric
for _k, _v in list(RELATIONS.items()):
    RELATIONS.setdefault(_v, _k)

SPECIAL_KEYS = {"name", "tier", "parent"}


def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


@dataclass
class Entity:
    id: str
    kind: str
    name: str
    tier: str = ""
    parent_id: str | None = None
    sort_order: float = 0.0
    created: str = ""
    updated: str = ""
    deleted: bool = False
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.name or "(unnamed)"

    def get(self, key: str, default: str = "") -> str:
        if key == "name":
            return self.name
        if key == "tier":
            return self.tier
        if key == "parent":
            return self.parent_id or ""
        return self.fields.get(key, default)


@dataclass
class Link:
    id: int
    src: str
    dst: str
    relation: str
    via: str
    note: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS counters(prefix TEXT PRIMARY KEY, n INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entities(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL DEFAULT '',
    parent_id TEXT,
    sort_order REAL NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_entities_kind ON entities(kind, deleted);
CREATE TABLE IF NOT EXISTS fields(
    entity_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL,
    PRIMARY KEY(entity_id, key)
);
CREATE TABLE IF NOT EXISTS links(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    relation TEXT NOT NULL,
    via TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    UNIQUE(src, dst, relation)
);
CREATE INDEX IF NOT EXISTS ix_links_src ON links(src);
CREATE INDEX IF NOT EXISTS ix_links_dst ON links(dst);
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session TEXT NOT NULL,
    entity_id TEXT,
    action TEXT NOT NULL,
    key TEXT,
    old TEXT,
    new TEXT,
    source TEXT NOT NULL DEFAULT 'edit'
);
CREATE INDEX IF NOT EXISTS ix_revisions_entity ON revisions(entity_id);
CREATE TABLE IF NOT EXISTS conversation(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    speaker TEXT NOT NULL,
    text TEXT NOT NULL
);
"""


class ProjectStore:
    """Access to a single project database."""

    EXT = ".pwdb"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.session = uuid.uuid4().hex[:8]
        self._listeners: list[Callable[[str, str | None], None]] = []
        self._batch_depth = 0
        self._pending_events: list[tuple[str, str | None]] = []
        self.conn: sqlite3.Connection = self._connect()

    # ------------------------------------------------------------------ lifecycle
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=DELETE")  # single self-contained file
        conn.executescript(_SCHEMA)
        if conn.execute("SELECT 1 FROM meta WHERE key='schema_version'").fetchone() is None:
            conn.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        return conn

    @classmethod
    def create(cls, folder: Path, title: str, project_type: str) -> "ProjectStore":
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{title}{cls.EXT}"
        store = cls(path)
        with store.batch():
            store.set_meta("title", title)
            store.set_meta("project_type", project_type)
            store.set_meta("created", now())
            store.create_entity("project", title, source="system")
        return store

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def reopen(self) -> None:
        self.close()
        self.conn = self._connect()
        self._emit("reload", None)

    @property
    def folder(self) -> Path:
        return self.path.parent

    @property
    def title(self) -> str:
        return self.meta("title") or self.path.stem

    @property
    def project_type(self) -> str:
        return self.meta("project_type") or "Fiction"

    # ------------------------------------------------------------------ events
    def subscribe(self, fn: Callable[[str, str | None], None]) -> None:
        self._listeners.append(fn)

    def _emit(self, what: str, entity_id: str | None) -> None:
        if self._batch_depth:
            self._pending_events.append((what, entity_id))
            return
        for fn in list(self._listeners):
            try:
                fn(what, entity_id)
            except Exception:  # listeners must never break storage
                import traceback
                traceback.print_exc()

    class _Batch:
        def __init__(self, store: "ProjectStore"):
            self.s = store

        def __enter__(self):
            if self.s._batch_depth == 0:
                self.s.conn.execute("BEGIN")
            self.s._batch_depth += 1
            return self.s

        def __exit__(self, exc_type, exc, tb):
            self.s._batch_depth -= 1
            if self.s._batch_depth == 0:
                if exc_type is None:
                    self.s.conn.execute("COMMIT")
                else:
                    self.s.conn.execute("ROLLBACK")
                events, self.s._pending_events = self.s._pending_events, []
                if exc_type is None:
                    seen = set()
                    for ev in events:
                        if ev not in seen:
                            seen.add(ev)
                            self.s._emit(*ev)
            return False

    def batch(self) -> "_Batch":
        """Group several changes into one transaction (and one UI refresh)."""
        return ProjectStore._Batch(self)

    # ------------------------------------------------------------------ meta
    def meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str, log: bool = True) -> None:
        """Set a project setting. ``log=False`` for UI state (map layout) that
        shouldn't clutter the change history."""
        old = self.meta(key)
        if old == value:
            return
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))
        if log:
            self._log(None, "meta", key, old, value, "system")
            self._emit("meta", None)

    # ------------------------------------------------------------------ revisions
    def _log(self, entity_id, action, key, old, new, source) -> None:
        self.conn.execute(
            "INSERT INTO revisions(ts, session, entity_id, action, key, old, new, source)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (now(), self.session, entity_id, action, key, old, new, source),
        )

    def revision_count(self) -> int:
        return self.conn.execute("SELECT COALESCE(MAX(id),0) FROM revisions").fetchone()[0]

    def revisions(self, entity_id: str | None = None, limit: int = 500) -> list[sqlite3.Row]:
        if entity_id:
            q = "SELECT * FROM revisions WHERE entity_id=? ORDER BY id DESC LIMIT ?"
            return self.conn.execute(q, (entity_id, limit)).fetchall()
        return self.conn.execute("SELECT * FROM revisions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def revert(self, rev_id: int) -> bool:
        """Apply the inverse of one revision. The revert itself is logged too."""
        r = self.conn.execute("SELECT * FROM revisions WHERE id=?", (rev_id,)).fetchone()
        if not r:
            return False
        eid, action, key, old = r["entity_id"], r["action"], r["key"], r["old"]
        src = "revert"
        with self.batch():
            if action == "set_field":
                self.set_field(eid, key, old or "", source=src)
            elif action == "create":
                self.delete_entity(eid, source=src)
            elif action == "delete":
                self.undelete_entity(eid, source=src)
            elif action == "link":
                data = json.loads(r["new"])
                self.unlink(data["src"], data["dst"], data["relation"], source=src)
            elif action == "unlink":
                data = json.loads(r["old"])
                self.link(data["src"], data["dst"], data["relation"], via=data.get("via", ""), source=src)
            elif action == "meta":
                self.set_meta(key, old or "")
            else:
                return False
        return True

    def undo_last(self, session_only: bool = True) -> sqlite3.Row | None:
        """Revert the most recent revertible change (from this session by default)."""
        q = ("SELECT * FROM revisions WHERE source!='revert' AND action IN"
             " ('set_field','create','link','unlink','delete')")
        if session_only:
            q += " AND session=?"
            row = self.conn.execute(q + " ORDER BY id DESC LIMIT 1", (self.session,)).fetchone()
        else:
            row = self.conn.execute(q + " ORDER BY id DESC LIMIT 1").fetchone()
        if row and self.revert(row["id"]):
            # mark so it isn't undone twice
            self.conn.execute("UPDATE revisions SET source='undone' WHERE id=?", (row["id"],))
            return row
        return None

    # ------------------------------------------------------------------ ids
    def _next_id(self, kind: str) -> str:
        prefix = KINDS.get(kind, ("ENT",))[0]
        row = self.conn.execute("SELECT n FROM counters WHERE prefix=?", (prefix,)).fetchone()
        n = (row[0] if row else 0) + 1
        self.conn.execute("INSERT OR REPLACE INTO counters VALUES(?,?)", (prefix, n))
        return f"{prefix}-{n:04d}"

    # ------------------------------------------------------------------ entities
    def create_entity(self, kind: str, name: str = "", tier: str = "", parent_id: str | None = None,
                      fields: dict[str, str] | None = None, source: str = "edit") -> str:
        with self.batch():
            eid = self._next_id(kind)
            ts = now()
            order = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order),0)+1 FROM entities WHERE kind=?", (kind,)).fetchone()[0]
            self.conn.execute(
                "INSERT INTO entities(id, kind, name, tier, parent_id, sort_order, created, updated)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (eid, kind, name.strip(), tier, parent_id, order, ts, ts),
            )
            self._log(eid, "create", kind, None, name, source)
            for k, v in (fields or {}).items():
                self.set_field(eid, k, v, source=source)
            self._emit("entity", eid)
        return eid

    def _row_to_entity(self, row: sqlite3.Row, with_fields: bool = True) -> Entity:
        e = Entity(id=row["id"], kind=row["kind"], name=row["name"], tier=row["tier"],
                   parent_id=row["parent_id"], sort_order=row["sort_order"],
                   created=row["created"], updated=row["updated"], deleted=bool(row["deleted"]))
        if with_fields:
            for f in self.conn.execute("SELECT key, value FROM fields WHERE entity_id=?", (e.id,)):
                e.fields[f["key"]] = f["value"]
        return e

    def get(self, entity_id: str | None, with_fields: bool = True) -> Entity | None:
        if not entity_id:
            return None
        row = self.conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        return self._row_to_entity(row, with_fields) if row else None

    def entities(self, kind: str | None = None, include_deleted: bool = False,
                 with_fields: bool = False) -> list[Entity]:
        q = "SELECT * FROM entities WHERE 1=1"
        args: list[Any] = []
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if not include_deleted:
            q += " AND deleted=0"
        q += " ORDER BY kind, sort_order, name COLLATE NOCASE"
        return [self._row_to_entity(r, with_fields) for r in self.conn.execute(q, args)]

    def project_entity(self) -> Entity:
        rows = self.entities("project", with_fields=True)
        if rows:
            return rows[0]
        eid = self.create_entity("project", self.title, source="system")
        return self.get(eid)  # type: ignore[return-value]

    def find_by_name(self, name: str, kind: str | None = None) -> Entity | None:
        q = "SELECT * FROM entities WHERE deleted=0 AND name=? COLLATE NOCASE"
        args: list[Any] = [name.strip()]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        row = self.conn.execute(q, args).fetchone()
        return self._row_to_entity(row) if row else None

    def all_names(self) -> list[tuple[str, str, str]]:
        """(id, kind, name) for every live, named entity except the project itself.
        Aliases (field 'aliases', comma-separated) are included as extra rows."""
        out = []
        for r in self.conn.execute(
                "SELECT id, kind, name FROM entities WHERE deleted=0 AND kind!='project' AND name!=''"):
            out.append((r["id"], r["kind"], r["name"]))
        for r in self.conn.execute(
                "SELECT f.entity_id, e.kind, f.value FROM fields f JOIN entities e ON e.id=f.entity_id"
                " WHERE f.key='aliases' AND e.deleted=0 AND f.value!=''"):
            for alias in split_list(r["value"]):
                out.append((r["entity_id"], r["kind"], alias))
        return out

    def set_field(self, entity_id: str, key: str, value: Any, source: str = "edit") -> bool:
        """Set one answer. Returns True if anything changed."""
        value = "" if value is None else str(value)
        e_row = self.conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        if not e_row:
            raise KeyError(entity_id)
        if key in SPECIAL_KEYS:
            column = {"name": "name", "tier": "tier", "parent": "parent_id"}[key]
            old = e_row[column] or ""
            if key == "name":
                value = value.strip()
            if old == value:
                return False
            self.conn.execute(f"UPDATE entities SET {column}=?, updated=? WHERE id=?",
                              (value or (None if key == "parent" else ""), now(), entity_id))
        else:
            row = self.conn.execute("SELECT value FROM fields WHERE entity_id=? AND key=?",
                                    (entity_id, key)).fetchone()
            old = row[0] if row else ""
            if old == value:
                return False
            if value == "":
                self.conn.execute("DELETE FROM fields WHERE entity_id=? AND key=?", (entity_id, key))
            else:
                self.conn.execute("INSERT OR REPLACE INTO fields VALUES(?,?,?,?)",
                                  (entity_id, key, value, now()))
            self.conn.execute("UPDATE entities SET updated=? WHERE id=?", (now(), entity_id))
        self._log(entity_id, "set_field", key, old, value, source)
        self._emit("entity", entity_id)
        return True

    def set_fields(self, entity_id: str, values: dict[str, Any], source: str = "edit") -> int:
        changed = 0
        with self.batch():
            for k, v in values.items():
                changed += self.set_field(entity_id, k, v, source=source)
        return changed

    def delete_entity(self, entity_id: str, source: str = "edit") -> None:
        self.conn.execute("UPDATE entities SET deleted=1, updated=? WHERE id=?", (now(), entity_id))
        self._log(entity_id, "delete", None, None, None, source)
        self._emit("entity", entity_id)

    def undelete_entity(self, entity_id: str, source: str = "edit") -> None:
        self.conn.execute("UPDATE entities SET deleted=0, updated=? WHERE id=?", (now(), entity_id))
        self._log(entity_id, "undelete", None, None, None, source)
        self._emit("entity", entity_id)

    def move(self, entity_id: str, new_order: float) -> None:
        self.conn.execute("UPDATE entities SET sort_order=? WHERE id=?", (new_order, entity_id))
        self._emit("entity", entity_id)

    def children(self, parent_id: str) -> list[Entity]:
        rows = self.conn.execute(
            "SELECT * FROM entities WHERE parent_id=? AND deleted=0 ORDER BY sort_order, name", (parent_id,))
        return [self._row_to_entity(r, False) for r in rows]

    def ancestors(self, entity_id: str) -> list[Entity]:
        out, seen = [], {entity_id}
        e = self.get(entity_id, with_fields=False)
        while e and e.parent_id and e.parent_id not in seen:
            seen.add(e.parent_id)
            e = self.get(e.parent_id, with_fields=False)
            if e:
                out.append(e)
        return out

    # ------------------------------------------------------------------ links
    def link(self, src: str, dst: str, relation: str, via: str = "", note: str = "",
             source: str = "edit") -> bool:
        if src == dst:
            return False
        relation = relation.strip().lower() or "related to"
        # avoid storing the same relation twice from both ends
        inv = RELATIONS.get(relation)
        if inv and self.conn.execute("SELECT 1 FROM links WHERE src=? AND dst=? AND relation=?",
                                     (dst, src, inv)).fetchone():
            return False
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO links(src, dst, relation, via, note, created) VALUES(?,?,?,?,?,?)",
            (src, dst, relation, via, note, now()))
        if cur.rowcount:
            self._log(src, "link", relation, None,
                      json.dumps({"src": src, "dst": dst, "relation": relation, "via": via}), source)
            self._emit("link", src)
            self._emit("link", dst)
            return True
        return False

    def unlink(self, src: str, dst: str, relation: str, source: str = "edit") -> bool:
        row = self.conn.execute("SELECT * FROM links WHERE src=? AND dst=? AND relation=?",
                                (src, dst, relation)).fetchone()
        if not row:
            return False
        self.conn.execute("DELETE FROM links WHERE id=?", (row["id"],))
        self._log(src, "unlink", relation,
                  json.dumps({"src": src, "dst": dst, "relation": relation, "via": row["via"]}), None, source)
        self._emit("link", src)
        self._emit("link", dst)
        return True

    def links_for(self, entity_id: str) -> list[tuple[Link, str, str]]:
        """All links touching an entity as (link, other_id, relation-as-seen-from-entity)."""
        out = []
        for r in self.conn.execute(
                "SELECT l.* FROM links l JOIN entities e ON e.id = CASE WHEN l.src=? THEN l.dst ELSE l.src END"
                " WHERE (l.src=? OR l.dst=?) AND e.deleted=0 ORDER BY l.relation",
                (entity_id, entity_id, entity_id)):
            link = Link(r["id"], r["src"], r["dst"], r["relation"], r["via"], r["note"])
            if link.src == entity_id:
                out.append((link, link.dst, link.relation))
            else:
                out.append((link, link.src, RELATIONS.get(link.relation, link.relation)))
        return out

    def all_links(self) -> list[Link]:
        return [Link(r["id"], r["src"], r["dst"], r["relation"], r["via"], r["note"])
                for r in self.conn.execute(
                    "SELECT l.* FROM links l JOIN entities a ON a.id=l.src JOIN entities b ON b.id=l.dst"
                    " WHERE a.deleted=0 AND b.deleted=0")]

    def sync_links(self, src: str, via: str, relation: str, targets: Iterable[str],
                   source: str = "interview", reverse: bool = False) -> None:
        """Make links created by one interview answer (``via``) match ``targets``.

        ``reverse`` stores the link as target -> src (e.g. "member of" from a group's
        member list)."""
        targets = [t for t in targets if t and t != src]
        with self.batch():
            col_self, col_other = ("dst", "src") if reverse else ("src", "dst")
            existing = self.conn.execute(
                f"SELECT {col_other} AS other, relation FROM links WHERE {col_self}=? AND via=?",
                (src, via)).fetchall()
            for row in existing:
                if row["other"] not in targets or row["relation"] != relation:
                    a, b = (row["other"], src) if reverse else (src, row["other"])
                    self.unlink(a, b, row["relation"], source=source)
            for t in targets:
                a, b = (t, src) if reverse else (src, t)
                self.link(a, b, relation, via=via, source=source)

    # ------------------------------------------------------------------ notes
    def add_note(self, entity_id: str, text: str, source: str = "manual") -> int:
        cur = self.conn.execute("INSERT INTO notes(entity_id, text, source, created) VALUES(?,?,?,?)",
                                (entity_id, text, source, now()))
        self._log(entity_id, "note", None, None, text, source)
        self._emit("entity", entity_id)
        return cur.lastrowid

    def notes_for(self, entity_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM notes WHERE entity_id=? ORDER BY id", (entity_id,)).fetchall()

    def delete_note(self, note_id: int) -> None:
        row = self.conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        if row:
            self.conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
            self._log(row["entity_id"], "delete_note", None, row["text"], None, "edit")
            self._emit("entity", row["entity_id"])

    # ------------------------------------------------------------------ conversation
    def log_conversation(self, speaker: str, text: str) -> None:
        self.conn.execute("INSERT INTO conversation(ts, speaker, text) VALUES(?,?,?)", (now(), speaker, text))

    def conversation(self, limit: int = 200) -> list[sqlite3.Row]:
        rows = self.conn.execute("SELECT * FROM conversation ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return list(reversed(rows))


def split_list(text: str) -> list[str]:
    """Split a comma / semicolon / newline / 'and' separated list of names."""
    import re
    if not text:
        return []
    parts = re.split(r"\s*(?:,|;|\n|\band\b|&)\s*", text)
    return [p.strip(" .") for p in parts if p and p.strip(" .")]
