"""Talk mode: a rule-based interpreter that turns casual statements into
structured story-bible updates. It never writes prose; it only files what the
writer says.

Examples it understands::

    "Mara is the protagonist."                -> tier=primary, story_role=protagonist
    "She has red hair and green eyes."        -> hair / eyes on the last-mentioned character
    "Mara lives in Port Vell."                -> link Mara -lives in-> Port Vell (created if new)
    "Tomas is Mara's older brother."          -> sibling link
    "Mara is 34 years old."                   -> age
    "Change Mara's occupation to smuggler."   -> occupation
    "Open Port Vell" / "Tell me about Mara" / "Interview Tomas" / "Add a new location" / "Undo"

Anything it can't file is kept as a note on the entry being discussed (or the
project), and every exchange is stored in the conversation log, so nothing is lost.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches

from .engine import effective_fields, ref_questions, set_answer
from .library import Library
from .names import needs_spelling_check, parse_spelling, spell_out
from .store import KINDS, ProjectStore
from .summary import spoken_summary

KIND_WORDS = {
    "character": "character", "person": "character", "people": "character", "characters": "character",
    "location": "location", "place": "location", "places": "location", "locations": "location",
    "setting": "location", "settings": "location",
    "group": "group", "organization": "group", "organisation": "group", "faction": "group",
    "groups": "group", "family": "group",
    "item": "item", "object": "item", "artifact": "item", "artefact": "item", "items": "item",
    "event": "event", "events": "event", "timeline": "event",
    "theme": "theme", "themes": "theme",
    "plot": "plot", "subplot": "plot", "storyline": "plot",
    "topic": "topic", "topics": "topic",
    "source": "source", "sources": "source", "reference": "source",
}
KIND_ALT = "|".join(sorted(KIND_WORDS, key=len, reverse=True))

TIER_WORDS = {
    "primary": r"main character|protagonist|main|major character|lead|hero|heroine|central character|"
               r"primary character|antagonist|villain|narrator",
    "secondary": r"secondary character|supporting character|side character|secondary|supporting|sidekick",
    "tertiary": r"minor character|background character|minor|tertiary|extra|bit part|cameo",
}
ROLE_WORDS = r"protagonist|antagonist|villain|hero|heroine|mentor|love interest|sidekick|narrator|" \
             r"rival|foil|comic relief|anti-hero|antihero|deuteragonist"

REL_WORDS: dict[str, str] = {
    "sister": "sibling", "brother": "sibling", "sibling": "sibling", "twin": "sibling",
    "half-sister": "sibling", "half-brother": "sibling", "stepsister": "sibling", "stepbrother": "sibling",
    "mother": "parent", "father": "parent", "mom": "parent", "mum": "parent", "dad": "parent",
    "parent": "parent", "stepmother": "parent", "stepfather": "parent", "guardian": "guardian",
    "son": "child", "daughter": "child", "child": "child", "kid": "child", "ward": "ward",
    "wife": "spouse", "husband": "spouse", "spouse": "spouse",
    "girlfriend": "partner", "boyfriend": "partner", "partner": "partner", "lover": "partner",
    "fiance": "partner", "fiancee": "partner", "ex": "ex-partner", "ex-wife": "ex-partner",
    "ex-husband": "ex-partner",
    "friend": "friend", "best friend": "friend", "companion": "friend",
    "enemy": "enemy", "nemesis": "enemy", "arch-enemy": "enemy", "archenemy": "enemy",
    "rival": "rival", "ally": "ally",
    "mentor": "mentor", "teacher": "mentor", "master": "mentor",
    "student": "student", "apprentice": "student", "pupil": "student",
    "boss": "employer", "employer": "employer",
    "employee": "employee", "assistant": "employee", "servant": "employee",
    "colleague": "colleague", "coworker": "colleague", "co-worker": "colleague", "partner in crime": "ally",
    "uncle": "relative", "aunt": "relative", "cousin": "relative", "grandmother": "relative",
    "grandfather": "relative", "grandma": "relative", "grandpa": "relative", "niece": "relative",
    "nephew": "relative", "relative": "relative",
    "love interest": "love interest", "crush": "love interest",
}
REL_ALT = "|".join(sorted(map(re.escape, REL_WORDS), key=len, reverse=True))
PLURAL_REL = {"siblings": "sibling", "friends": "friend", "enemies": "enemy", "rivals": "rival",
              "married": "spouse", "partners": "partner", "allies": "ally", "colleagues": "colleague",
              "cousins": "relative", "lovers": "partner", "twins": "sibling"}

# keyword -> field, per kind (first match wins)
FIELD_LEXICON: dict[str, list[tuple[str, str]]] = {
    "character": [
        (r"\b(?:years? old|aged?)\b", "age"),
        (r"\bhair\b|\bblond(?:e)?\b|\bbrunette\b|\bredhead\b|\bbald\b", "hair"),
        (r"\beyes?\b|\beyed\b", "eyes"),
        (r"\btall\b|\bshort\b|\bfeet\b|\bfoot\b|\binches\b|\bcm\b|\bheight\b", "height"),
        (r"\bscars?\b|\btattoos?\b|\bbirthmark\b|\bpiercings?\b|\bfreckles\b|\blimp\b|\bmissing\b|\bprosthetic\b",
         "features"),
        (r"\b(?:thin|skinny|muscular|stocky|slim|heavy|lean|broad|petite|plump|wiry|athletic|"
         r"heavyset|chubby|burly|lanky|fat)\b", "build"),
        (r"\bwears?\b|\bdressed\b|\bdresses\b|\bcoat\b|\bcloak\b|\bboots\b|\bhat\b|\bjacket\b|\buniform\b",
         "clothing"),
        (r"\bvoice\b|\baccent\b|\braspy\b|\bhusky\b|\bstutter", "voice"),
        (r"\bafraid\b|\bscared\b|\bfears?\b|\bterrified\b|\bphobia\b", "fear"),
        (r"\bwants?\b|\bdreams? of\b|\blongs? (?:for|to)\b|\bdesires?\b|\bgoal\b", "want"),
        (r"\bsecret\b", "secret"),
        (r"\bcan\b|\bgood at\b|\bskilled\b|\bexpert\b|\btalented\b|\bable to\b", "skills"),
        (r"\bworks? as\b|\bjob\b|\bprofession\b|\boccupation\b|\bfor a living\b", "occupation"),
        (r"\bloves?\b|\badores?\b|\benjoys?\b", "loves"),
        (r"\bhates?\b|\bdespises?\b|\bcan'?t stand\b", "hates"),
        (r"\bspeaks?\b|\blanguages?\b|\bfluent\b", "languages"),
        (r"\bpronouns?\b", "pronouns"),
    ],
    "location": [
        (r"\bpopulation\b|\bpeople live\b|\binhabitants\b", "population"),
        (r"\bruled\b|\bgoverned\b|\bgovernment\b|\bking\b|\bqueen\b|\bmayor\b|\bcouncil\b", "governance"),
        (r"\btrade\b|\beconomy\b|\bexports?\b|\bmines?\b|\bfarm(?:s|ing)?\b|\bmarket\b", "economy"),
        (r"\bclimate\b|\bweather\b|\bcold\b|\bhot\b|\brain(?:y|s)?\b|\bsnow(?:y)?\b|\bfoggy\b|\bhumid\b",
         "climate"),
        (r"\bdangerous\b|\bdanger\b|\bmonsters?\b|\bbandits?\b|\bdeadly\b", "dangers"),
        (r"\bsmells?\b", "smells"),
        (r"\bsounds?\b|\bnoisy\b|\bquiet\b", "sounds"),
        (r"\bsecret\b|\bhidden\b", "secrets"),
    ],
}
DEFAULT_FIELD = {"character": "personality", "location": "look", "group": "purpose", "item": "look",
                 "event": "summary", "plot": "summary", "theme": "statement", "topic": "claim",
                 "source": "key_points", "project": "notes_from_talk"}
# When a project type's interview has no question for a Talk fact (Biography and
# Non-Fiction people and places are asked fewer questions), file it under the
# nearest question instead, so it shows up in that interview and on the Edit tab.
FIELD_FALLBACK: dict[str, dict[str, str]] = {
    "character": {"eyes": "features", "height": "build", "want": "values", "secret": "relationship_notes",
                  "skills": "qualifications", "story_role": "role_in_book"},
    "location": {"population": "community", "governance": "community", "economy": "conditions",
                 "climate": "conditions", "dangers": "conditions", "smells": "look", "sounds": "look",
                 "secrets": "significance"},
}
REPLACE_FIELDS = {"age", "occupation", "pronouns", "story_role", "height", "level", "place_type"}

LEVEL_WORDS = {
    "room": "room", "chamber": "room", "office": "room", "cell": "room",
    "building": "building", "house": "building", "tavern": "building", "inn": "building", "castle": "building",
    "tower": "building", "temple": "building", "church": "building", "shop": "building", "ship": "building",
    "starship": "building", "station": "building", "mansion": "building", "palace": "building",
    "school": "building", "farmhouse": "building", "apartment": "building", "fortress": "building",
    "forest": "site", "lake": "site", "mountain": "site", "cave": "site", "river": "site", "valley": "site",
    "island": "site", "ruins": "site", "park": "site",
    "neighborhood": "district", "neighbourhood": "district", "district": "district", "quarter": "district",
    "village": "settlement", "town": "settlement", "city": "settlement", "port": "settlement",
    "capital": "settlement", "hamlet": "settlement",
    "region": "region", "province": "region", "county": "region", "desert": "region", "wilderness": "region",
    "country": "country", "kingdom": "country", "nation": "country", "empire": "country", "republic": "country",
    "continent": "continent", "planet": "planet", "world": "planet", "moon": "planet",
    "star system": "star_system", "galaxy": "galaxy", "universe": "universe",
    "dimension": "dimension", "realm": "dimension", "plane": "dimension", "timeline": "timeline",
}

STOP = set("""
a an the i me my we our you your he him his she her they them their it its this that these those
there here who what when where why how which and or but so then also just really very well okay ok
um uh like yes no not maybe story book chapter scene project everyone someone somebody nobody
everybody something nothing everything one ones man woman boy girl people person thing things
character characters place places today tomorrow yesterday now later always never sometimes
""".split())

PRONOUNS = r"\b(?:she|he|they|her|him|them|it)\b"
SUBJ_PRON = {"she", "he", "they", "it", "her", "his", "their", "its", "him", "them"}


@dataclass
class Reply:
    text: str
    open_entity: str | None = None
    start_interview: tuple[str, str | None] | None = None  # (kind, entity_id)
    changed: list[str] = field(default_factory=list)


@dataclass
class _Pending:
    kind: str                       # 'ask_kind' | 'ask_tier' | 'confirm_delete' | 'offer_interview' | 'spell'
    name: str = ""
    entity_id: str = ""
    sentences: list[str] = field(default_factory=list)
    reason: str = ""
    choices: list[str] = field(default_factory=list)


class Interpreter:
    def __init__(self, store: ProjectStore, library: Library):
        self.store = store
        self.lib = library
        self.focus: str | None = None
        self.pending: _Pending | None = None
        self._spoken = False

    # ================================================================ public
    def handle(self, text: str, spoken: bool = False) -> Reply:
        """Interpret one utterance. ``spoken`` means it came from speech recognition,
        so new names get a spelling check."""
        self._spoken = spoken
        text = text.strip()
        if not text:
            return Reply("")
        self.store.log_conversation("writer", text)
        reply = self._handle(text)
        if reply.text:
            self.store.log_conversation("pywriter", reply.text)
        return reply

    def kinds(self) -> list[str]:
        """Kinds of entry this project type has (and shows in the sidebar)."""
        return [k for k in KINDS if k not in ("project", "scene")
                and self.lib.pack_for_kind(k, self.store.project_type)]

    def _kind_word(self, kind: str) -> str:
        if kind == "character":
            return "character" if self.store.project_type == "Fiction" else "person"
        return {"location": "place"}.get(kind, KINDS[kind][1].lower())

    def _kind_question(self, name: str) -> str:
        # the kinds people name in conversation; plot threads and themes can still be added by name
        common = [k for k in ("character", "location", "group", "item", "event", "topic", "source")
                  if k in self.kinds() and not (k == "source" and self.store.project_type == "Fiction")]
        words = [("an " if self._kind_word(k)[0] in "aeiou" else "a ") + self._kind_word(k) for k in common]
        return f"Is {name} " + ", ".join(words[:-1]) + ", or " + words[-1] + "?"

    def _not_here(self, kind: str) -> str:
        return (f"{self.store.project_type} projects don't have {KINDS[kind][2].lower()}. You can add "
                + ", ".join(self._kind_word(k) + "s" for k in self.kinds()) + ".")

    def set_focus(self, entity_id: str | None) -> None:
        self.focus = entity_id

    # ================================================================ routing
    def _handle(self, text: str) -> Reply:
        if self.pending:
            r = self._answer_pending(text)
            if r:
                return r
        low = text.lower().strip(" .!?")

        if re.fullmatch(r"(?:undo|undo that|take that back|scratch that)", low):
            row = self.store.undo_last()
            return Reply("Done, I've undone the last change." if row else "There's nothing to undo.",
                         changed=[row["entity_id"]] if row else [])

        if re.fullmatch(r"(?:help|what can (?:i|you) (?:say|do))", low):
            return Reply(HELP_TEXT)

        m = re.match(rf"^(?:please\s+)?(?:add|create|make|start)\s+(?:a\s+|an\s+)?(?:new\s+)?({KIND_ALT})"
                     r"(?:\s+(?:named|called)\s+(.+))?$", low)
        if m:
            kind = KIND_WORDS[m.group(1)]
            if kind not in self.kinds():
                return Reply(self._not_here(kind))
            name = self._orig(text, m.group(2)) if m.group(2) else ""
            if not name:
                return Reply(f"Let's add a new {KINDS[kind][1].lower()}. I'll start the interview.",
                             start_interview=(kind, None))
            return self._create_named(kind, self._clean_name(name), [])

        m = re.match(r"^(?:open|show(?: me)?|go to|display)\s+(.+)$", low)
        if m:
            eid = self._lookup(m.group(1))
            if eid:
                self.focus = eid
                return Reply(f"Opening {self.store.get(eid).label}.", open_entity=eid)
            return Reply(f"I couldn't find anything called {self._orig(text, m.group(1))}.")

        m = re.match(r"^(?:tell me about|who is|who's|what is|what's|describe|read(?: me)?|remind me about)\s+(.+)$",
                     low)
        if m and not re.search(r"'s\s+\w+", m.group(1)):
            eid = self._lookup(m.group(1))
            if eid:
                self.focus = eid
                return Reply(spoken_summary(self.store, eid))
            if len(m.group(1).split()) <= 4:
                said = self._orig(text, m.group(1))
                return Reply(f"I don't have anything called {said} yet. You can say "
                             f"'add a character named {said}', or just tell me about them.")

        m = re.match(rf"^(?:interview(?: me)?(?: about| on| for)?|start (?:an |the )?interview (?:for|about|on|with))"
                     rf"\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(.+)$", low)
        if m:
            target = m.group(1).strip()
            if target in KIND_WORDS:
                kind = KIND_WORDS[target]
                if kind not in self.kinds():
                    return Reply(self._not_here(kind))
                return Reply(f"Starting a new {KINDS[kind][1].lower()} interview.", start_interview=(kind, None))
            eid = self._lookup(target)
            if eid:
                e = self.store.get(eid)
                return Reply(f"Starting the interview for {e.label}.", start_interview=(e.kind, eid))
            said = self._orig(text, target)
            return Reply(f"I don't have anyone or anything called {said} yet. "
                         f"Say 'add a character named {said}' first.")

        m = re.match(r"^(?:delete|remove)\s+(.+)$", low)
        if m:
            eid = self._lookup(m.group(1))
            if eid:
                self.pending = _Pending("confirm_delete", entity_id=eid)
                return Reply(f"Are you sure you want to delete {self.store.get(eid).label}? Say yes or no.")

        m = re.match(r"^(?:change|set|update|make)\s+(.+?)'s\s+(.+?)\s+(?:to|as)\s+(.+)$", low)
        if m:
            return self._explicit_edit(self._orig(text, m.group(1)), m.group(2), self._orig(text, m.group(3)))

        return self._statements(text)

    # ================================================================ pending
    def _answer_pending(self, text: str) -> Reply | None:
        p = self.pending
        low = text.lower()
        yes = bool(re.match(r"^\s*(?:yes|yeah|yep|sure|ok|okay|please|do it|go ahead|confirm)", low))
        no = bool(re.match(r"^\s*(?:no|nope|not now|cancel|never ?mind|later)", low))
        if p.kind == "spell":
            return self._answer_spelling(p, text, yes, no)
        if p.kind == "confirm_delete":
            self.pending = None
            if yes:
                e = self.store.get(p.entity_id)
                self.store.delete_entity(p.entity_id, source="talk")
                return Reply(f"Deleted {e.label}. You can say 'undo' to bring it back.", changed=[p.entity_id])
            return Reply("Okay, I won't delete it.")
        if p.kind == "ask_kind":
            for w, k in sorted(KIND_WORDS.items(), key=lambda wk: -len(wk[0])):
                if re.search(rf"\b{re.escape(w)}\b", low):
                    if k not in self.kinds():
                        return Reply(self._not_here(k) + " " + self._kind_question(p.name))
                    self.pending = None
                    return self._create_named(k, p.name, p.sentences)
            self.pending = None
            for s in p.sentences:
                self._keep_note(s)
            if no:
                return Reply(f"Okay, I won't add {p.name}. I've kept what you said as a note.")
            return None  # the writer moved on; handle the new text normally
        if p.kind == "ask_tier":
            for tier, pat in TIER_WORDS.items():
                if re.search(rf"\b(?:{pat})\b", low):
                    self.pending = None
                    self.store.set_field(p.entity_id, "tier", tier, source="talk")
                    e = self.store.get(p.entity_id)
                    self.pending = _Pending("offer_interview", entity_id=p.entity_id)
                    return Reply(f"Got it, {e.label} is a {tier_phrase(tier)}. "
                                 f"Would you like to do {e.label}'s interview now?", changed=[e.id])
            if no or re.search(r"\b(?:not sure|don'?t know|skip|later)\b", low):
                self.pending = None
                return Reply("No problem, you can decide later.")
            self.pending = None
            return None  # treat as a normal statement
        if p.kind == "offer_interview":
            self.pending = None
            if yes:
                e = self.store.get(p.entity_id)
                return Reply(f"Starting {e.label}'s interview.", start_interview=(e.kind, e.id))
            if no:
                return Reply("Okay. Keep telling me about the story whenever you like.")
            return None
        self.pending = None
        return None

    # ================================================================ creation
    def _create_named(self, kind: str, name: str, sentences: list[str]) -> Reply:
        existing = self.store.find_by_name(name, kind)
        if existing:
            self.focus = existing.id
            msg = f"{existing.label} already exists, so I'll add to it."
            if sentences:
                return self._statements(_rejoin(sentences), prefix=msg)
            return Reply(msg, open_entity=existing.id)
        eid = self.store.create_entity(kind, name, source="talk")
        self.focus = eid
        parts = [f"I've added {name} as a new {KINDS[kind][1].lower()}."]
        changed = [eid]
        if sentences:
            r = self._statements(_rejoin(sentences), announce=False)
            changed += r.changed
            if r.text:
                parts.append(r.text)
        check = needs_spelling_check(name, person=kind == "character") if self._spoken else None
        if check:
            reason, choices = check
            self.pending = _Pending("spell", entity_id=eid, name=name, reason=reason, choices=choices)
            parts.append(self._spelling_prompt(name, reason, choices))
        else:
            parts.append(self._followup(eid))
        return Reply(" ".join(parts), changed=changed)

    def _followup(self, eid: str) -> str:
        e = self.store.get(eid)
        if e.kind == "character" and not e.tier:
            self.pending = _Pending("ask_tier", entity_id=eid)
            return f"Is {e.label} a main character, a secondary character, or a minor character?"
        self.pending = _Pending("offer_interview", entity_id=eid)
        return f"Would you like to do the interview for {e.label} now?"

    @staticmethod
    def _spelling_prompt(name: str, reason: str, choices: list[str]) -> str:
        if reason == "variants":
            opts = "; ".join(f"{i + 1}, {c}" for i, c in enumerate(choices))
            return (f"There are a few common spellings of {name}: {opts}. Which one? Say or type the number, "
                    f"type the name, or spell it letter by letter.")
        return (f"I've spelled that {spell_out(name)} Is that right? Say yes, type the correct spelling, "
                f"or spell it letter by letter.")

    def _answer_spelling(self, p: "_Pending", text: str, yes: bool, no: bool) -> Reply:
        low = text.lower().strip(" .!?")
        nums = {"one": 1, "first": 1, "1": 1, "two": 2, "second": 2, "2": 2, "three": 3, "third": 3, "3": 3,
                "four": 4, "fourth": 4, "4": 4, "five": 5, "5": 5}
        chosen = None
        words = low.replace("number", " ").split()
        if p.reason == "variants" and len(words) <= 2:
            for w in words:
                if w in nums and nums[w] <= len(p.choices):
                    chosen = p.choices[nums[w] - 1]
        if not chosen:
            for c in p.choices:
                if low == c.lower():
                    chosen = c
        if not chosen:
            chosen = parse_spelling(text)
            if chosen and len(chosen.split()) < len(p.name.split()):
                chosen = " ".join([chosen] + p.name.split()[len(chosen.split()):])
        if not chosen and not self._spoken and not yes and not no and 1 <= len(text.split()) <= 5:
            chosen = text.strip(" .!?")  # a typed correction
        if chosen:
            self.store.set_field(p.entity_id, "name", chosen, source="talk")
            self.pending = None
            return Reply(f"Got it, {chosen}. " + self._followup(p.entity_id), changed=[p.entity_id])
        if yes:
            self.pending = None
            return Reply("Great. " + self._followup(p.entity_id))
        if no:
            return Reply("Okay, please spell it letter by letter, or type it.")
        return Reply("Sorry, I didn't catch that. " + self._spelling_prompt(p.name, p.reason, p.choices))

    # ================================================================ statements
    def _statements(self, text: str, prefix: str = "", announce: bool = True) -> Reply:
        sentences = split_sentences(text)
        done: list[str] = []
        created: list[str] = []
        changed: list[str] = []
        for i, s in enumerate(sentences):
            res = self._statement(s)
            if res is None:
                continue
            if isinstance(res, _Pending):
                # stop and ask; re-run this and the remaining sentences once answered
                res.sentences = sentences[i:]
                self.pending = res
                head = (prefix + " " if prefix else "") + (" ".join(done) + " " if done else "")
                return Reply(head + f"I don't know {res.name} yet. " + self._kind_question(res.name),
                             changed=changed)
            msg, ids, new = res
            if msg:
                done.append(msg)
            changed += ids
            created += new
        if created:
            done.append("New entries: " + ", ".join(self.store.get(c).label for c in created) + ".")
        if not done:
            return Reply(prefix or "", changed=changed)
        out = " ".join(done)
        if prefix:
            out = prefix + " " + out
        return Reply(out if announce else out, changed=changed)

    def _statement(self, s: str):
        """Returns None, a _Pending (unknown name), or (message, changed_ids, created_ids)."""
        low = s.lower().strip(" .!?")
        if not low:
            return None

        # "Mara and Tomas are siblings"
        m = re.match(r"^(.+?)\s+and\s+(.+?)\s+are\s+(?:(?:best|close|old)\s+)?(?:\w+\s+)?(" +
                     "|".join(PLURAL_REL) + r")\b", low)
        if m:
            a, b = self._subject(m.group(1), s), self._subject(m.group(2), s)
            for x in (a, b):
                if isinstance(x, _Pending):
                    return x
            if a and b:
                rel = PLURAL_REL[m.group(3)]
                self.store.link(a, b, rel, source="talk")
                return (f"Noted that {self._n(a)} and {self._n(b)} are {m.group(3)}.", [a, b], [])

        # "Tomas is Mara's (older) brother"
        m = re.match(rf"^(.+?)\s+(?:is|was)\s+(.+?)'s\s+(?:\w+\s+)?({REL_ALT})\b", low)
        if m:
            a, b = self._subject(m.group(1), s), self._subject(m.group(2), s)
            for x in (a, b):
                if isinstance(x, _Pending):
                    return x
            if a and b:
                rel = REL_WORDS[m.group(3)]
                self.store.link(b, a, rel, source="talk")
                self.focus = a
                return (f"Noted that {self._n(a)} is {self._n(b)}'s {m.group(3)}.", [a, b], [])

        # "Mara's brother is Tomas"
        m = re.match(rf"^(.+?)'s\s+(?:\w+\s+)?({REL_ALT})\s+(?:is|was)\s+(?:called\s+|named\s+)?(.+)$", low)
        if m:
            owner = self._subject(m.group(1), s)
            if isinstance(owner, _Pending):
                return owner
            if owner:
                kind = "character"
                other = self._lookup(m.group(3)) or None
                created = []
                if not other:
                    other = self.store.create_entity(kind, self._clean_name(self._orig(s, m.group(3))), source="talk")
                    created.append(other)
                self.store.link(owner, other, REL_WORDS[m.group(2)], source="talk")
                return (f"Noted that {self._n(other)} is {self._n(owner)}'s {m.group(2)}.", [owner, other], created)

        # "Mara is the sister of Tomas"
        m = re.match(rf"^(.+?)\s+(?:is|was)\s+(?:the|a|an)\s+({REL_ALT})\s+of\s+(.+)$", low)
        if m:
            a, b = self._subject(m.group(1), s), self._subject(m.group(3), s)
            for x in (a, b):
                if isinstance(x, _Pending):
                    return x
            if a and b:
                self.store.link(b, a, REL_WORDS[m.group(2)], source="talk")
                return (f"Noted that {self._n(a)} is {self._n(b)}'s {m.group(2)}.", [a, b], [])

        # location / group relations
        loc_patterns = [
            (r"\s+(?:lives|lived|resides|resided|stays|stayed)\s+(?:in|at|on)\s+(?:the\s+)?(.+)$", "lives in", "location"),
            (r"\s+(?:is|was|comes|came)\s+(?:originally\s+)?from\s+(?:the\s+)?(.+)$", "born in", "location"),
            (r"\s+(?:was born|was created|was made)\s+(?:in|at|on)\s+(?:the\s+)?(.+)$", "born in", "location"),
            (r"\s+works?\s+(?:at|in|on)\s+(?:the\s+)?(.+)$", "works in", "location"),
            (r"\s+(?:works?|worked)\s+for\s+(?:the\s+)?(.+)$", "employer", "group"),
            (r"\s+(?:is|was)\s+(?:located|found|situated)\s+(?:in|on|at|inside)\s+(?:the\s+)?(.+)$", "located in", "location"),
            (r"\s+(?:is|was)\s+(?:a\s+)?(?:member|part)\s+of\s+(?:the\s+)?(.+)$", "member of", "group"),
            (r"\s+(?:belongs|belonged)\s+to\s+(?:the\s+)?(.+)$", "member of", "group"),
            (r"\s+(?:leads|led|runs|ran|rules|ruled)\s+(?:the\s+)?(.+)$", "leader of", "group"),
        ]
        for pat, rel, kind in loc_patterns:
            m = re.match(r"^(.+?)" + pat, low)
            if m:
                subj = self._subject(m.group(1), s)
                if isinstance(subj, _Pending):
                    return subj
                if not subj:
                    break
                target_text = m.group(2).strip()
                tgt = self._lookup(target_text, kind=kind) or self._lookup(target_text)
                created = []
                if not tgt:
                    orig_target = self._orig(s, target_text)
                    if rel in ("leader of", "employer") and not (re.search(r"[A-Z]", orig_target) or
                                                   re.match(r"the\s", target_text)):
                        break  # "Mara runs a bakery" - not necessarily a named group
                    tgt = self.store.create_entity(kind, self._clean_name(self._orig(s, target_text)), source="talk")
                    created.append(tgt)
                subj_e = self.store.get(subj, with_fields=False)
                if rel == "located in" and subj_e.kind == "location":
                    self.store.set_field(subj, "parent", tgt, source="talk")
                else:
                    self.store.link(subj, tgt, rel, source="talk")
                self.focus = subj
                return (f"Noted that {self._n(subj)} {rel_phrase(rel)} {self._n(tgt)}.", [subj, tgt], created)

        # "X is a/the <tier or role>"
        m = re.match(r"^(.+?)\s+(?:is|will be|was)\s+(?:a|an|the|our|my)?\s*(.+)$", low)
        if m:
            subj = self._subject(m.group(1), s)
            if isinstance(subj, _Pending):
                return subj
            if subj:
                rest = m.group(2).strip()
                e = self.store.get(subj)
                msgs = []
                if e.kind == "character":
                    for tier, pat in TIER_WORDS.items():
                        if re.search(rf"^(?:{pat})\b", rest):
                            self.store.set_field(subj, "tier", tier, source="talk")
                            msgs.append(f"{e.label} is a {tier_phrase(tier)}")
                            break
                    rm = re.search(rf"\b({ROLE_WORDS})\b", rest)
                    if rm:
                        self.store.set_field(subj, "story_role", rm.group(1), source="talk")
                        if not msgs:
                            msgs.append(f"{e.label}'s role is {rm.group(1)}")
                    am = re.match(r"^(\d{1,4})(?:\s+years?\s+old)?$", rest)
                    if am:
                        self.store.set_field(subj, "age", am.group(1), source="talk")
                        msgs.append(f"{e.label} is {am.group(1)}")
                if e.kind == "location":
                    for w, lvl in LEVEL_WORDS.items():
                        if re.search(rf"\b{re.escape(w)}\b", rest):
                            if not e.fields.get("level"):
                                self.store.set_field(subj, "level", lvl, source="talk")
                            if not e.fields.get("place_type"):
                                self.store.set_field(subj, "place_type", self._orig(s, rest), source="talk")
                            msgs.append(f"{e.label} is {'an' if rest[:1] in 'aeiou' else 'a'} {rest}")
                            break
                if msgs:
                    self.focus = subj
                    return ("Noted: " + "; ".join(msgs) + ".", [subj], [])

        # general descriptive sentence about a known subject -> field
        subj = self._sentence_subject(s)
        if isinstance(subj, _Pending):
            return subj
        if subj:
            e = self.store.get(subj)
            # "She has red hair and green eyes" -> hair and eyes, when the parts fit different questions
            pieces = [p for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", s.strip(" .!?")) if p.strip()]
            filed: list[tuple[str, str]] = []
            for i, piece in enumerate(pieces):
                k = self._field_for(e.kind, piece.lower())
                if i and k == DEFAULT_FIELD.get(e.kind) and filed:
                    filed[-1] = (filed[-1][0], filed[-1][1] + " and " + piece.strip())
                else:
                    filed.append((k, piece.strip()))
            if len({k for k, _ in filed}) < 2:
                filed = [(self._field_for(e.kind, low), s)]
            keys = []
            for key, text in filed:
                value = self._orig_sentence(text)
                if key == "age":
                    am = re.search(r"\b(\d{1,4})\b", text)
                    if am:
                        value = am.group(1)
                self._set_or_append(subj, key, value)
                keys.append(label_for(self.lib, self.store, e.kind, key).lower())
            self.focus = subj
            keys = list(dict.fromkeys(keys))
            said = keys[0] if len(keys) == 1 else ", ".join(keys[:-1]) + " and " + keys[-1]
            return (f"Added to {e.label}'s {said}.", [subj], [])

        # nothing understood: keep it
        target = self._keep_note(s)
        return (f"I've kept that as a note on {self._n(target)}.", [target], [])

    # ================================================================ helpers
    def _explicit_edit(self, who: str, what: str, value: str) -> Reply:
        eid = self._lookup(who)
        if not eid:
            return Reply(f"I couldn't find {who}.")
        e = self.store.get(eid)
        key = self._match_field_name(e.kind, what)
        if not key:
            key = what.strip().replace(" ", "_")
        if key in ("name", "tier"):
            self.store.set_field(eid, key, value.strip(" ."), source="talk")
        else:
            set_answer(self.store, self.lib, eid, key, value.strip(" ."), source="talk")
        self.focus = eid
        return Reply(f"Changed {e.label}'s {what} to {value.strip(' .')}.", changed=[eid])

    def _match_field_name(self, kind: str, words: str) -> str | None:
        words = words.lower().strip()
        pack = self.lib.pack_for_kind(kind, self.store.project_type) if kind != "project" else None
        if not pack:
            return None
        candidates = {}
        for q in pack.questions:
            candidates[q.key.replace("_", " ")] = q.key
            candidates[q.display_label.lower()] = q.key
        if words in candidates:
            return candidates[words]
        close = get_close_matches(words, list(candidates), n=1, cutoff=0.7)
        if close:
            return candidates[close[0]]
        for label, key in candidates.items():
            if words in label.split() or words in label:
                return key
        return None

    def _field_for(self, kind: str, low: str) -> str:
        key = DEFAULT_FIELD.get(kind, "notes_from_talk")
        for pat, k in FIELD_LEXICON.get(kind, []):
            if re.search(pat, low):
                key = k
                break
        pack = self.lib.pack_for_kind(kind, self.store.project_type) if kind != "project" else None
        if pack and not pack.question(key):
            alt = FIELD_FALLBACK.get(kind, {}).get(key)
            if alt and pack.question(alt):
                return alt
        return key

    def _set_or_append(self, eid: str, key: str, value: str) -> None:
        e = self.store.get(eid)
        pack = self.lib.pack_for_kind(e.kind, self.store.project_type) if e.kind != "project" else None
        if pack and key in {q.key for q in ref_questions(pack)}:
            # a relationship answer: add the names as links, exactly as an interview would
            old = effective_fields(self.store, self.lib, e).get(key, "")
            set_answer(self.store, self.lib, eid, key, f"{old}, {value}" if old else value, source="talk")
            return
        old = e.get(key).strip()
        value = value.strip()
        if key in REPLACE_FIELDS or not old:
            self.store.set_field(eid, key, value, source="talk")
        elif value.lower() not in old.lower():
            sep = " " if old.endswith((".", "!", "?")) else ". "
            self.store.set_field(eid, key, old + sep + value, source="talk")

    def _keep_note(self, s: str) -> str:
        target = self.focus if self.focus and self.store.get(self.focus) else self.store.project_entity().id
        self.store.add_note(target, s.strip(), source="talk")
        return target

    def _n(self, eid: str) -> str:
        e = self.store.get(eid, with_fields=False)
        return e.label if e else "?"

    @staticmethod
    def _orig(full: str, lowered_piece: str | None) -> str:
        """Recover original casing for a substring found in the lowercased text."""
        if not lowered_piece:
            return ""
        i = full.lower().find(lowered_piece.lower())
        return full[i:i + len(lowered_piece)] if i >= 0 else lowered_piece

    @staticmethod
    def _orig_sentence(s: str) -> str:
        s = s.strip()
        if s and s[-1] not in ".!?":
            s += "."
        return s[:1].upper() + s[1:]

    @staticmethod
    def _clean_name(name: str) -> str:
        name = re.sub(r"^(?:the|a|an)\s+", "", name.strip(" .,!?"), flags=re.I)
        if name.islower():
            name = " ".join(w if w in ("of", "the", "and", "de", "von", "van") else w.capitalize()
                            for w in name.split())
        return name

    def _lookup(self, text: str, kind: str | None = None) -> str | None:
        """Find an entity by name/alias mentioned as (or at the start of) ``text``."""
        t = re.sub(r"^(?:the|a|an)\s+", "", text.lower().strip(" .,!?'\""))
        if not t:
            return None
        if t in SUBJ_PRON:
            return self.focus
        names = [(eid, k, n.lower()) for eid, k, n in self.store.all_names() if not kind or k == kind]
        for eid, k, n in sorted(names, key=lambda r: -len(r[2])):
            if t == n:
                return eid
        for eid, k, n in sorted(names, key=lambda r: -len(r[2])):
            if t.startswith(n + " ") or t == n.split()[0]:
                first_matches = [x for x in names if x[2].split()[0] == t]
                if t == n.split()[0] and len(first_matches) > 1:
                    continue
                return eid
        close = get_close_matches(t, [n for _, _, n in names], n=1, cutoff=0.85)
        if close:
            for eid, k, n in names:
                if n == close[0]:
                    return eid
        return None

    def _subject(self, phrase: str, sentence: str):
        """Resolve a subject phrase to an entity id, a _Pending for an unknown name, or None."""
        p = phrase.strip(" ,").lower()
        p = re.sub(r"^(?:and|also|so|then|well|oh|um|now)\s+", "", p)
        if p in SUBJ_PRON:
            return self.focus
        eid = self._lookup(p)
        if eid:
            return eid
        # "The Tavern is a building": a capitalized name after "the" is still a name
        orig = self._orig(sentence, phrase.strip(" ,"))
        if re.match(r"^[Tt]he\s+[A-Z]", orig):
            p = re.sub(r"^the\s+", "", p)
            phrase = re.sub(r"^[Tt]he\s+", "", phrase.strip(" ,"))
            eid = self._lookup(p)
            if eid:
                return eid
        words = p.split()
        if 1 <= len(words) <= 4 and not any(w in STOP for w in words) and all(re.fullmatch(r"[\w'’.-]+", w) for w in words):
            return _Pending("ask_kind", name=self._clean_name(self._orig(sentence, phrase.strip(" ,"))))
        return None

    def _sentence_subject(self, s: str):
        low = s.lower().strip()
        m = re.match(r"^(?:and\s+|also\s+)?(she|he|they|it)\b", low)
        if m:
            return self.focus
        m = re.match(r"^(?:and\s+|also\s+)?(?:her|his|their|its)\b", low)
        if m:
            return self.focus
        # longest known name at the start of the sentence
        names = sorted(self.store.all_names(), key=lambda r: -len(r[2]))
        for eid, _, n in names:
            nl = n.lower()
            if low.startswith(nl + " ") or low.startswith(nl + "'s ") or low.startswith(nl + "’s "):
                return eid
            first = nl.split()[0]
            if len(first) > 2 and (low.startswith(first + " ") or low.startswith(first + "'s ")):
                if sum(1 for _, _, x in names if x.lower().split()[0] == first) == 1:
                    return eid
        # an unknown name followed by a verb
        m = re.match(r"^([\w'’.-]+(?:\s+[\w'’.-]+){0,2}?)\s+(?:has|had|is|was|wants|loves|hates|can|fears|"
                     r"wears|likes|works|lives|speaks|seems|looks)\b", low)
        if m:
            r = self._subject(m.group(1), s)
            return r
        # any known name mentioned anywhere
        for eid, _, n in names:
            if re.search(rf"\b{re.escape(n.lower())}\b", low):
                return eid
        return None


    # ================================================================ local AI actions
    COMMAND_RE = re.compile(r"^\s*(?:undo|help|open|show|go to|tell me about|who is|what is|describe|read|"
                            r"interview|start|delete|remove|add|create|new|change|set|update)\b", re.I)

    def wants_rules(self, text: str) -> bool:
        """Commands and follow-up answers are handled by the fast built-in rules."""
        return bool(self.pending) or bool(self.COMMAND_RE.match(text))

    @staticmethod
    def _grounded(value: str, said: str) -> bool:
        """True if a value is (mostly) the writer's own words - the model may only file, not write."""
        words = re.findall(r"[a-z0-9']+", value.lower())
        if not words:
            return False
        said_words = set(re.findall(r"[a-z0-9']+", said.lower()))
        hits = sum(1 for w in words if w in said_words)
        return hits / len(words) >= 0.6

    def handle_actions(self, text: str, actions: list, spoken: bool = False) -> Reply | None:
        """Apply filing actions proposed by the local AI model. Returns None (so the caller
        falls back to the built-in rules) if nothing usable was proposed."""
        self._spoken = spoken
        if not actions:
            return None
        valid_kinds = set(self.kinds())
        msgs: list[str] = []
        changed: list[str] = []
        created_chars: list[str] = []
        loc_rel = {"lives in", "born in", "located in", "works in", "happens in", "based in"}
        for a in actions[:12]:
            if not isinstance(a, dict):
                continue
            op = a.get("op")
            name = (a.get("name") or "").strip()
            if op == "create":
                kind = a.get("kind") if a.get("kind") in valid_kinds else "character"
                if not name:
                    continue
                e = self.store.find_by_name(name, kind)
                if e:
                    self.focus = e.id
                    continue
                eid = self.store.create_entity(kind, self._clean_name(name), source="talk-ai")
                self.focus = eid
                changed.append(eid)
                msgs.append(f"Added {self._n(eid)} as a new {KINDS[kind][1].lower()}.")
                if kind == "character":
                    created_chars.append(eid)
            elif op == "set":
                eid = self._lookup(name) if name else self.focus
                field_ = re.sub(r"[^a-z_]", "", (a.get("field") or "").lower().replace(" ", "_"))
                value = (a.get("value") or "").strip()
                if not eid or not field_ or not value:
                    continue
                e = self.store.get(eid)
                if field_ == "tier":
                    tier = next((t for t, pat in TIER_WORDS.items() if re.search(rf"\b(?:{pat})\b", value.lower())),
                                value.lower() if value.lower() in ("primary", "secondary", "tertiary") else "")
                    if tier:
                        self.store.set_field(eid, "tier", tier, source="talk-ai")
                        msgs.append(f"{e.label} is a {tier_phrase(tier)}.")
                        changed.append(eid)
                        created_chars = [c for c in created_chars if c != eid]
                    continue
                rel_fields = {"location", "home", "residence", "lives_in", "birthplace", "parent", "parents",
                              "mentors", "siblings", "allies", "enemies", "friends", "relatives", "children",
                              "partners", "spouse"}
                if field_ in rel_fields or field_ in REL_WORDS or field_.rstrip("s") in REL_WORDS:
                    continue  # places and relationships are filed as links, not text fields
                if not self._grounded(value, text):
                    continue  # not the writer's words (often repeated from earlier): never file it
                before = e.get(field_)
                self._set_or_append(eid, field_, value)
                if self.store.get(eid).get(field_) == before:
                    continue  # already recorded
                self.focus = eid
                changed.append(eid)
                msgs.append(f"Added to {e.label}'s {label_for(self.lib, self.store, e.kind, field_).lower()}.")
            elif op == "link":
                a_id = self._lookup(name) if name else self.focus
                target = (a.get("target") or "").strip()
                rel = (a.get("relation") or "related to").strip().lower()
                rel = REL_WORDS.get(rel, rel)
                if not a_id or not target:
                    continue
                said = text.lower()
                tgt_words = [w for w in re.findall(r"[a-z']+", target.lower()) if len(w) > 2]
                b_known = self._lookup(target)
                b_name = self._n(b_known).lower() if b_known else target.lower()
                mentioned = any(w in said for w in tgt_words) or any(
                    w in said for w in re.findall(r"[a-z']+", b_name) if len(w) > 2)
                a_name = self._n(a_id).lower()
                a_mentioned = any(w in said for w in re.findall(r"[a-z']+", a_name) if len(w) > 2) or \
                    re.search(r"\b(she|he|they|her|his|their|him|them)\b", said) or a_id == self.focus
                if not mentioned or not a_mentioned:
                    continue  # a link repeated from earlier in the conversation
                b_id = b_known
                if not b_id:
                    kind = "location" if rel in loc_rel else "group" if rel in ("member of", "leader of") \
                        else "character"
                    b_id = self.store.create_entity(kind, self._clean_name(target), source="talk-ai")
                    msgs.append(f"Added {self._n(b_id)} as a new {KINDS[kind][1].lower()}.")
                a_e = self.store.get(a_id, with_fields=False)
                if rel == "located in" and a_e.kind == "location":
                    made = self.store.set_field(a_id, "parent", b_id, source="talk-ai")
                else:
                    made = self.store.link(a_id, b_id, rel, source="talk-ai")
                if not made:
                    continue  # already linked
                changed += [a_id, b_id]
                msgs.append(f"Noted: {self._n(b_id)} is {self._n(a_id)}'s {rel}." if rel not in loc_rel
                            else f"Noted that {self._n(a_id)} {rel_phrase(rel)} {self._n(b_id)}.")
                self.focus = a_id
            elif op in ("open", "describe"):
                eid = self._lookup(name) if name else self.focus
                if eid:
                    self.focus = eid
                    return self._log_reply(Reply(spoken_summary(self.store, eid),
                                                 open_entity=eid if op == "open" else None))
            elif op == "interview":
                eid = self._lookup(name) if name else None
                if eid:
                    e = self.store.get(eid)
                    return self._log_reply(Reply(f"Starting the interview for {e.label}.",
                                                 start_interview=(e.kind, eid)))
                kind = a.get("kind") if a.get("kind") in valid_kinds else ""
                if kind:
                    return self._log_reply(Reply(f"Starting a new {KINDS[kind][1].lower()} interview.",
                                                 start_interview=(kind, None)))
            elif op == "note":
                eid = self._lookup(name) if name else None
                target = eid or self._keep_note_target()
                self.store.add_note(target, self._orig_sentence(text), source="talk-ai")
                changed.append(target)
                msgs.append(f"I've kept that as a note on {self._n(target)}.")
            elif op == "ask" and a.get("value") and not msgs:
                q = str(a["value"]).strip()
                # ignore "questions" that just echo the writer's words back
                if q.endswith("?") and not self._grounded(q.rstrip("?"), text):
                    return self._log_reply(Reply(q[:300]))
        if not msgs:
            return None  # nothing usable: the built-in rules take over (and keep a note if needed)
        for eid in created_chars:
            e = self.store.get(eid)
            if e and not e.tier:
                self.pending = _Pending("ask_tier", entity_id=eid)
                msgs.append(f"Is {e.label} a main character, a secondary character, or a minor character?")
                break
        return self._log_reply(Reply(" ".join(dict.fromkeys(msgs)), changed=list(dict.fromkeys(changed))))

    def _keep_note_target(self) -> str:
        return self.focus if self.focus and self.store.get(self.focus) else self.store.project_entity().id

    def _log_reply(self, r: Reply) -> Reply:
        if r.text:
            self.store.log_conversation("pywriter", r.text)
        return r

    def known_names(self) -> list[str]:
        return sorted({n for _, _, n in self.store.all_names()}, key=str.lower)

    def recent(self) -> list[tuple[str, str]]:
        return [(row["speaker"], row["text"]) for row in self.store.conversation(10)]

    def focus_name(self) -> str:
        e = self.store.get(self.focus, with_fields=False) if self.focus else None
        return e.label if e else ""


