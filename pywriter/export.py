"""Human-readable Story Bible (Markdown), regenerated from the database on save.

Every entry is headed with the same ID used in the database and change log
(e.g. ``CHR-0001``), so the readable file and the database always line up.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from .library import LEVEL_LABELS, Library
from .store import KINDS, TIER_LABELS, Entity, ProjectStore


def _questions(lib: Library, kind: str, project_type: str) -> dict:
    packs = lib.project_packs(project_type) if kind == "project" else         [p for p in [lib.pack_for_kind(kind, project_type)] if p]
    return {q.key: q for p in packs for q in p.questions}


def _value_text(q, key: str, value: str) -> str:
    if key == "level":
        return LEVEL_LABELS.get(value, value)
    if q is not None and q.type in ("choice", "yesno"):
        return q.option_label(value)
    return value


def entity_markdown(store: ProjectStore, lib: Library, e: Entity, heading: str = "###") -> list[str]:
    lines = []
    tier = f" · {TIER_LABELS.get(e.tier, e.tier)}" if e.tier else ""
    lines.append(f"{heading} {e.id} — {e.label}{tier}")
    anc = store.ancestors(e.id)
    if anc:
        lines.append(f"*Within: {' › '.join(a.label for a in reversed(anc))}*")
    lines.append("")
    used = {"name", "tier", "parent"}
    qmap = _questions(lib, e.kind, store.project_type)
    for section, keys in lib.labels_for(e.kind, store.project_type):
        rows = [(k, label, e.fields[k]) for k, label in keys if e.fields.get(k) and k not in used]
        used.update(k for k, _ in keys)
        if rows:
            lines.append(f"**{section}**")
            lines.append("")
            for k, label, val in rows:
                val = _value_text(qmap.get(k), k, val).strip()
                if "\n" in val:
                    lines.append(f"- *{label}:*")
                    lines.extend(f"  > {ln}" for ln in val.splitlines())
                else:
                    lines.append(f"- *{label}:* {val}")
            lines.append("")
    extra = {k: v for k, v in e.fields.items() if k not in used and not k.startswith("_") and v}
    if extra:
        lines.append("**Other details**")
        lines.append("")
        lines.extend(f"- *{k.replace('_', ' ').capitalize()}:* {v}" for k, v in sorted(extra.items()))
        lines.append("")
    links = store.links_for(e.id)
    if links:
        lines.append("**Connections**")
        lines.append("")
        for _, other, rel in links:
            o = store.get(other, with_fields=False)
            if o:
                lines.append(f"- {rel.capitalize()}: {o.label} ({o.id})")
        lines.append("")
    notes = store.notes_for(e.id)
    if notes:
        lines.append("**Notes**")
        lines.append("")
        lines.extend(f"- [{n['created']}] {n['text']}" for n in notes)
        lines.append("")
    return lines


def export_story_bible(store: ProjectStore, lib: Library, path: Path | None = None) -> Path:
    path = path or store.folder / f"{store.title} - Story Bible.md"
    out = [f"# {store.title}", "",
           f"*{store.project_type} project · exported {_dt.datetime.now():%Y-%m-%d %H:%M} · "
           f"change #{store.revision_count()}*", ""]
    proj = store.project_entity()
    out.append("## Project")
    out.append("")
    out.extend(entity_markdown(store, lib, proj)[2:])
    for kind, (_, _, plural) in KINDS.items():
        if kind == "project":
            continue
        ents = store.entities(kind, with_fields=True)
        if kind == "scene":
            continue  # manuscript text is exported separately
        if not ents:
            continue
        out.append(f"## {plural}")
        out.append("")
        if kind == "event":
            def order_key(e: Entity):
                try:
                    return float(e.fields.get("order", "") or 1e9), e.sort_order
                except ValueError:
                    return 1e9, e.sort_order
            ents.sort(key=order_key)
        elif kind == "character":
            rank = {"primary": 0, "secondary": 1, "tertiary": 2, "": 3}
            ents.sort(key=lambda e: (rank.get(e.tier, 3), e.name.lower()))
        for e in ents:
            out.extend(entity_markdown(store, lib, e))
    # recent change log
    out.append("## Recent changes")
    out.append("")
    out.append("| # | When | Entry | Change | Field | Source |")
    out.append("|---|---|---|---|---|---|")
    names = {e.id: e.label for e in store.entities(include_deleted=True)}
    for r in store.revisions(limit=200):
        out.append(f"| {r['id']} | {r['ts']} | {r['entity_id'] or ''} {names.get(r['entity_id'], '')} "
                   f"| {r['action']} | {r['key'] or ''} | {r['source']} |")
    out.append("")
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(out), encoding="utf-8")
    tmp.replace(path)
    return path


def export_manuscript(store: ProjectStore, path: Path | None = None) -> Path:
    path = path or store.folder / f"{store.title} - Manuscript.md"
    scenes = sorted(store.entities("scene", with_fields=True), key=lambda e: e.sort_order)
    out = [f"# {store.title}", ""]
    for s in scenes:
        out.append(f"## {s.label}")
        out.append("")
        out.append(s.fields.get("text", ""))
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")
    return path
