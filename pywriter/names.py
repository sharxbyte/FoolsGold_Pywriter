"""Spelling help for names heard by speech recognition.

Speech recognition can't know how an invented name is spelled, and many real
names have several common spellings. When a name arrives by voice, PyWriter:

* accepts it silently if it's a common name with one usual spelling,
* offers the choices when several popular names sound the same
  (Catherine / Katherine / Kathryn), ranked by popularity,
* otherwise reads back how it was written and asks the writer to confirm or
  spell it out letter by letter.

"Sounds the same" uses a phonetic key (Metaphone via ``jellyfish``; Soundex if
that isn't installed). Popularity comes from public name lists downloaded once
from inside the app (Voice ▸ Download name lists):

* first names - US Social Security baby names, via the public mirror at
  github.com/hadley/data-baby-names (about 6,800 names, 1880-2008)
* surnames    - US Census Bureau 2000 surnames, via FiveThirtyEight's public data
  repository (github.com/fivethirtyeight/data, about 150,000 names)

Until those are downloaded, a small built-in list is used.
"""
from __future__ import annotations

import csv
import io
import re
import urllib.request
from functools import lru_cache
from pathlib import Path

from .paths import models_dir

FIRST_URL = "https://raw.githubusercontent.com/hadley/data-baby-names/master/baby-names.csv"
SURNAME_URL = "https://raw.githubusercontent.com/fivethirtyeight/data/master/most-common-name/surnames.csv"

# Small fallback used before the full lists are downloaded.
_FALLBACK_GROUPS = [
    ["Catherine", "Katherine", "Kathryn"], ["Jon", "John"], ["Sean", "Shaun", "Shawn"],
    ["Steven", "Stephen"], ["Ann", "Anne"], ["Sara", "Sarah"], ["Eric", "Erik"], ["Mark", "Marc"],
    ["Alan", "Allan", "Allen"], ["Brian", "Bryan"], ["Claire", "Clare"], ["Megan", "Meghan"],
    ["Rachel", "Rachael"], ["Zoe", "Zoey"], ["Aidan", "Aiden"], ["Caitlin", "Kaitlyn", "Katelyn"],
    ["Haley", "Hailey", "Hayley"], ["Sophia", "Sofia"], ["Isabel", "Isabelle"], ["Smith", "Smyth"],
    ["Reid", "Reed"], ["Clark", "Clarke"], ["Thompson", "Thomson"],
]
_FALLBACK_COMMON = set("""
james robert william david richard joseph thomas charles daniel paul andrew george henry peter jack
mary patricia jennifer linda susan emma olivia grace lily anna laura helen alice rose kate jane tom sam
""".split())


def _data_files() -> tuple[Path, Path]:
    """Where downloaded/imported lists are written (the user's data folder)."""
    d = models_dir()
    return d / "names_first.tsv", d / "names_last.tsv"


def _read_files() -> list[Path]:
    """Lists to load: the user's own copy if present, otherwise the copy bundled with the app."""
    from .paths import resource_dir
    out = []
    for user_copy in _data_files():
        bundled = resource_dir() / "data" / user_copy.name
        if user_copy.exists():
            out.append(user_copy)
        elif bundled.exists():
            out.append(bundled)
    return out


def name_lists_installed() -> bool:
    return len(_read_files()) == 2


# --------------------------------------------------------------- phonetics

def _soundex(word: str) -> str:
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"),
             "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    out, last = w[0].upper(), codes.get(w[0], "")
    for c in w[1:]:
        code = codes.get(c, "")
        if code and code != last:
            out += code
        if c not in "hw":
            last = code
    return (out + "000")[:4]


def phonetic(word: str) -> str:
    try:
        import jellyfish  # type: ignore
        return jellyfish.metaphone(word)
    except Exception:
        return _soundex(word)


# --------------------------------------------------------------- data

class _NameIndex:
    def __init__(self):
        self.weight: dict[str, tuple[str, float]] = {}   # lower -> (Proper, popularity)
        self.by_key: dict[str, list[tuple[float, str]]] = {}

    def add(self, name: str, weight: float) -> None:
        low = name.lower()
        if low in self.weight:
            proper, w = self.weight[low]
            self.weight[low] = (proper, w + weight)
        else:
            self.weight[low] = (name, weight)

    def build(self) -> None:
        self.by_key.clear()
        for low, (proper, w) in self.weight.items():
            self.by_key.setdefault(phonetic(proper), []).append((w, proper))
        for v in self.by_key.values():
            v.sort(reverse=True)


