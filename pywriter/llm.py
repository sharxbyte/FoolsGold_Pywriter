"""Optional local AI assistant for Talk mode.

A small instruction-tuned language model, run entirely on this computer with
llama.cpp, that *interprets* what the writer says or types and turns it into
structured story-bible updates (the same actions the rule-based interpreter
produces). It is never asked to write prose, and its output is limited to a
fixed JSON format, so it can't write the story.

Nothing leaves the computer: the model file is downloaded once from Hugging Face
when the writer chooses to, and after that no network connection is used.
"""
from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .paths import models_dir


@dataclass(frozen=True)
class ModelInfo:
    id: str
    title: str
    url: str
    file_mb: int
    ram_gb: float
    note: str
    page: str = ""


MODELS: dict[str, ModelInfo] = {
    "qwen2.5-1.5b": ModelInfo(
        "qwen2.5-1.5b", "Qwen2.5 1.5B Instruct (recommended)",
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        1120, 2.0, "Good understanding of casual phrasing; about 1–3 seconds per reply on a typical laptop.",
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF"),
    "qwen2.5-0.5b": ModelInfo(
        "qwen2.5-0.5b", "Qwen2.5 0.5B Instruct (lightweight)",
        "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        400, 1.0, "For older or low-memory computers. Noticeably less accurate in testing: it often misreads remarks, so PyWriter falls back to its built-in rules more often.",
        "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"),
}

ABOUT_HTML = """
<h3>Local AI assistant (optional)</h3>
<p>PyWriter works fully without this. The optional assistant is a small language model that runs
<b>entirely on your computer</b>. It helps PyWriter understand you, not write for you:</p>
<ul>
<li>It understands freer, more natural phrasing in <b>Talk mode</b>. For example, "oh and Mara's got this
nasty scar from the shipwreck" is filed as a distinguishing feature of Mara.</li>
<li>It works out who "she", "they" or "the captain" refers to from the conversation so far.</li>
<li>It fixes speech-recognition slips by matching them against the names already in your project.
For example, "more of an" becomes "Mara Venn".</li>
</ul>

<h4>What it does <i>not</i> do</h4>
<ul>
<li><b>It does not write.</b> It's only allowed to return a short list of filing actions, such as "set Mara's
hair to red" or "link Tomas as Mara's brother", in a fixed format. Every word stored in your project is a word
you said or typed.</li>
<li><b>It does not share anything.</b> It has no internet access and sends no data anywhere. The only
network use is downloading the model file once, when you click Download.</li>
<li><b>It doesn't learn from you or keep a hidden history.</b> Your conversation is stored only in your project
file, in Talk mode's conversation log, the same as without the assistant. It's there so you and PyWriter can
organize your writing, and you can see and delete it.</li>
</ul>

<h4>What the model is</h4>
<p><b>Qwen2.5 Instruct</b> is made by the Qwen team at Alibaba Cloud and released under the
open <b>Apache 2.0</b> license. According to its creators, the Qwen2.5 models were pre-trained on up to
about 18 trillion tokens of multilingual text, code and mathematics, gathered mostly from the public web.
They were then instruction-tuned with supervised fine-tuning and reinforcement learning from human feedback,
so they follow instructions well. PyWriter uses a compressed ("4-bit quantized", GGUF format) copy so it runs on
ordinary computers without a graphics card. Details:
<a href="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct">huggingface.co/Qwen/Qwen2.5-1.5B-Instruct</a>
and the Qwen2.5 technical report.</p>
<p><b>A note on training data.</b> Like most language models, Qwen2.5 was trained on a very large collection of
web text. That collection very likely includes writing that was gathered without its authors' explicit consent.
We looked for a small model trained only on licensed, public-domain or donated text that can do this job.
The best candidate (Pleias, trained only on openly licensed data) is built for a different task and couldn't
do the filing reliably. If this matters to you, leave the assistant off. Talk mode works without it, using
PyWriter's built-in rules, which involve no trained model at all. If a suitable ethically sourced model
appears, it will be offered here.</p>
<p>Like any language model it can misunderstand. When it's unsure, PyWriter asks you, or falls back to its
built-in rules. Everything it changes is recorded in History and can be undone ("undo" in Talk mode).</p>

<h4>What it needs</h4>
<table cellpadding="3">
<tr><td><b>Recommended (1.5B)</b></td><td>about 1.1 GB of disk space · about 2 GB of free memory while
running · any 64-bit processor from the last ~8 years · no graphics card needed</td></tr>
<tr><td><b>Lightweight (0.5B)</b></td><td>about 0.4 GB of disk space · about 1 GB of free memory · faster but
less accurate</td></tr>
</table>
<p>The model loads in the background the first time you use Talk mode, which takes a few seconds. Each reply
then takes roughly 1–3 seconds. It only uses your processor while working out a reply. The Python package
<code>llama-cpp-python</code> must be installed; it is included in requirements.txt and in the standalone
app.</p>

<h4>Turning it on, off, or removing it</h4>
<ul>
<li><b>Enable:</b> download a model below and tick <i>Use the local AI assistant in Talk mode</i>.</li>
<li><b>Disable:</b> untick it. PyWriter goes back to its built-in rules immediately, and the model stays
downloaded for later.</li>
<li><b>Delete:</b> click <i>Delete model</i> to remove the file and free the disk space. You can download it
again at any time.</li>
<li>This window is always available from <b>Tools ▸ Local AI assistant…</b> and from Settings.</li>
</ul>
"""

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["create", "set", "link", "open", "describe",
                                                      "interview", "note", "ask"]},
                    "kind": {"type": "string", "enum": ["character", "location", "group", "item", "event",
                                                        "theme", "plot", "topic", "source", ""]},
                    "name": {"type": "string"},
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                    "relation": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["op"],
            },
        }
    },
    "required": ["actions"],
}

