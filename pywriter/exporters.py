"""Exports for keeping and using a project outside PyWriter.

* Word (.docx): the Story Bible and the Manuscript as ordinary documents.
* Spreadsheets (.csv): one sheet per kind of entry (a row per entry, a column per
  question), plus connections, notes and scenes. Opens in Excel, LibreOffice
  Calc, Numbers and Google Sheets.
* JSON: a complete, lossless copy of the project database in an open format.
* Backup (.zip): all of the above, plus a copy of the project database that
  PyWriter can open directly.

Relationship answers ("Siblings: Tomas Venn") are taken from the links between
entries, exactly as the app shows them.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .engine import effective_fields
from .library import LEVEL_LABELS, Library
from .store import KINDS, TIER_LABELS, Entity, ProjectStore

EXPORT_FORMAT = 1


# ------------------------------------------------------------------ shared view of an entry

@dataclass
class EntryView:
    entity: Entity
    within: list[str] = field(default_factory=list)                      # outermost first
    sections: list[tuple[str, list[tuple[str, str, str]]]] = field(default_factory=list)  # (title, [(key, label, text)])
    extra: list[tuple[str, str]] = field(default_factory=list)            # (label, text)
    connections: list[tuple[str, str, str]] = field(default_factory=list)  # (relation, name, id)
    notes: list[tuple[str, str]] = field(default_factory=list)            # (created, text)


def _questions(lib: Library, kind: str, project_type: str) -> dict:
    packs = lib.project_packs(project_type) if kind == "project" else \
        [p for p in [lib.pack_for_kind(kind, project_type)] if p]
    return {q.key: q for p in packs for q in p.questions}


def _text(q, key: str, value: str) -> str:
    if key == "level":
        return LEVEL_LABELS.get(value, value)
    if q is not None and q.type in ("choice", "yesno"):
        return q.option_label(value)
    return value


def entry_view(store: ProjectStore, lib: Library, e: Entity) -> EntryView:
    fields = effective_fields(store, lib, e)
    qmap = _questions(lib, e.kind, store.project_type)
    v = EntryView(e, within=[a.label for a in reversed(store.ancestors(e.id))])
    used = {"name", "tier", "parent"}
    for title, keys in lib.labels_for(e.kind, store.project_type):
        rows = []
        for key, label in keys:
            if key in used:
                continue
            used.add(key)
            val = (fields.get(key) or "").strip()
            if val:
                text = _text(qmap.get(key), key, val)
                details = (fields.get(key + "_details") or "").strip()
                if details:
                    text += " — " + details
                    used.add(key + "_details")
                rows.append((key, label, text))
        if rows:
            v.sections.append((title, rows))
    v.extra = [(k.replace("_", " ").capitalize(), val.strip()) for k, val in sorted(fields.items())
               if k not in used and not k.startswith("_") and val and val.strip()
               and not (e.kind == "scene" and k == "text")]
    for _, other, rel in store.links_for(e.id):
        o = store.get(other, with_fields=False)
        if o:
            v.connections.append((rel, o.label, o.id))
    v.notes = [(n["created"], n["text"]) for n in store.notes_for(e.id)]
    return v


def _ordered(store: ProjectStore, kind: str) -> list[Entity]:
    ents = store.entities(kind, with_fields=True)
    if kind == "event":
        def key(e: Entity):
            try:
                return float(e.fields.get("order", "") or 1e9), e.sort_order
            except ValueError:
                return 1e9, e.sort_order
        ents.sort(key=key)
    elif kind == "character":
        rank = {"primary": 0, "secondary": 1, "tertiary": 2, "": 3}
        ents.sort(key=lambda e: (rank.get(e.tier, 3), e.name.lower()))
    elif kind == "scene":
        ents.sort(key=lambda e: e.sort_order)
    else:
        ents.sort(key=lambda e: e.name.lower())
    return ents


def _kind_label(store: ProjectStore, kind: str) -> str:
    if kind == "character" and store.project_type != "Fiction":
        return "People"
    if kind == "location" and store.project_type != "Fiction":
        return "Places"
    return KINDS[kind][2]


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "Untitled"


# ------------------------------------------------------------------ Word

def _docx():
    try:
        import docx  # python-docx
        return docx
    except ImportError as e:  # pragma: no cover - depends on the install
        raise RuntimeError("Word export needs the python-docx package:  pip install python-docx") from e


def export_story_bible_docx(store: ProjectStore, lib: Library, path: Path) -> Path:
    docx = _docx()
    from docx.shared import Pt
    doc = docx.Document()
    doc.core_properties.title = f"{store.title} - Story Bible"
    doc.core_properties.comments = "Exported from FoolsGold PyWriter"
    doc.add_heading(store.title, 0)
    p = doc.add_paragraph()
    p.add_run(f"Story Bible · {store.project_type} project · exported {_dt.datetime.now():%Y-%m-%d %H:%M}").italic = True

    def entry(v: EntryView, level: int) -> None:
        e = v.entity
        tier = f" · {TIER_LABELS.get(e.tier, e.tier)}" if e.tier else ""
        doc.add_heading(f"{e.label}{tier}  ({e.id})" if e.kind != "project" else "Project", level)
        if v.within:
            doc.add_paragraph().add_run("Within: " + " › ".join(v.within)).italic = True
        for title, rows in v.sections + ([("Other details", [("", k, t) for k, t in v.extra])] if v.extra else []):
            doc.add_heading(title, level + 1)
            table = doc.add_table(rows=0, cols=2)
            table.style = "Table Grid"
            for _, label, text in rows:
                cells = table.add_row().cells
                cells[0].text = label
                for r in cells[0].paragraphs[0].runs:
                    r.bold = True
                cells[1].text = text
            for row in table.rows:
                row.cells[0].width = docx.shared.Inches(1.9)
                row.cells[1].width = docx.shared.Inches(4.6)
        if v.connections:
            doc.add_heading("Connections", level + 1)
            for rel, name, oid in v.connections:
                doc.add_paragraph(f"{rel.capitalize()}: {name} ({oid})", style="List Bullet")
        if v.notes:
            doc.add_heading("Notes", level + 1)
            for created, text in v.notes:
                doc.add_paragraph(f"[{created[:16].replace('T', ' ')}] {text}", style="List Bullet")

    entry(entry_view(store, lib, store.project_entity()), 1)
    for kind in KINDS:
        if kind in ("project", "scene"):
            continue
        ents = _ordered(store, kind)
        if not ents:
            continue
        doc.add_page_break()
        doc.add_heading(_kind_label(store, kind), 1)
        for e in ents:
            entry(entry_view(store, lib, e), 2)
    for st in ("Normal",):
        doc.styles[st].font.size = Pt(10.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def export_manuscript_docx(store: ProjectStore, path: Path) -> Path:
    docx = _docx()
    doc = docx.Document()
    doc.core_properties.title = store.title
    doc.core_properties.comments = "Exported from FoolsGold PyWriter"
    doc.add_heading(store.title, 0)
    for i, s in enumerate(_ordered(store, "scene")):
        if i:
            doc.add_page_break()
        doc.add_heading(s.label, 1)
        if s.fields.get("synopsis"):
            doc.add_paragraph().add_run(s.fields["synopsis"]).italic = True
        for para in re.split(r"\n\s*\n", s.fields.get("text", "")):
            if para.strip():
                doc.add_paragraph(para.strip("\n"))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


# ------------------------------------------------------------------ spreadsheets

def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    # UTF-8 with a byte-order mark so Excel shows accents and other scripts correctly
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def export_csv(store: ProjectStore, lib: Library, folder: Path) -> list[Path]:
    """One CSV per kind of entry, plus connections, notes and scenes."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    names = {e.id: e.label for e in store.entities(include_deleted=True)}
    for kind in KINDS:
        if kind == "scene":
            continue
        ents = [store.project_entity()] if kind == "project" else _ordered(store, kind)
        if not ents:
            continue
        views = [entry_view(store, lib, e) for e in ents]
        cols: list[str] = []
        for v in views:   # question columns in interview order, then any extra details
            for _, rows in v.sections:
                for _, label, _ in rows:
                    if label not in cols:
                        cols.append(label)
        extra_cols = sorted({k for v in views for k, _ in v.extra} - set(cols))
        header = ["ID", "Name"] + (["Importance"] if kind == "character" else []) + \
                 (["Inside"] if kind == "location" else []) + cols + extra_cols + ["Connections", "Notes"]
        rows = []
        for v in views:
            e = v.entity
            vals = {label: text for _, rs in v.sections for _, label, text in rs}
            vals.update(dict(v.extra))
            row = [e.id, e.label]
            if kind == "character":
                row.append(TIER_LABELS.get(e.tier, e.tier) if e.tier else "")
            if kind == "location":
                row.append(" › ".join(v.within))
            row += [vals.get(c, "") for c in cols + extra_cols]
            row.append("; ".join(f"{rel}: {name}" for rel, name, _ in v.connections))
            row.append("\n".join(t for _, t in v.notes))
            rows.append(row)
        p = folder / f"{safe_filename('Project' if kind == 'project' else _kind_label(store, kind))}.csv"
        _write_csv(p, header, rows)
        written.append(p)
    links = [[l.src, names.get(l.src, ""), l.relation, l.dst, names.get(l.dst, ""), l.via]
             for l in store.all_links()]
    if links:
        p = folder / "Connections.csv"
        _write_csv(p, ["From ID", "From", "Relation", "To ID", "To", "Interview question"], links)
        written.append(p)
    notes = []
    for e in store.entities():
        for n in store.notes_for(e.id):
            notes.append([e.id, e.label, n["created"], n["source"], n["text"]])
    if notes:
        p = folder / "Notes.csv"
        _write_csv(p, ["Entry ID", "Entry", "Created", "Source", "Note"], notes)
        written.append(p)
    scenes = _ordered(store, "scene")
    if scenes:
        p = folder / "Manuscript scenes.csv"
        _write_csv(p, ["ID", "Order", "Title", "Synopsis", "Words", "Text"],
                   [[s.id, str(i + 1), s.label, s.fields.get("synopsis", ""),
                     str(len(s.fields.get("text", "").split())), s.fields.get("text", "")]
                    for i, s in enumerate(scenes)])
        written.append(p)
    return written