@lru_cache(maxsize=1)
def _index() -> _NameIndex:
    idx = _NameIndex()
    loaded = False
    for path in _read_files():
        if path.exists():
            loaded = True
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) == 2:
                        try:
                            idx.add(parts[0], float(parts[1]))
                        except ValueError:
                            pass
    if not loaded:
        for g in _FALLBACK_GROUPS:
            for i, n in enumerate(g):
                idx.add(n, 100.0 / (i + 1))
        for n in _FALLBACK_COMMON:
            idx.add(n.capitalize(), 100.0)
    idx.build()
    return idx


def reload() -> None:
    _index.cache_clear()


TITLES = set("""captain capt doctor dr mr mrs ms miss mister madam sir dame lord lady king queen prince princess
duke duchess earl count countess baron baroness professor prof general colonel major lieutenant sergeant
corporal private admiral commander officer detective inspector chief father mother sister brother saint st
uncle aunt grandma grandpa granny nana elder master mistress reverend rev bishop pope emperor empress""".split())


def _similar(a: str, b: str) -> float:
    try:
        import jellyfish  # type: ignore
        return jellyfish.jaro_winkler_similarity(a.lower(), b.lower())
    except Exception:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def sound_alikes(word: str, limit: int = 4, min_share: float = 0.08, min_similarity: float = 0.84) -> list[str]:
    """Popular names that sound like ``word`` and are spelled similarly (including the
    word itself if known), most popular first. Much rarer matches are dropped."""
    idx = _index()
    matches = [(w, n) for w, n in idx.by_key.get(phonetic(word), [])
               if _similar(word, n) >= min_similarity]
    if not matches:
        return []
    top = matches[0][0]
    out = [n for w, n in matches if w >= top * min_share][:limit]
    known = idx.weight.get(word.lower())
    if known and known[0] not in out:
        out.append(known[0])
    return out


def needs_spelling_check(name: str, person: bool = True) -> tuple[str, list[str]] | None:
    """Return (reason, choices) when a spoken name should be confirmed, else None.

    reason is 'variants' (choices are full-name alternatives) or 'unknown'."""
    words = [w for w in re.findall(r"[A-Za-z'’-]+", name)
             if w.lower() not in ("the", "of", "and") and w.lower() not in TITLES]
    if not words:
        return None
    if not person:  # places, groups, items: just read back the spelling to confirm
        return "unknown", []
    idx = _index()
    all_known = True
    for w in words:
        alikes = sound_alikes(w)
        if len(alikes) > 1:
            choices = []
            for alt in alikes:
                full = re.sub(rf"\b{re.escape(w)}\b", alt, name, count=1)
                if full not in choices:
                    choices.append(full)
            if len(choices) > 1:
                return "variants", choices
        if w.lower() not in idx.weight:
            all_known = False
    return None if all_known else ("unknown", [])


def spell_out(name: str) -> str:
    """'Mara Venn' -> 'M, A, R, A. Then V, E, N, N.' for reading aloud."""
    parts = [", ".join(c.upper() for c in w if c.isalnum()) for w in name.split()]
    return ". Then ".join(parts) + "."


# spoken letter names -> letters (speech recognizers often return these words)
_LETTERS = {
    "a": "a", "ay": "a", "b": "b", "bee": "b", "be": "b", "c": "c", "see": "c", "sea": "c", "cee": "c",
    "d": "d", "dee": "d", "e": "e", "ee": "e", "f": "f", "ef": "f", "eff": "f", "g": "g", "gee": "g",
    "h": "h", "aitch": "h", "haitch": "h", "i": "i", "eye": "i", "j": "j", "jay": "j", "k": "k",
    "kay": "k", "l": "l", "el": "l", "ell": "l", "m": "m", "em": "m", "n": "n", "en": "n", "o": "o",
    "oh": "o", "owe": "o", "p": "p", "pee": "p", "pea": "p", "q": "q", "queue": "q", "cue": "q", "r": "r",
    "are": "r", "ar": "r", "s": "s", "es": "s", "ess": "s", "t": "t", "tee": "t", "tea": "t", "u": "u",
    "you": "u", "v": "v", "vee": "v", "w": "w", "x": "x", "ex": "x", "y": "y", "why": "y", "z": "z",
    "zee": "z", "zed": "z",
    "alpha": "a", "bravo": "b", "charlie": "c", "delta": "d", "echo": "e", "foxtrot": "f", "golf": "g",
    "hotel": "h", "india": "i", "juliet": "j", "kilo": "k", "lima": "l", "mike": "m", "november": "n",
    "oscar": "o", "papa": "p", "quebec": "q", "romeo": "r", "sierra": "s", "tango": "t", "uniform": "u",
    "victor": "v", "whiskey": "w", "xray": "x", "yankee": "y", "zulu": "z",
}
_SPACE_WORDS = {"space", "then", "next", "new", "word"}


