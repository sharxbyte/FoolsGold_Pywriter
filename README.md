# FoolsGold PyWriter

An offline, voice-friendly interviewer and story bible for writers.

PyWriter interviews you about your project one question at a time. That covers characters, places, groups, plot, timeline, themes, sources and more. It files every answer into a linked, searchable story bible. You can type, dictate, or go completely hands-free: it reads each question aloud and records your spoken answer.

**It runs entirely on your computer and does not use AI to write anything.** Speech recognition, text-to-speech and the Talk-mode interpreter only *understand and organize* what you say. The words are yours.

---

## Features

| | |
|---|---|
| **Guided Story Interview** | Walks through the whole project: kickoff → world and scope → characters → places → groups → plot → timeline → items → themes. After each interview it asks "Is there another…?" |
| **Branching interviews** | Early answers decide later questions. A single linear timeline hides the flashback and time-travel questions. A story set in one town never asks about star systems. A minor character gets a short sketch; a main character gets the full ~80-question profile. |
| **Résumé-first character interviews** | Name and role, then qualifications and experience, then first impressions (height, build, hair, voice, clothing…), then personality, inner life, background, relationships and arc. |
| **Location levels** | Every place has a level (room → building → … → planet → galaxy → dimension → timeline) and a parent place, so the setting forms a tree. "Are there notable places inside?" leads straight into a sub-location interview. |
| **Linked story bible** | Names you give in answers become linked entries automatically, e.g. "Who are her siblings?" → *Tomas Venn* is created and linked. Hover any linked name to see a short bio; click it to open the full sheet. |
| **Entry pages** | Double-click any entry. **Sheet** is the read view with links; **Edit** shows every question as an editable field. Each page also has **Re-interview** (answers pre-filled), connections, places inside, mentions and notes. |
| **Talk mode** (Ctrl+T) | Just describe your story: "Mara is the protagonist. She has red hair and lives in Port Vell. Tomas is Mara's older brother." PyWriter files it. It asks before creating anything it doesn't recognize, and offers to start an interview. |
| **Narration mode** (F5) | Hands-free interviews. The question is read aloud, then PyWriter listens. Say "next question, confirm" to move on. After 10 seconds of silence it asks whether you're finished; after another silence it pauses. |
| **Name spelling** | When a name comes in by voice, PyWriter checks it. Names with several common spellings (Catherine / Katherine / Kathryn) are offered as choices. Invented names are read back letter by letter, and you can spell a correction: "M, A, R, A, space, V, E, N, N". |
| **Natural voices** | Windows voices (modern WinRT or classic SAPI), or optional **Piper** neural voices that sound far more natural and still run offline. |
| **Map** | A relationship graph with drag-to-arrange nodes (positions are saved), colors per kind of entry, and dashed lines for place containment. |
| **Manuscript** | Chapters and scenes with dictation, read-aloud, word count, and links to the people and places mentioned in each scene. |
| **History and backups** | Every change is recorded and can be reverted individually. Full snapshots are taken on open, on close, after interviews, and every 5 minutes. Restore any snapshot; the current state is snapshotted first, so a restore can be undone. |
| **Readable export** | `<Title> - Story Bible.md` is rewritten on every save. Each entry carries the same ID as the database (CHR-0001, LOC-0003…). |
| **Accessibility** | Large question text, light, dark and high-contrast themes, adjustable text size, keyboard shortcuts for everything, and full voice control of interviews. |

---

## Install and run

Requires **Python 3.10+** on Windows, macOS or Linux.

```bash
cd PyWriter
python -m pip install -r requirements.txt
python main.py
```