SYSTEM_PROMPT = """You convert a writer's remarks about their story into filing actions for a story database.
You never write story text. You only copy facts the writer stated, using their words.

Return JSON: {"actions": [...]}. Each action is one of:
- {"op":"create","kind":K,"name":N}  a new character/location/group/item/event/theme the writer introduces
- {"op":"set","name":N,"field":F,"value":V}  a fact about an existing or just-created entry; V uses the writer's words
- {"op":"link","name":A,"relation":R,"target":B}  B is A's R, e.g. relation "sibling", "parent", "friend",
  "enemy", "rival", "mentor", "spouse", "lives in", "born in", "member of", "located in", "works in"
- {"op":"open","name":N} | {"op":"describe","name":N} | {"op":"interview","name":N or "","kind":K}
- {"op":"note","name":N or "","value":V}  anything that fits no field
- {"op":"ask","value":question}  only if you truly cannot tell what the writer means

Rules: file ONLY the facts in WRITER SAYS. RECENT CONVERSATION is context for working out who he/she/they
refers to; never repeat facts from it. Use the exact spelling of KNOWN NAMES when the writer clearly means one of
them (speech recognition may mishear names). Use "link" (not "set") for where someone lives or comes from. Prefer these fields:
character: tier(primary|secondary|tertiary), story_role, age, pronouns, occupation, height, build, hair,
eyes, skin, features, clothing, voice, personality, strengths, flaws, want, fear, secret, skills, loves,
hates, values, upbringing; location: level, place_type, look, climate, population, governance, economy,
dangers, importance; group: group_type, purpose; event: summary, when; others: summary.
Keep values short and in the writer's words. Output only JSON.

EXAMPLES
KNOWN NAMES: Mara Venn | CURRENTLY DISCUSSING: Mara Venn
WRITER SAYS: oh and she's got a nasty scar from the shipwreck
{"actions":[{"op":"set","name":"Mara Venn","field":"features","value":"a nasty scar from the shipwreck"}]}

KNOWN NAMES: Mara Venn | CURRENTLY DISCUSSING: Mara Venn
WRITER SAYS: her brother tomas is a fisherman
{"actions":[{"op":"create","kind":"character","name":"Tomas"},{"op":"link","name":"Mara Venn","relation":"sibling","target":"Tomas"},{"op":"set","name":"Tomas","field":"occupation","value":"fisherman"}]}

KNOWN NAMES: Mara Venn, Tomas | CURRENTLY DISCUSSING: Tomas
WRITER SAYS: more of an is scared of the dark
{"actions":[{"op":"set","name":"Mara Venn","field":"fear","value":"scared of the dark"}]}

KNOWN NAMES: Mara Venn | CURRENTLY DISCUSSING: Mara Venn
WRITER SAYS: she grew up in a mining village called hollow end
{"actions":[{"op":"create","kind":"location","name":"Hollow End"},{"op":"set","name":"Hollow End","field":"place_type","value":"mining village"},{"op":"link","name":"Mara Venn","relation":"born in","target":"Hollow End"}]}"""


_LOG_CB = None


def _silence_llama_logs() -> None:
    """Route llama.cpp's native log output to a no-op callback (kept alive globally)."""
    global _LOG_CB
    if _LOG_CB is not None:
        return
    try:
        import ctypes
        import llama_cpp
        _LOG_CB = llama_cpp.llama_log_callback(lambda level, text, user_data: None)
        llama_cpp.llama_log_set(_LOG_CB, ctypes.c_void_p(0))
    except Exception:
        pass


