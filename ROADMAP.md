# FoolsGold PyWriter Roadmap

Version 1.0 is a ground-up rewrite of `Pywriter Alpha Version 11.py` (Tkinter) as a Qt (PySide6) desktop app.
Offline and local. No AI text generation; speech and language tools only *interpret* what the writer says.

## Decisions

| Area | Choice | Why |
|---|---|---|
| Language / UI | Python 3.11 + PySide6 (Qt 6) | Runs on Windows, macOS and Linux; best offline speech libraries; smooth, modern UI. |
| Storage | One SQLite database per project (`<Title>.pwdb`) | A single file, safe against crashes (transactions), fast queries, and supports linking. |
| Change log | Append-only `revisions` table in the DB | Replaces the clunky rotating text logs. Every edit is ordered, timestamped and revertible. |
| Backups | Rolling snapshots via SQLite's online backup API, in `backups/` | A full copy is made on open, on close, and on a timer when there are changes. Old snapshots are never edited. Restoring one first snapshots the current state. |
| Readable log | `<Title> - Story Bible.md` regenerated on each save | Human-readable export. Each entry carries the same ID as in the DB (CHR-0001, LOC-0003…). |
| Text-to-speech | Qt TextToSpeech (SAPI/WinRT on Windows), falling back to pyttsx3 | Built in and offline. |
| Speech-to-text | Vosk (small English model, about 40 MB, downloaded once from inside the app) | Offline, streaming, lightweight; can listen for spoken commands. |
| Conversation | Rule-based interpreter plus flowchart interviews; a small local language model can be plugged in later (optional) | Works on any machine with no model download, and is predictable. |
| Interview content | YAML question packs with conditions (`when:`), loops ("add another?"), and links to other entries | Questions can be edited without touching code. |

## Blocks

### Block 1 – Foundation
- [x] Package layout, entry point, settings (QSettings)
- [x] Project creation: choose type, enter a title (validated as a folder name), create the project subfolder
- [x] SQLite `ProjectStore`: entities, fields, links, notes, revisions, metadata
- [x] Readable IDs per kind (CHR-, LOC-, EVT-, GRP-, ITM-, THM-, PLT-, TOP-, SRC-, SCN-)
- [x] Rolling backup manager and restore
- [x] Story Bible Markdown export

### Block 2 – Interview engine and question library
- [x] YAML pack loader, safe condition evaluator, `{name}`/`{their}` templating
- [x] Question types: text, long, choice, yes/no, number, entity link(s)
- [x] Project-level qualifying interviews (scale, timeline linearity, flashbacks, time travel, magic/tech, species) that unlock later questions
- [x] Rewrite the question library as full, specific sentences, in "resume first" order (identity and qualifications, then appearance, then personality, then history, relationships, arc)
- [x] Character depth by tier: primary gets everything, secondary a medium set, tertiary a short set
- [x] Location levels (room → building → district → settlement → region → country → planet → star system → galaxy → dimension → timeline) with a parent location, and sub-location loops
- [x] Packs for fiction, non-fiction and biography

### Block 3 – Main window
- [x] Centered window at half the monitor's size, light and dark themes
- [x] Sidebar sections; lists grouped by tier or by location hierarchy; search
- [x] Double-click opens an entry page in a tab
- [x] Entry page: editable fields grouped by interview section, Re-interview (pre-filled), links, notes, backlinks
- [x] Hover any linked name to see a short bio; click to open the full sheet
- [x] Autosave on interview finish, tab change and window close

### Block 4 – Interview window and voice
- [x] Interview dialog: centered, half the screen, progress bar, back/next/skip, pre-filled answers
- [x] Read aloud: the question, the answer, or both
- [x] Dictation into any text box
- [x] Narration (hands-free) mode: reads the question, listens, a 10-second silence pauses it, and "next question / finished / continue" followed by "confirm / yes" moves on. Also "go back", "repeat", "skip"
- [x] "Add another character/location/…?" loop when an interview finishes
- [x] Guided Story Interview: runs the whole flow (project → world → characters → places → plot → events → themes)

### Block 5 – Talk mode (conversational)
- [x] Type or speak freely: "Mara is the protagonist. She has red hair and lives in Port Vell."
- [x] Spots names, fuzzy-matches them against existing entries, asks about unknown ones (character or place? main, secondary or minor?)
- [x] Pulls facts into fields (appearance, age, occupation…) and relations into links (sister of, lives in, works for…)
- [x] Commands: open X, tell me about X, interview X, change X's age to 30, undo
- [x] Nothing is lost: text it can't parse is saved as a note on the entry being discussed, and the full conversation is kept

### Block 6 – Mapping
- [x] Relationship map (drag nodes, positions saved, double-click opens the entry)
- [x] Location hierarchy tree
- [x] Timeline view ordered by story order

### Block 7 – Writing and history tools
- [x] Manuscript: chapters and scenes with an editor, dictation and read-aloud
- [x] History window: browse revisions, revert a single change, restore a snapshot
- [x] Distraction-free (full screen) mode

### Block 8 – Packaging and next steps
- [x] Build script, README
- [x] Optional: local language model plugin (llama.cpp) for richer conversation
- [x] Optional: import from the v11 JSON projects

### Added during development
- [x] Name spelling checks for spoken names: common-spelling choices (Catherine / Katherine / Kathryn) and letter-by-letter spelling, using bundled US first-name and surname lists plus phonetic matching
- [x] Speech engine choice: Windows modern (WinRT), classic (SAPI), or Piper natural neural voices (optional download); speed, pitch and volume controls
- [x] Speech model picker (any installed Vosk language model) and README instructions for other languages
- [x] Optional larger, more accurate English speech model
- [x] Import of the official SSA names.zip for a larger first-name list

### 1.1
- [x] Talk mode and interviews fully interchangeable: relationships are stored once, as links, and shown in every view
- [x] File ▸ Export: complete backup zip, Word (.docx), spreadsheets (.csv) and lossless JSON
- [x] GPL-3.0-or-later license with plain-language terms of use
- [x] Nuitka folder build, headless `--selftest`, Inno Setup installer, GitHub Actions release workflow with SignPath signing

### Ideas for later
- [x] Optional local language model (llama.cpp) for richer Talk-mode understanding: extraction only, never writing; offered on first run; download, enable, disable and delete from Tools ▸ Local AI assistant
- [x] Voice transcript file per project; communication-device defaults with device pickers; mic noise reduction, gate and compressor; optional WAV/FLAC/MP3 recording
- [ ] Ethically sourced assistant model: instruction-tune an openly licensed base model (Pleias 3B Preview on Common Corpus, or EleutherAI Comma v0.1 on the Common Pile) using openly licensed instruction data, quantize to GGUF, and offer it alongside or instead of Qwen. Pleias-RAG 350M was tested and couldn't do the filing task.
- [ ] Speech recognition trained only on consented data (Mozilla Common Voice and LibriSpeech), e.g. a k2/icefall Zipformer through sherpa-onnx, as an alternative to Vosk
- [ ] Talk-mode patterns for other languages
- [ ] Scene/chapter outline view linked to timeline events
- [ ] Mobile companion (would need a rewrite of the UI layer, e.g. Flutter, reusing the YAML packs and database format)
