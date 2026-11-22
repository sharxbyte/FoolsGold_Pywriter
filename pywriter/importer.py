"""Import projects saved by PyWriter Alpha v10/v11 (the Tkinter version's .json files)."""
from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

from .library import Library
from .store import ProjectStore

SECTION_KIND = {"characters": "character", "settings": "location", "history": "event", "topics": "topic"}


_STOP = set("what is the a an of and or to in does do did was were their they this that how character's "
             "character’s characters character person's person your story any with for are has have its it "
             "please describe tell me about who which place location story type kind like what's".split())


def _words(s: str) -> set[str]:
    import re
    s = re.sub(r"\{[^}]*\}", " ", s)  # template placeholders like {name}
    out = set()
    for w in re.findall(r"[a-z]+", s.lower().replace("’", "'")):
        if w in _STOP or len(w) <= 2:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)  # crude plural stemming
    return out


def _best_question(pack, text: str):
    """Match an old question to the closest new one. Conservative on purpose: an answer
    filed under the wrong field is worse than one kept under 'Imported from v11'."""
    best, score = None, 0.0
    t, tw = text.lower(), _words(text)
    for q in pack.questions:
        lw = _words(q.display_label)
        qw = _words(q.ask) | lw
        shared = tw & qw
        seq = SequenceMatcher(None, t, q.ask.lower()).ratio()
        ok = seq >= 0.8 or len(shared) >= 2 or (len(shared) == 1 and shared <= lw and len(lw) <= 2 and len(tw) <= 4)
        if not ok:
            continue
        s = max(seq, len(shared) / max(1, min(len(tw), len(qw))) + 0.2 * len(shared & lw))
        if s > score:
            best, score = q, s
    return best


def import_v11(path: Path, store: ProjectStore, lib: Library) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ptype = store.project_type
    counts = {"entries": 0, "matched": 0, "unmatched": 0, "notes": 0, "links": 0}
    id_map: dict[str, str] = {}
    pending_links: list[tuple[str, str]] = []
    with store.batch():
        if data.get("summary"):
            proj = store.project_entity()
            key = "premise" if ptype == "Fiction" else "imported_summary"
            if not proj.fields.get(key):
                store.set_field(proj.id, key, data["summary"], source="import")
        for section, kind in SECTION_KIND.items():
            if kind == "topic" and ptype != "Non-Fiction":
                kind = "theme" if ptype != "Fiction" else "plot"
            pack = lib.pack_for_kind(kind, ptype)
            for entry in data.get(section, []) or []:
                answers = entry.get("answers", entry) if isinstance(entry, dict) else {}
                answers = {q: a for q, a in answers.items() if isinstance(a, str) and a.strip()}
                name, name_q = "", None
                for q, a in answers.items():
                    if "name" in q.lower() or "called" in q.lower() or "title" in q.lower():
                        name, name_q = a.strip().split("\n")[0][:80], q
                        break
                if not name and answers:
                    name = next(iter(answers.values())).strip().split("\n")[0][:60]
                eid = store.create_entity(kind, name or f"Imported {kind}", source="import")
                counts["entries"] += 1
                if entry.get("id"):
                    id_map[entry["id"]] = eid
                leftovers = []
                for q, a in answers.items():
                    if q == name_q and a.strip() == name:
                        continue
                    target = _best_question(pack, q) if pack else None
                    if target and target.key not in ("name",) and target.type not in ("entity", "entities"):
                        existing = store.get(eid).fields.get(target.key, "")
                        value = a if not existing else existing + "\n\n" + a
                        store.set_field(eid, target.key, value, source="import")
                        counts["matched"] += 1
                    elif not (target and target.key == "name"):
                        leftovers.append(f"Q: {q}\nA: {a}")
                        counts["unmatched"] += 1
                if leftovers:
                    store.set_field(eid, "imported_from_v11", "\n\n".join(leftovers), source="import")
                for n in entry.get("notes", []) or []:
                    text = n.get("content", "") if isinstance(n, dict) else str(n)
                    if text:
                        store.add_note(eid, text, source="import")
                        counts["notes"] += 1
                for lid in entry.get("links", []) or []:
                    pending_links.append((eid, lid))
        for eid, old in pending_links:
            if old in id_map and store.link(eid, id_map[old], "related to", source="import"):
                counts["links"] += 1
    return counts