def model_path(model_id: str) -> Path:
    return models_dir() / "llm" / Path(MODELS[model_id].url).name


def installed_models() -> list[str]:
    return [m for m in MODELS if model_path(m).exists()]


def runtime_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def delete_model(model_id: str) -> None:
    p = model_path(model_id)
    if p.exists():
        p.unlink()


class LLMDownloader(QThread):
    progress = Signal(int, int)
    done = Signal(str)

    def __init__(self, model_id: str, parent=None):
        super().__init__(parent)
        self.model_id = model_id
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        """Download with resume: an interrupted or cancelled download continues where it
        stopped next time, instead of starting over."""
        target = model_path(self.model_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        try:
            have = tmp.stat().st_size if tmp.exists() else 0
            headers = {"User-Agent": "PyWriter"}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(MODELS[self.model_id].url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                resumed = have and r.status == 206
                if not resumed:
                    have = 0
                total = have + int(r.headers.get("Content-Length") or 0)
                done = have
                with open(tmp, "ab" if resumed else "wb") as f:
                    while not self._cancel:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        self.progress.emit(done, total)
            if self._cancel:
                self.done.emit("cancelled")   # keep the partial file so it can resume
                return
            if total and tmp.stat().st_size != total:
                self.done.emit("The download was incomplete. Click Download again to resume.")
                return
            tmp.replace(target)
            self.done.emit("")
        except Exception as e:
            self.done.emit(f"{e}\n\nClick Download again to resume where it stopped.")


class LocalAssistant(QObject):
    """Loads the model lazily in a background thread and answers requests off the UI thread."""

    ready_changed = Signal(bool)
    result = Signal(int, object)   # request id, list of actions (or None on failure)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_id = ""
        self.enabled = False
        self._llm = None
        self._loading = False
        self._lock = threading.Lock()
        self._req = 0

    @property
    def usable(self) -> bool:
        return self.enabled and runtime_available() and bool(self.model_id) and model_path(self.model_id).exists()

    @property
    def ready(self) -> bool:
        return self._llm is not None

    def configure(self, enabled: bool, model_id: str) -> None:
        if model_id != self.model_id or not enabled:
            self.unload()
        self.enabled, self.model_id = enabled, model_id

    def unload(self) -> None:
        with self._lock:
            self._llm = None
        self.ready_changed.emit(False)

    def warm_up(self) -> None:
        """Start loading in the background so the first reply is quick."""
        if not self.usable or self._llm is not None or self._loading:
            return
        self._loading = True
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from llama_cpp import Llama
            _silence_llama_logs()
            # verbose=True stops llama-cpp-python from redirecting the whole process's stdout/stderr
            # while loading (which isn't thread-safe and can swallow other output); its native log
            # messages are silenced by the callback above instead.
            llm = Llama(model_path=str(model_path(self.model_id)), n_ctx=4096, n_threads=None, verbose=True)
            with self._lock:
                self._llm = llm
            self.ready_changed.emit(True)
        except Exception as e:
            print("local model failed to load:", e)
        finally:
            self._loading = False

    def request(self, text: str, known_names: list[str], recent: list[tuple[str, str]], focus: str) -> int:
        """Ask for actions asynchronously; the answer arrives on ``result``."""
        self._req += 1
        rid = self._req
        threading.Thread(target=self._run, args=(rid, text, known_names, recent, focus), daemon=True).start()
        return rid

    def interpret(self, text: str, known_names: list[str], recent: list[tuple[str, str]], focus: str):
        """Blocking version (used by tests). Returns a list of actions, or None."""
        if self._llm is None:
            self._load()
        if self._llm is None:
            return None
        names = ", ".join(known_names[:200]) or "(none yet)"
        convo = "\n".join(f"{who}: {t}" for who, t in recent[-8:]) or "(start of conversation)"
        user = (f"KNOWN NAMES: {names}\nCURRENTLY DISCUSSING: {focus or 'nothing yet'}\n"
                f"RECENT CONVERSATION:\n{convo}\n\nWRITER SAYS: {text}")
        with self._lock:
            out = self._llm.create_chat_completion(
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                response_format={"type": "json_object", "schema": ACTION_SCHEMA},
                temperature=0.0, max_tokens=400)
        try:
            data = json.loads(out["choices"][0]["message"]["content"])
            acts = data.get("actions")
            return acts if isinstance(acts, list) else None
        except (ValueError, KeyError, TypeError):
            return None

    def _run(self, rid, text, names, recent, focus) -> None:
        try:
            acts = self.interpret(text, names, recent, focus)
        except Exception as e:
            print("local model error:", e)
            acts = None
        self.result.emit(rid, acts)