On first launch, choose a project type (Fiction, Biography, Non-Fiction) and a working title. The title becomes the project folder (characters that aren't allowed in folder names are blocked as you type):

```
Documents/PyWriter Projects/<Title>/
    <Title>.pwdb                 ← the project database (SQLite)
    <Title> - Story Bible.md     ← readable export, regenerated on save
    <Title> - Manuscript.md      ← manuscript export
    backups/                     ← timestamped full snapshots
```

### Turning on speech recognition

Go to **Voice ▸ Download speech model…**. This is a one-time download from alphacephei.com; after that, recognition is fully offline. There are two choices:

- *Small English model* (~40 MB): fast and works on any computer.
- *Larger English model* (~128 MB): noticeably more accurate.

Models are stored in your user data folder (see *Where things are stored*).

### Getting more natural voices

Go to **Tools ▸ Settings ▸ Reading voice**:

- **Engine:** choose *Windows modern voices*, *Windows classic voices*, or *Natural neural voices (Piper)*.
- **Get natural voices…** downloads Piper voices (about 60–110 MB each) from the public [Rhasspy Piper voice library](https://huggingface.co/rhasspy/piper-voices). Try *en_US-lessac*, *en_US-amy*, *en_US-ryan-high* or *en_GB-cori-high*.
- **Speed**, **pitch** and **volume** apply to every engine. Use **Test voice** to hear the result.

To add more Windows voices, go to Windows **Settings ▸ Time & language ▸ Speech ▸ Manage voices ▸ Add voices**.

---

## Using other languages

PyWriter's three language-dependent parts can each be switched separately.

### 1. Speech recognition (what PyWriter hears)

1. Download a Vosk model for your language from <https://alphacephei.com/vosk/models>. There are 20+ languages, including Spanish, French, German, Italian, Portuguese, Russian, Chinese, Japanese and Hindi. The "small" models (40–50 MB) are a good start.
2. Unzip it into the **models** folder, so you end up with e.g. `…/PyWriter/models/vosk-model-small-es-0.42/`.
3. In **Settings ▸ Listening ▸ Speech model / language**, pick that folder. Every installed model appears in the list, so you can switch between languages.

### 2. Reading voice (what PyWriter says)

- **Windows voices:** in Windows **Settings ▸ Time & language ▸ Language & region**, add the language and include *Text-to-speech*, or use **Speech ▸ Add voices**. Restart PyWriter, and the new voices appear under the Windows engines.
- **Piper voices:** browse <https://huggingface.co/rhasspy/piper-voices>. Download both files for a voice, the `.onnx` and the `.onnx.json` (e.g. `es/es_ES/davefx/medium/es_ES-davefx-medium.onnx` plus its `.json`). Put both in `…/PyWriter/models/piper/`, then choose the voice under **Engine: Natural neural voices**.
- **macOS / Linux:** voices come from the system (AVSpeech on macOS; speech-dispatcher or espeak on Linux). Install voices there.

### 3. Interview questions (what PyWriter asks)

Questions live in plain YAML files in [`pywriter/packs/`](pywriter/packs/). To translate:

1. Copy a pack, e.g. `10_character.yaml` → `10_character_es.yaml`.
2. Change `pack:` to a new id (e.g. `character_es`). Translate `title`, `intro`, `outro`, `another`, every section `title`, and every question's `ask` and `label`, plus each option's `label`.
3. **Don't change** `key:`, option `value:`, `type:`, `kind:`, `relation:` or the `when:` conditions. Those keep the database, links and branching working.
4. Set `project_types:` so the translated pack is used. Make sure only one pack per kind is active for a project type, either by removing the English one from that type or by moving it out of the folder.
5. Restart PyWriter. Any errors in a pack are shown at start-up and in **Tools ▸ Diagnostics**.

> **Talk mode** understands English sentence patterns only. In other languages, use interviews; dictation and read-aloud work in any language with installed models and voices.

### Name lists for spelling checks

The bundled name lists are US-centric:

- First names come from Social Security baby names.
- Surnames come from Census surnames.

For the official, larger first-name list, download <https://www.ssa.gov/oact/babynames/names.zip> in your browser, then use **Settings ▸ Import SSA names.zip…**. Lists for other countries can be dropped into the models folder as `names_first.tsv` / `names_last.tsv`. Each line holds a name, a tab, and a popularity number.

---

## Voice commands

**During interviews (Narration mode, F5)**

| Say | Does |
|---|---|
| "next question, confirm" (also *finished / continue / proceed* + *confirm / yes*) | Save and move on |
| "next question" | Asks you to confirm first |
| "go back" | Previous question |
| "repeat the question" | Reads it again |
| "read my answer" | Reads back what you've said |
| "skip question" | Skips it |
| "scratch that" | Removes the last thing you said |
| "stop listening" | Pauses |
| "end interview" | Saves and finishes |

For choice questions, just say the option ("main character", "yes"). PyWriter confirms what it heard.

**While dictating:** say "comma", "full stop", "question mark", "new line" or "new paragraph".

**In Talk mode:**

- "open Port Vell"
- "tell me about Mara"
- "interview Tomas"
- "add a character named Elda"
- "change Mara's age to 34"
- "delete Tomas"
- "undo"

**Keyboard:**

| Key | Does |
|---|---|
| Ctrl+Enter | Next question |
| Alt+Left | Back |
| F2 / F3 | Read question / answer |
| F4 | Dictate |
| F5 | Narration mode |
| F11 | Distraction-free mode |
| Ctrl+T | Talk mode |
| Ctrl+G | Guided interview |
| Ctrl+H | History |

---

## How saving works

- Every answer and edit is written to the project database immediately. There's no Save button to forget.
- Every change is recorded with its old and new value in the database's change log. **Tools ▸ History** lets you revert any single change or restore deleted entries.
- **Snapshots** are complete copies of the project in `backups/`. They're taken when you open or close a project, after each interview, and every few minutes while you work (only when something changed). Snapshots are never modified. By default all are kept; this is adjustable in Settings.
- The **Story Bible** Markdown file is regenerated after changes, when you switch tabs, and when you close.
- **File ▸ Import from PyWriter v10/v11** brings in projects from the old Tkinter version. Old answers are matched to the new questions where it's clear; anything uncertain is kept under "Imported from v11", so nothing is lost.

## Where things are stored

| | |
|---|---|
| Projects | `Documents/PyWriter Projects/` (changeable when creating a project) |
| Speech models, Piper voices, name lists | Windows `%APPDATA%\PyWriter\models\` · macOS `~/Library/Application Support/PyWriter/models/` · Linux `~/.local/share/PyWriter/models/` |
| Settings | Qt settings (registry on Windows) |
| Error log | `%APPDATA%\PyWriter\error.log` (same folder as models on other systems) |

---

## Building a standalone app

```bash
python -m pip install pyinstaller
python build.py
```

This produces `dist/FoolsGoldPyWriter/`. On Windows the output is `FoolsGoldPyWriter.exe`. Build on each operating system you want to support.

## Project layout

```
PyWriter/
  main.py                  entry point
  build.py                 PyInstaller build script
  pywriter/
    store.py               SQLite project database + change log
    backup.py              rolling snapshots / restore
    library.py             YAML question packs + condition language
    engine.py              interview engine (branching, linking, stubs)
    nlu.py                 Talk-mode interpreter (rule-based)
    names.py               name spelling checks
    voice.py               text-to-speech, speech-to-text, voice commands
    export.py, importer.py, summary.py
    packs/                 question packs (YAML) + guided flows
    data/                  bundled name lists
    resources/             icon, splash
    ui/                    Qt windows
```

## Credits and data sources

- [Qt for Python (PySide6)](https://www.qt.io/qt-for-python): LGPL
- [Vosk](https://alphacephei.com/vosk/) speech recognition: Apache 2.0
- [Piper](https://github.com/rhasspy/piper) neural text-to-speech: MIT. Voices have individual licenses; see each voice's model card.
- First names: US Social Security Administration baby names (public domain), via [hadley/data-baby-names](https://github.com/hadley/data-baby-names)
- Surnames: US Census Bureau 2000 surnames (public domain), via [FiveThirtyEight's data repository](https://github.com/fivethirtyeight/data/tree/master/most-common-name) (CC BY 4.0)
- [jellyfish](https://github.com/jamesturk/jellyfish) (phonetic matching): MIT