def parse_spelling(text: str) -> str | None:
    """'m a r a space v e n n' / 'M-A-R-A V-E-N-N' / 'em ay are ay' -> 'Mara Venn'.
    Returns None if the text doesn't look like spelling."""
    t = text.lower().replace("double you", "w").replace("double u", "w").replace("x-ray", "xray")
    toks = re.sub(r"[-,.]", " ", t).split()
    words, cur, letters, i = [], "", 0, 0
    while i < len(toks):
        tok = toks[i]
        if tok in _SPACE_WORDS:
            if cur:
                words.append(cur)
                cur = ""
        elif tok == "apostrophe":
            cur += "'"
        elif tok in ("hyphen", "dash"):
            cur += "-"
        elif tok == "double" and i + 1 < len(toks) and toks[i + 1] in _LETTERS:
            cur += _LETTERS[toks[i + 1]] * 2
            letters += 2
            i += 1
        elif tok in _LETTERS:
            cur += _LETTERS[tok]
            letters += 1
        elif tok in ("capital", "uppercase", "lowercase", "small"):
            pass
        else:
            return None  # an ordinary word, so this isn't spelling
        i += 1
    if cur:
        words.append(cur)
    if letters < 2:
        return None
    return " ".join(w[:1].upper() + w[1:] for w in words)


# --------------------------------------------------------------- download

def download_name_lists(progress=None) -> None:
    """Download and compact the public name lists. Raises on failure."""
    first_path, last_path = _data_files()

    def fetch(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "PyWriter"})
        with urllib.request.urlopen(req, timeout=120) as r:
            total = int(r.headers.get("Content-Length") or 0)
            buf, done = bytearray(), 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                buf += chunk
                done += len(chunk)
                if progress:
                    progress(url, done, total)
            return bytes(buf)

    # first names: sum the yearly popularity of each name
    data = fetch(FIRST_URL).decode("utf-8")
    totals: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(data)):
        totals[row["name"]] = totals.get(row["name"], 0.0) + float(row["percent"] or 0)
    with first_path.open("w", encoding="utf-8") as fh:
        for n, w in sorted(totals.items(), key=lambda kv: -kv[1]):
            fh.write(f"{n}\t{w * 1000:.3f}\n")

    # surnames: CSV with name,rank,count,...
    rows = csv.DictReader(io.StringIO(fetch(SURNAME_URL).decode("utf-8", errors="replace")))
    with last_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            try:
                name, count = row["name"], int(row["count"])
            except (ValueError, KeyError, TypeError):
                continue
            if count < 100 or not name.isalpha():
                continue
            fh.write(f"{name.capitalize()}\t{count / 1000:.3f}\n")
    reload()


def import_ssa_zip(path) -> int:
    """Import first names from the official SSA file (https://www.ssa.gov/oact/babynames/names.zip,
    downloaded by the writer in a browser). Returns the number of names."""
    import zipfile
    totals: dict[str, float] = {}
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            if not re.match(r"yob\d{4}\.txt$", member.split("/")[-1]):
                continue
            for line in z.open(member).read().decode("utf-8", errors="replace").splitlines():
                parts = line.split(",")
                if len(parts) == 3:
                    try:
                        totals[parts[0]] = totals.get(parts[0], 0.0) + int(parts[2])
                    except ValueError:
                        pass
    if not totals:
        raise ValueError("That zip doesn't contain SSA yobYYYY.txt files.")
    first_path, _ = _data_files()
    with first_path.open("w", encoding="utf-8") as fh:
        for n, c in sorted(totals.items(), key=lambda kv: -kv[1]):
            if c >= 50:
                fh.write(f"{n}\t{c / 1000:.3f}\n")
    reload()
    return len(totals)