# ==================================================================== utilities

def split_sentences(text: str) -> list[str]:
    text = text.strip()
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    out = []
    for p in parts:
        # dictation rarely has punctuation: split on " and she/he/they " as clause breaks
        for x in re.split(r"\s+(?:and|but)\s+(?=(?:she|he|they|it)\b)", p, flags=re.I):
            if not x.strip():
                continue
            # "She has red hair and lives in Port Vell" -> the second clause keeps the same subject
            clauses = re.split(rf",?\s+(?:and|but)\s+(?:also\s+)?(?=(?:{_CLAUSE_VERBS})\b)", x, flags=re.I)
            out.append(clauses[0])
            out.extend("they " + c for c in clauses[1:] if c.strip())
    return out


_CLAUSE_VERBS = (r"lives|lived|resides|resided|works|worked|comes|came|was born|belongs|belonged|"
                 r"leads|led|runs|ran|rules|ruled|is a member|was a member")


def tier_phrase(tier: str) -> str:
    return {"primary": "main character", "secondary": "secondary character",
            "tertiary": "minor character"}.get(tier, tier)


def rel_phrase(rel: str) -> str:
    return {"lives in": "lives in", "born in": "comes from", "works in": "works at",
            "located in": "is located in", "member of": "is a member of",
            "leader of": "leads", "employer": "works for"}.get(rel, rel)


def label_for(lib: Library, store: ProjectStore, kind: str, key: str) -> str:
    pack = lib.pack_for_kind(kind, store.project_type)
    if pack:
        q = pack.question(key)
        if q:
            return q.display_label
    return key.replace("_", " ")


HELP_TEXT = (
    "Just talk about your story and I'll file it. For example: 'Mara is the protagonist.' "
    "'She has red hair and lives in Port Vell.' 'Tomas is Mara's brother.' "
    "You can also say: add a character named Elda; open Port Vell; tell me about Mara; "
    "interview Tomas; change Mara's age to 34; delete Tomas; or undo."
)


def _rejoin(sentences: list[str]) -> str:
    """Join already-split sentences so split_sentences() splits them the same way again."""
    return " ".join(s.strip() if s.strip()[-1:] in ".!?" else s.strip() + "." for s in sentences if s.strip())
