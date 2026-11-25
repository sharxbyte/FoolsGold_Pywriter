# FoolsGold PyWriter

**An offline, voice-friendly interviewer and story bible for writers.**

PyWriter asks you about your project one question at a time: your characters, places, groups, plot, timeline, themes and sources. It files every answer into a linked, searchable story bible. You can type, dictate, or work completely hands-free, with each question read aloud and your spoken answer recorded.

> **PyWriter does not write for you.** Speech recognition, read-aloud and the Talk-mode interpreter only *understand and organize* what you say. Every word in your story bible is yours. Everything runs on your own computer, and nothing is uploaded.

**Status:** 1.0, the first public test release. Please report anything that breaks (see [Reporting problems](#reporting-problems)).

---

## Contents

- [Download and run (Windows)](#download-and-run-windows)
- [Run from source (Windows, macOS, Linux)](#run-from-source-windows-macos-linux)
- [Your first ten minutes](#your-first-ten-minutes)
- [Features](#features)
- [Voice setup](#voice-setup)
- [Voice commands and keyboard shortcuts](#voice-commands-and-keyboard-shortcuts)
- [How saving works](#how-saving-works)
- [Where things are stored](#where-things-are-stored)
- [Using other languages](#using-other-languages)
- [Downloads, privacy and training data](#downloads-privacy-and-training-data)
- [Building the Windows app yourself](#building-the-windows-app-yourself)
- [Project layout](#project-layout)
- [Reporting problems](#reporting-problems)
- [Credits](#credits)

---

## Download and run (Windows)

1. Go to the [Releases page](https://github.com/sharxbyte/FoolsGold_Pywriter/releases) and download `FoolsGoldPyWriter-<version>-windows-x64.zip`.
2. Unzip it anywhere, e.g. `Documents\FoolsGoldPyWriter\`. **Keep the folder together:** the `.exe` needs the `_internal` folder next to it.
3. Double-click **`FoolsGoldPyWriter.exe`**.

**Windows SmartScreen:** the app isn't code-signed yet, so Windows may show *"Windows protected your PC"*. Click **More info ▸ Run anyway**. You only need to do this once.

The download has no speech or AI models in it, so it stays small. PyWriter offers to download them from inside the app when you want them (see [Voice setup](#voice-setup)).

To update, unzip the new version over the old folder, or into a new folder. Your projects and settings are stored elsewhere and aren't touched.

---

## Run from source (Windows, macOS, Linux)

Run from source if you're on macOS or Linux, if you'd rather not run a downloaded `.exe`, or if you want to change the question packs or code.

### Requirements

- **Python 3.10 – 3.12** (3.11 recommended). On Windows, tick *"Add python.exe to PATH"* when installing.
- **Git** (optional; you can also download the source as a ZIP from GitHub).

### 1. Get the code

```bash
git clone https://github.com/sharxbyte/FoolsGold_Pywriter.git
cd FoolsGold_Pywriter
```

### 2. Create a virtual environment (recommended)

**Windows (PowerShell or Command Prompt):**
```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the dependencies

**Full install**, with every feature:
```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**Minimal install**, if the full install fails (usually because `llama-cpp-python` has to compile). This gives you interviews, Talk mode, speech recognition and read-aloud without the optional AI assistant:
```bash
python -m pip install PySide6 PyYAML numpy vosk sounddevice soundfile jellyfish networkx pyttsx3
```

**Optional extras:**

| Package | Adds | Notes |
|---|---|---|
| `piper-tts` | Natural neural voices | Recommended; prebuilt wheels on all three systems |
| `llama-cpp-python` | Optional local AI assistant for Talk mode | Prebuilt CPU wheels: `pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu` |
| `pycaw` | Uses Windows' *default communication device* for mic and speaker | Windows only; installed automatically by requirements.txt |

### 4. Run it

```bash
python main.py
```

Options:

```bash
python main.py "path/to/My Novel.pwdb"   # open a specific project
python main.py --no-splash               # skip the splash screen
python main.py --no-guide                # don't offer the guided interview on start-up
```

### Linux notes

Qt, audio and speech need a few system packages. On Debian or Ubuntu:

```bash
sudo apt install python3-venv libportaudio2 libxcb-cursor0 libxkbcommon-x11-0 \
                 speech-dispatcher espeak-ng libegl1
```

- `libportaudio2` is needed for the microphone (`sounddevice`).
- `libxcb-cursor0` is needed for Qt 6 on X11. If the window won't open, run with `QT_DEBUG_PLUGINS=1 python main.py` to see what's missing.
- `speech-dispatcher` / `espeak-ng` provide the system read-aloud voices. Piper voices sound much better and need no system packages.
- On Wayland, Qt normally works as-is. If it doesn't, try `QT_QPA_PLATFORM=xcb python main.py`.
- Fedora: `sudo dnf install portaudio xcb-util-cursor speech-dispatcher espeak-ng`.

To get a launcher icon, create `~/.local/share/applications/foolsgold-pywriter.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=FoolsGold PyWriter
Exec=/path/to/FoolsGold_Pywriter/.venv/bin/python /path/to/FoolsGold_Pywriter/main.py
Icon=/path/to/FoolsGold_Pywriter/pywriter/resources/splash.png
Categories=Office;
```

### macOS notes

- Allow microphone access when macOS asks. If you missed the prompt, go to **System Settings ▸ Privacy & Security ▸ Microphone** and enable your terminal app.
- Read-aloud uses the system voices. Add more in **System Settings ▸ Accessibility ▸ Spoken Content**.

---

## Your first ten minutes

1. **Create a project.** Pick a project type (**Fiction**, **Biography** or **Non-Fiction**) and type a working title. The title becomes the project's folder name. Characters that aren't allowed in folder names (`\ / : * ? " < > |`) are blocked as you type.
2. **Start the Guided Story Interview** (offered straight away, or **Ctrl+G**). It walks through the whole project in a sensible order. For fiction, that's the big picture, then world and scale, then characters, places, groups, plot, timeline, items and themes. Answer what you can and skip the rest. You can stop at any time; everything is already saved.
3. **Browse what you've built.** The left sidebar lists every kind of entry. **Double-click** any entry to open its page. Hover over a linked name anywhere to see a short summary, and click it to jump to that entry.
4. **Try Talk mode** (**Ctrl+T**). Type or say something like *"Mara is the protagonist. She has red hair and lives in Port Vell."* PyWriter files it for you: Mara becomes a main character with red hair, and Port Vell becomes a linked place.
5. **Turn on voice** when you're ready. Go to **Voice ▸ Download speech model…** (one-time, about 40 MB), then press **F5** in any interview for hands-free narration mode.

---

## Features

### Interviews that adapt to your answers

- **Branching:** early answers decide which questions come later.
  - Say the story follows a single linear timeline, and the flashback and time-travel questions are skipped.
  - Set it in one town, and you're never asked about star systems.
  - A minor character gets a short sketch; a main character gets the full profile of about 80 questions.
- **Résumé-first character interviews:** questions come in the order you'd learn about someone you're interviewing for a job:
  1. Name, role, qualifications and experience
  2. First impressions: height, build, hair, voice, clothing and demeanour
  3. Personality and inner life
  4. Background
  5. Relationships and arc
- **Complete-sentence questions** make the interview feel like a conversation, and they read aloud naturally.
- **Location levels:** every place has a level and a parent place, so your setting forms a tree. The levels run room → building → district → settlement → region → country → planet → star system → galaxy → dimension → timeline. Answering "yes" to *"Are there notable places inside?"* leads straight into a sub-location interview.
- **"Is there another…?"** follows each interview, so you can add characters or places back-to-back.
- **Re-interview** from any entry's page. Every question comes back with your earlier answers filled in, ready to edit.

### A linked story bible

- **Automatic linking:** names you give in answers become linked entries. For example, *"Who are her siblings?" → "Tomas Venn"* creates Tomas, linked to her as a sibling. Duplicates are avoided: if Tomas already exists, the existing entry is used.
- **Entry pages:** each page has three parts:
  - **Sheet:** a readable summary with links.
  - **Edit:** every question as an editable field.
  - Connections, places inside, mentions elsewhere, and notes.
- **Readable IDs** such as CHR-0001, LOC-0003 and EVT-0002 are the same in the app, the database and the exported Story Bible.
- **Map:** a relationship graph. Drag nodes to arrange them (positions are saved). Colours show each kind of entry, and dashed lines show which places are inside which.
- **Manuscript:** chapters and scenes with dictation, read-aloud, word count, and links to the people and places mentioned in each scene.

### Talk mode (Ctrl+T)

Describe your story in plain sentences, typed or spoken. PyWriter pulls out facts (appearance, age, occupation…) and relationships (sibling of, lives in, works for, member of…). If it meets a name it doesn't know, it asks whether that's a character, place, group, item or event. Anything it can't file is kept as a note, so nothing you say is lost.

You can also give it commands: *open Port Vell · tell me about Mara · interview Tomas · add a character named Elda · change Mara's age to 34 · delete Tomas · undo*.

Talk mode uses built-in language rules. An **optional** small AI model that runs on your computer can be switched on to understand freer phrasing (see [Downloads, privacy and training data](#downloads-privacy-and-training-data)).

### Voice

- **Read aloud:** read the question (F2), read your answer (F3), or both.
- **Dictation** into any text box (F4). Say "comma", "full stop", "question mark", "new line" or "new paragraph" for punctuation.
- **Narration mode** (F5) runs interviews hands-free.
  - PyWriter reads the question, then listens.
  - Say *"next question, confirm"* to move on.
  - After 10 seconds of silence it asks whether you're finished. After another silence it pauses.
- **Name spelling:** spoken names are checked.
  - Names with several common spellings (Catherine / Katherine) are offered as choices.
  - Invented names are spelled back letter by letter. You can spell a correction aloud: *"M, A, R, A, space, V, E, N, N"*.
- **Voices:** choose between Windows modern or classic voices and optional **Piper** neural voices, which sound far more natural and still run offline. Speed, pitch and volume are adjustable.
- **Voice transcript:** each project keeps a timestamped, append-only text record of everything heard, said and answered. Audio recording is optional and off by default.

### Safety nets

- **Autosave:** there's no Save button. Changes are saved as you type, when you finish an interview, when you switch tabs, and when you close the window.
- **History** (Ctrl+H): every change is kept with its old and new value. You can revert any single change or bring back deleted entries.
- **Snapshots:** complete copies of the project are taken on open, on close, after each interview, and every 5 minutes while you work. Snapshots are never edited afterwards. Restoring one takes a snapshot of the current state first, so a restore can be undone too.
- **Story Bible export:** `<Title> - Story Bible.md` is a plain-text Markdown copy of everything. It's rewritten automatically and can be opened in any editor.
- **Import:** **File ▸ Import from PyWriter v10/v11** brings in projects from the old Tkinter version. Anything that doesn't match a new question cleanly is kept under "Imported from v11".

### Accessibility

Large question text; light, dark and high-contrast themes; adjustable text size (Ctrl+= / Ctrl+-); distraction-free full screen (F11); keyboard shortcuts for everything; and full voice control of interviews.

---

## Voice setup

### Speech recognition (so PyWriter can hear you)

Go to **Voice ▸ Download speech model…**. This is a one-time download, and after it recognition works fully offline.

- *Small English model* (~40 MB): fast, and works on any computer.
- *Larger English model* (~128 MB): noticeably more accurate.

### Natural voices (so PyWriter sounds good)

Go to **Tools ▸ Settings ▸ Reading voice**:

- **Engine:** *Windows modern voices*, *Windows classic voices*, or *Natural neural voices (Piper)*.
- **Get natural voices…** downloads Piper voices (60–110 MB each). The list shows where each voice's training recordings came from.
- **Test voice** plays a sample with your speed, pitch and volume settings.

To add more Windows voices, go to **Windows Settings ▸ Time & language ▸ Speech ▸ Manage voices ▸ Add voices**.

### Microphone and speaker

PyWriter finds your audio devices each time it starts, so it works on whichever computer it runs on.

- **Windows** uses your *default communication device*: the mic and speaker Windows uses for calls (**Sound settings ▸ More sound settings**).
- **Linux** follows the PipeWire/PulseAudio default.
- **macOS** uses the system default.

To choose specific devices, go to **Settings ▸ Listening ▸ Microphone** and **Settings ▸ Reading voice ▸ Speaker**. Click **Refresh devices** after plugging something in. Devices are remembered by name. If a chosen device is unplugged, PyWriter falls back to the default.

> *Modern Windows voices* always play on the system default speaker. If you choose a different speaker, use the classic or Piper voices.

**Mic processing**, under **Settings ▸ Listening**:

| Option | What it does | Default |
|---|---|---|
| Compressor | Evens out loud and quiet speech | On |
| Background noise reduction | Removes steady fan, hum or hiss. Helps in noisy rooms; can slightly reduce accuracy in quiet ones | Off |
| Noise gate | Mutes the mic between words. Can clip very quiet words | Off |

---

## Voice commands and keyboard shortcuts

**In interviews (narration mode, F5):**

| Say | Does |
|---|---|
| "next question, confirm" (also *finished / done / continue / proceed / move on* + *confirm / yes*) | Save and go to the next question |
| "next question" alone | Asks you to confirm first |
| "go back" / "previous question" | Previous question |
| "repeat the question" | Reads it again |
| "read my answer" / "what did I say" | Reads back your answer |
| "skip question" | Skips it |
| "scratch that" | Removes the last thing you said |
| "stop listening" / "pause narration" | Pauses |
| "end interview" / "save and close" | Saves and finishes |

For choice questions, just say the option (*"main character"*, *"yes"*). PyWriter confirms what it heard.

**Keyboard:**

| Key | Does | | Key | Does |
|---|---|---|---|---|
| Ctrl+Enter | Next question | | Ctrl+G | Guided interview |
| Alt+Left | Previous question | | Ctrl+T | Talk mode |
| F2 | Read question aloud | | Ctrl+H | History and backups |
| F3 | Read answer aloud | | Ctrl+O | New / open project |
| F4 | Dictate | | Ctrl+, | Settings |
| F5 | Narration mode | | Ctrl+Shift+Z | Undo last change |
| F11 | Distraction-free mode | | Esc | Stop reading |
| Ctrl+= / Ctrl+- | Larger / smaller text | | Ctrl+Q | Exit |

---

## How saving works

Every project is a folder:

```
Documents/PyWriter Projects/<Title>/
    <Title>.pwdb                    the project database (SQLite, one file)
    <Title> - Story Bible.md        readable export, rewritten automatically
    <Title> - Manuscript.md         manuscript export (once you have scenes)
    <Title>_voice-transcript.txt    append-only record of what was heard and said
    backups/                        timestamped full snapshots, never modified
    audio/                          only if you turn on audio recording
```

- Every answer and edit goes into the database straight away, inside a transaction, so a crash or power cut can't leave a half-written file.
- The database keeps a **change log** of every edit, with the old and new values. **Tools ▸ History** uses it to revert single changes.
- **Snapshots** in `backups/` are complete project copies. All are kept by default. You can change this in **Settings ▸ Backups**.
- To back up or move a project, copy its whole folder.

## Where things are stored

| What | Where |
|---|---|
| Projects | `Documents/PyWriter Projects/` (you can choose another folder when creating a project) |
| Speech models, Piper voices, AI models, name lists | Windows `%APPDATA%\PyWriter\models\` · macOS `~/Library/Application Support/PyWriter/models/` · Linux `~/.local/share/PyWriter/models/` |
| Settings | Windows registry `HKEY_CURRENT_USER\Software\PyWriter` · macOS `~/Library/Preferences` · Linux `~/.config/PyWriter/` |
| Error log | `error.log` in the same PyWriter user-data folder as the models |

---

## Using other languages

PyWriter has three language-dependent parts, and each can be switched separately.

1. **Speech recognition:** download a Vosk model for your language from <https://alphacephei.com/vosk/models>. More than 20 languages are available. Unzip it into the **models** folder (e.g. `…/PyWriter/models/vosk-model-small-es-0.42/`), then pick it in **Settings ▸ Listening ▸ Speech model / language**.
2. **Reading voice:** you have two options.
   - Add a Windows voice for the language: **Settings ▸ Time & language ▸ Language & region**, and include *Text-to-speech*.
   - Use a Piper voice. Download both its `.onnx` and `.onnx.json` files from <https://huggingface.co/rhasspy/piper-voices> into `…/PyWriter/models/piper/`.
3. **Interview questions:** these are plain YAML files in [`pywriter/packs/`](pywriter/packs/).
   1. Copy a pack (e.g. `10_character.yaml` → `10_character_es.yaml`) and give it a new `pack:` id.
   2. Translate `title`, `intro`, `outro`, `another`, section titles, and each question's `ask`, `label` and option `label`.
   3. **Don't change** `key`, option `value`, `type`, `kind`, `relation` or `when`. Those keep the database, links and branching working.
   4. Make sure only one pack per kind is listed for a project type in `project_types:`.
   5. Restart PyWriter. **Tools ▸ Diagnostics** shows any pack errors.

Talk mode understands English sentence patterns only. Interviews, dictation and read-aloud work in any language you have models and voices for.

The bundled name lists for spelling checks are US-based. You can import the larger official SSA list with **Settings ▸ Import SSA names.zip…**, or drop your own `names_first.tsv` / `names_last.tsv` files (name, tab, popularity) into the models folder.

---

## Downloads, privacy and training data

**PyWriter never sends your writing anywhere.** The only network access is downloads you start yourself:

| Download | Source | Where in the app |
|---|---|---|
| Speech recognition (Vosk) | [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models) | Voice ▸ Download speech model… |
| Natural voices (Piper) | [huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) | Settings ▸ Reading voice ▸ Get natural voices… |
| Optional AI assistant (Qwen2.5 1.5B / 0.5B, GGUF) | [Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) · [Qwen2.5-0.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) | Tools ▸ Local AI assistant… |
| Larger first-name list | [SSA names.zip](https://www.ssa.gov/oact/babynames/names.zip) (you download it; PyWriter imports the file) | Settings ▸ Import SSA names.zip… |

Downloads show a progress bar, can be cancelled, and resume if interrupted. You can also put files in place by hand: Vosk folders and `piper/` voices go in the models folder, and AI models go in `models/llm/`.

**About the optional AI assistant.** It's off unless you switch it on, and it runs entirely on your computer. It needs about 1 GB of disk and 2 GB of memory. It can't write: it may only return filing actions in a fixed format, and any value that isn't mostly your own words is replaced with your original sentence. **Tools ▸ Local AI assistant…** explains each model and lets you enable, disable or delete it.

**Where the models' training data comes from.** PyWriter tries to rely on models trained on data that was paid for, licensed or volunteered:

| Component | Training data |
|---|---|
| Piper voices *ljspeech*, *cori* | Public-domain LibriVox recordings by volunteer readers. Recommended. |
| Piper voice *joe* | Voice donated under CC0. Recommended. |
| Piper voices *lessac*, *ryan* | Licensed research recordings (non-commercial licences) |
| Qwen2.5 models (optional assistant) | Large web-scraped corpus (Apache 2.0 weights). Clearly labelled and entirely optional. |
| Vosk models | Alpha Cephei doesn't publish the training sources for the small English model |
| Talk mode without the assistant | Built-in rules; no trained model at all |

See [ROADMAP.md](ROADMAP.md) for plans to offer models trained only on consented data.

---

## Building the Windows app yourself

From a source checkout, with the dependencies installed:

```bash
python -m pip install -U pyinstaller pyinstaller-hooks-contrib
python build.py
```

Use PyInstaller 6.10 or newer. Older versions build without complaint, but the app then fails at start-up with a NumPy 2 import error. Before sharing a build, always run `dist/FoolsGoldPyWriter/FoolsGoldPyWriter.exe` once.

The output is `dist/FoolsGoldPyWriter/`, containing `FoolsGoldPyWriter.exe` plus its `_internal` folder. It's a folder build because that starts much faster than a single-file `.exe`.

- Optional packages (Piper, llama-cpp, jellyfish…) are bundled only if they're installed when you build.
- Large unrelated libraries (torch, scipy, pandas…) are excluded automatically.
- PyInstaller doesn't cross-compile. To make a macOS or Linux build, run `build.py` on that system.

---

## Project layout

```
main.py                  entry point
build.py                 PyInstaller build script
requirements.txt
pywriter/
  store.py               SQLite project database and change log
  backup.py              snapshots and restore
  library.py             YAML question packs and the condition language
  engine.py              interview engine (branching, linking, stub entries)
  nlu.py                 Talk-mode interpreter (rule-based)
  llm.py                 optional local AI assistant
  names.py               name spelling checks
  voice.py, audio.py     read-aloud, speech recognition, devices, voice commands
  export.py, importer.py, summary.py
  packs/                 question packs (YAML) and guided-interview flows
  data/                  bundled name lists
  resources/             icon and splash screen
  ui/                    Qt windows and panels
```

---

## Reporting problems

Please [open an issue](https://github.com/sharxbyte/FoolsGold_Pywriter/issues) with:

- what you were doing, what you expected, and what happened instead;
- your operating system, and whether you used the `.exe` or ran from source;
- the contents of `error.log` (see [Where things are stored](#where-things-are-stored)) if there is one;
- **Help ▸ About** and **Tools ▸ Diagnostics** output.

Please don't attach project files that contain writing you want to keep private.

---

## Credits

- [Qt for Python (PySide6)](https://www.qt.io/qt-for-python): LGPL
- [Vosk](https://alphacephei.com/vosk/) speech recognition: Apache 2.0
- [Piper](https://github.com/rhasspy/piper) neural text-to-speech: MIT. Each voice has its own licence; see its model card.
- [llama.cpp](https://github.com/ggerganov/llama.cpp) / [llama-cpp-python](https://github.com/abetlen/llama-cpp-python): MIT
- [jellyfish](https://github.com/jamesturk/jellyfish) phonetic matching: MIT · [NetworkX](https://networkx.org/): BSD
- First names: US Social Security Administration baby names (public domain), via [hadley/data-baby-names](https://github.com/hadley/data-baby-names)
- Surnames: US Census Bureau 2000 surnames (public domain), via [FiveThirtyEight's data repository](https://github.com/fivethirtyeight/data/tree/master/most-common-name) (CC BY 4.0)
