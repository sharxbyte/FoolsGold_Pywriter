"""Condensed bios used for hover tooltips, Talk-mode answers and read-aloud."""
from __future__ import annotations

import html

from .library import LEVEL_LABELS
from .store import KINDS, TIER_LABELS, Entity, ProjectStore

# fields shown in the short bio, per kind, in order
BRIEF_FIELDS: dict[str, list[str]] = {
    "character": ["story_role", "age", "species", "occupation", "pronouns", "height", "build", "hair",
                  "eyes", "features", "personality", "want", "relationship_to_subject", "born"],
    "location": ["place_type", "importance", "look", "mood", "population", "climate"],
    "group": ["group_type", "purpose", "size"],
    "item": ["item_type", "look", "significance"],
    "event": ["when", "summary", "significance"],
    "plot": ["thread_type", "summary", "goal"],
    "theme": ["statement"],
    "topic": ["question", "claim"],
    "source": ["source_type", "author", "published"],
    "scene": ["synopsis"],
    "project": ["premise", "genre", "subject", "topic"],
}

LABELS = {
    "story_role": "Role", "age": "Age", "species": "Species", "occupation": "Occupation",
    "pronouns": "Pronouns", "height": "Height", "build": "Build", "hair": "Hair", "eyes": "Eyes",
    "features": "Features", "personality": "Personality", "want": "Wants",
    "relationship_to_subject": "Connection", "born": "Born",
    "place_type": "Type", "importance": "Importance", "look": "Looks", "mood": "Mood",
    "population": "Population", "climate": "Climate", "group_type": "Type", "purpose": "Purpose",
    "size": "Size", "item_type": "Type", "significance": "Significance", "when": "When",
    "summary": "Summary", "thread_type": "Thread", "goal": "Goal", "statement": "Statement",
    "question": "Question", "claim": "Claim", "source_type": "Type", "author": "Author",
    "published": "Published", "synopsis": "Synopsis", "premise": "Premise", "genre": "Genre",
    "subject": "Subject", "topic": "Topic",
}


def _clip(s: str, n: int = 140) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def subtitle(store: ProjectStore, e: Entity) -> str:
    parts = [KINDS.get(e.kind, ("", e.kind))[1]]
    if e.kind == "character" and e.tier:
        parts.insert(0, TIER_LABELS.get(e.tier, e.tier))
    if e.kind == "location" and e.fields.get("level"):
        parts = [LEVEL_LABELS.get(e.fields["level"], e.fields["level"])]
        anc = store.ancestors(e.id)
        if anc:
            parts.append("in " + anc[0].label)
    return " · ".join(parts)


def brief_rows(store: ProjectStore, e: Entity, max_rows: int = 7) -> list[tuple[str, str]]:
    rows = []
    for k in BRIEF_FIELDS.get(e.kind, []):
        v = e.fields.get(k, "").strip()
        if v:
            rows.append((LABELS.get(k, k), _clip(v)))
        if len(rows) >= max_rows:
            break
    return rows


def tooltip_html(store: ProjectStore, entity_id: str) -> str:
    e = store.get(entity_id)
    if not e:
        return ""
    out = [f"<b>{html.escape(e.label)}</b> <span style='color:gray'>({e.id})</span><br>"
           f"<i>{html.escape(subtitle(store, e))}</i>"]
    rows = brief_rows(store, e)
    if rows:
        out.append("<table style='margin-top:4px'>")
        for label, v in rows:
            out.append(f"<tr><td style='padding-right:6px;color:gray'>{label}</td>"
                       f"<td>{html.escape(v)}</td></tr>")
        out.append("</table>")
    links = store.links_for(e.id)[:6]
    if links:
        names = []
        for _, other, rel in links:
            o = store.get(other, with_fields=False)
            if o:
                names.append(f"{html.escape(rel)}: {html.escape(o.label)}")
        out.append("<div style='margin-top:4px;color:gray'>" + "<br>".join(names) + "</div>")
    out.append("<div style='margin-top:4px;color:gray'><small>Click to open the full sheet</small></div>")
    return "".join(out)


def spoken_summary(store: ProjectStore, entity_id: str) -> str:
    e = store.get(entity_id)
    if not e:
        return "I couldn't find that entry."
    bits = [f"{e.label}. {subtitle(store, e)}."]
    for label, v in brief_rows(store, e, max_rows=6):
        bits.append(f"{label}: {v.rstrip('.')}.")
    links = store.links_for(e.id)[:5]
    if links:
        rels = []
        for _, other, rel in links:
            o = store.get(other, with_fields=False)
            if o:
                rels.append(f"{rel} {o.label}")
        bits.append("Connections: " + "; ".join(rels) + ".")
    if len(bits) == 1:
        bits.append("There aren't any details yet. You could start an interview to fill them in.")
    return " ".join(bits)