# ------------------------------------------------------------------ JSON (lossless)

def export_json(store: ProjectStore, path: Path) -> Path:
    """Every table of the project database, as plain JSON."""
    c = store.conn

    def rows(sql: str) -> list[dict]:
        return [dict(r) for r in c.execute(sql)]

    data = {
        "format": "FoolsGold PyWriter project export",
        "format_version": EXPORT_FORMAT,
        "exported": _dt.datetime.now().isoformat(timespec="seconds"),
        "title": store.title,
        "project_type": store.project_type,
        "meta": {r["key"]: r["value"] for r in rows("SELECT * FROM meta")},
        "entities": rows("SELECT * FROM entities ORDER BY id"),
        "fields": rows("SELECT * FROM fields ORDER BY entity_id, key"),
        "links": rows("SELECT * FROM links ORDER BY id"),
        "notes": rows("SELECT * FROM notes ORDER BY id"),
        "conversation": rows("SELECT * FROM conversation ORDER BY id"),
        "revisions": rows("SELECT * FROM revisions ORDER BY id"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# ------------------------------------------------------------------ complete backup

_README = """FoolsGold PyWriter backup of "{title}"
Made {when}.

What's in this archive
  {db}                  The project database. To use it, unzip this archive into a
                        folder and open the .pwdb file with File > New / Open project
                        in PyWriter.
  {title}.json          The whole project as plain JSON (every entry, answer, link,
                        note, Talk conversation and change), for other programs or
                        long-term keeping.
  Story Bible.docx      Everything about your story as a Word document.
  Story Bible.md        The same as plain text (Markdown).
  Manuscript.docx/.md   Your scenes, if you've written any.
  Spreadsheets/         One .csv per kind of entry, plus connections, notes and scenes.
                        Open them in Excel, LibreOffice Calc or Google Sheets.
  {transcript}

Everything you write with PyWriter is yours. See TERMS-OF-USE.md in the program folder.
"""


def export_backup_zip(store: ProjectStore, lib: Library, path: Path) -> Path:
    from .export import export_manuscript, export_story_bible
    title = safe_filename(store.title)
    with tempfile.TemporaryDirectory(prefix="pywriter-export-") as td:
        tmp = Path(td)
        db = tmp / f"{title}.pwdb"
        dest = sqlite3.connect(str(db))
        try:
            store.conn.backup(dest)   # consistent copy even while the project is open
        finally:
            dest.close()
        export_json(store, tmp / f"{title}.json")
        export_story_bible_docx(store, lib, tmp / "Story Bible.docx")
        export_story_bible(store, lib, tmp / "Story Bible.md")
        if store.entities("scene"):
            export_manuscript_docx(store, tmp / "Manuscript.docx")
            export_manuscript(store, tmp / "Manuscript.md")
        export_csv(store, lib, tmp / "Spreadsheets")
        transcript = next(iter(store.folder.glob("*_voice-transcript.txt")), None)
        if transcript:
            shutil.copy2(transcript, tmp / transcript.name)
        (tmp / "READ ME.txt").write_text(_README.format(
            title=store.title, when=f"{_dt.datetime.now():%Y-%m-%d %H:%M}", db=db.name,
            transcript=f"{transcript.name}  Everything PyWriter heard and said." if transcript else ""),
            encoding="utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".zip.part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(tmp.rglob("*")):
                if f.is_file():
                    z.write(f, f"{title}/{f.relative_to(tmp).as_posix()}")
        part.replace(path)
    return path
