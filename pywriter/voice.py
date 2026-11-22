"""Offline voice: text-to-speech, speech-to-text, and spoken command parsing.

* TTS uses Qt's QTextToSpeech (SAPI / WinRT on Windows, speech-dispatcher on Linux,
  AVSpeech on macOS). Falls back to pyttsx3 when Qt has no engine.
* STT uses Vosk with a small (~40 MB) English model, downloaded once from inside the
  app and stored in the user data folder. Audio is captured with sounddevice.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .paths import models_dir

try:
    from PySide6.QtTextToSpeech import QTextToSpeech
except Exception:  # pragma: no cover
    QTextToSpeech = None  # type: ignore

try:
    import vosk  # type: ignore
    vosk.SetLogLevel(-1)
except Exception:  # pragma: no cover
    vosk = None  # type: ignore

try:
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover
    sd = None  # type: ignore

DEFAULT_MODEL = "vosk-model-small-en-us-0.15"
LARGE_MODEL = "vosk-model-en-us-0.22-lgraph"
MODELS = {
    DEFAULT_MODEL: "Small English model (about 40 MB) - fast, works on any computer",
    LARGE_MODEL: "Larger English model (about 128 MB) - noticeably more accurate, needs more memory",
}
MODEL_URL = f"https://alphacephei.com/vosk/models/{DEFAULT_MODEL}.zip"


# =============================================================== text to speech

# Curated natural-sounding Piper voices (downloaded on request from Rhasspy's public
# voice repository on Hugging Face). Any other voice from
# https://huggingface.co/rhasspy/piper-voices can be added by dropping its .onnx and
# .onnx.json files into the models/piper folder.
PIPER_VOICES = {
    "en_US-lessac-medium": "US English, female, clear and neutral",
    "en_US-amy-medium": "US English, female, warm",
    "en_US-ryan-high": "US English, male, high quality",
    "en_US-joe-medium": "US English, male, relaxed",
    "en_US-hfc_female-medium": "US English, female, bright",
    "en_GB-alba-medium": "British English, female (Scottish)",
    "en_GB-northern_english_male-medium": "British English, male (Northern)",
    "en_GB-cori-high": "British English, female, high quality",
}


def piper_dir() -> Path:
    d = models_dir() / "piper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def piper_installed() -> list[str]:
    return sorted(p.name[:-5] for p in piper_dir().glob("*.onnx") if (p.parent / (p.name + ".json")).exists())


def piper_available() -> bool:
    try:
        import piper  # noqa: F401
        return sd is not None
    except Exception:
        return False


def piper_url(voice: str, ext: str) -> str:
    lang, speaker, quality = voice.split("-", 2)
    return (f"https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{lang.split('_')[0]}/{lang}/{speaker}/{quality}/{voice}{ext}")


def engines() -> list[tuple[str, str]]:
    """Available speech engines as (id, description)."""
    out = []
    if QTextToSpeech is not None:
        names = QTextToSpeech.availableEngines()
        if "winrt" in names:
            out.append(("winrt", "Windows modern voices (OneCore)"))
        if "sapi" in names:
            out.append(("sapi", "Windows classic voices (SAPI)"))
        for e in names:
            if e not in ("winrt", "sapi", "mock"):
                out.append((e, f"System voices ({e})"))
    if piper_available():
        out.append(("piper", "Natural neural voices (Piper, offline)"))
    return out


class Speaker(QObject):
    """Speaks text with the chosen engine. Emits ``started`` and ``finished`` so
    listeners can pause while it talks (so it doesn't hear itself)."""

    started = Signal()
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tts = None
        self._py = None
        self._speaking = False
        self._piper_voice = None
        self._piper_name = ""
        self._stop_flag = threading.Event()
        self._gen = 0
        self.engine = ""
        self.rate = 0.0     # -1.0 .. 1.0
        self.pitch = 0.0    # -1.0 .. 1.0
        self.volume = 1.0
        self.voice_name = ""
        self.set_engine("")

    # ---------------------------------------------------------------- engine
    def set_engine(self, engine: str) -> None:
        """'' picks the best available system engine."""
        avail = [e for e, _ in engines()]
        if engine and engine not in avail:
            engine = ""
        if not engine:
            sys_engines = [e for e in avail if e != "piper"]
            engine = sys_engines[0] if sys_engines else ("piper" if "piper" in avail else "")
        if engine == self.engine and (self._tts is not None or engine == "piper"):
            return
        self.stop()
        if self._tts is not None:
            self._tts.deleteLater()
            self._tts = None
        self.engine = engine
        if engine and engine != "piper" and QTextToSpeech is not None:
            self._tts = QTextToSpeech(engine, self)
            self._tts.stateChanged.connect(self._on_state)
        if not engine:
            try:
                import pyttsx3  # type: ignore
                self._py = pyttsx3
            except Exception:
                self._py = None

    @property
    def available(self) -> bool:
        return self._tts is not None or self.engine == "piper" or self._py is not None

    def voices(self, engine: str | None = None) -> list[str]:
        engine = engine if engine is not None else self.engine
        if engine == "piper":
            return piper_installed()
        if QTextToSpeech is None or not engine:
            return []
        if engine == self.engine and self._tts is not None:
            return [v.name() for v in self._tts.availableVoices()]
        tmp = QTextToSpeech(engine)
        names = [v.name() for v in tmp.availableVoices()]
        tmp.deleteLater()
        return names

    def apply_settings(self, rate: float, volume: float, voice_name: str, engine: str = "",
                       pitch: float = 0.0) -> None:
        self.set_engine(engine)
        self.rate, self.volume, self.voice_name, self.pitch = rate, volume, voice_name, pitch
        if self._tts is not None:
            self._tts.setRate(max(-1.0, min(1.0, rate)))
            self._tts.setPitch(max(-1.0, min(1.0, pitch)))
            self._tts.setVolume(max(0.0, min(1.0, volume)))
            for v in self._tts.availableVoices():
                if v.name() == voice_name:
                    self._tts.setVoice(v)
                    break

    def _on_state(self, state) -> None:
        if QTextToSpeech is None:
            return
        if state == QTextToSpeech.State.Speaking and not self._speaking:
            self._speaking = True
            self.started.emit()
        elif state in (QTextToSpeech.State.Ready, QTextToSpeech.State.Error) and self._speaking:
            self._speaking = False
            self.finished.emit()

    @property
    def speaking(self) -> bool:
        return self._speaking

    # ---------------------------------------------------------------- speaking
    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self.finished.emit()
            return
        if self.engine == "piper":
            self._say_piper(text)
            return
        if self._tts is not None:
            self._tts.stop()
            self._tts.say(text)
            return
        if self._py is not None:
            self._run_thread(self._py_worker, text)
        else:
            self.finished.emit()

    def _run_thread(self, fn, text: str) -> None:
        self.stop()
        self._stop_flag = threading.Event()
        self._gen += 1
        gen = self._gen
        self._speaking = True
        self.started.emit()

        def run():
            try:
                fn(text, self._stop_flag)
            except Exception as e:  # never let audio errors escape the thread
                print("speech error:", e)
            finally:
                if gen == self._gen:
                    self._speaking = False
                    self.finished.emit()
        threading.Thread(target=run, daemon=True).start()

    def _py_worker(self, text: str, stop: threading.Event) -> None:
        eng = self._py.init()
        eng.setProperty("rate", int(180 * (1 + self.rate * 0.5)))
        eng.setProperty("volume", self.volume)
        eng.say(text)
        eng.runAndWait()

    def _load_piper(self):
        name = self.voice_name if self.voice_name in piper_installed() else \
            (piper_installed()[0] if piper_installed() else "")
        if not name:
            return None
        if self._piper_voice is None or self._piper_name != name:
            from piper import PiperVoice  # type: ignore
            self._piper_voice = PiperVoice.load(str(piper_dir() / f"{name}.onnx"))
            self._piper_name = name
        return self._piper_voice

    def _say_piper(self, text: str) -> None:
        def work(text: str, stop: threading.Event) -> None:
            voice = self._load_piper()
            if voice is None:
                return
            import numpy as np
            try:
                from piper import SynthesisConfig  # type: ignore
                # length_scale > 1 is slower; map rate -1..1 to 1.5..0.6
                cfg = SynthesisConfig(length_scale=1.0 - 0.45 * self.rate if self.rate > 0 else 1.0 - 0.5 * self.rate,
                                      volume=max(0.0, min(1.0, self.volume)))
            except Exception:
                cfg = None
            for chunk in voice.synthesize(text, syn_config=cfg):  # one chunk per sentence
                if stop.is_set():
                    break
                audio = chunk.audio_int16_array
                rate = chunk.sample_rate
                if self.pitch:  # simple pitch shift by resampling playback rate
                    rate = int(rate * (1.0 + 0.25 * self.pitch))
                sd.play(np.asarray(audio), rate)
                while sd.get_stream().active:
                    if stop.wait(0.05):
                        sd.stop()
                        return
        self._run_thread(work, text)

    def stop(self) -> None:
        if self._tts is not None:
            self._tts.stop()
        self._stop_flag.set()
        if self.engine == "piper" and sd is not None:
            try:
                sd.stop()
            except Exception:
                pass


class PiperDownloader(QThread):
    progress = Signal(int, int)
    done = Signal(str)

    def __init__(self, voice: str, parent=None):
        super().__init__(parent)
        self.voice = voice

    def run(self) -> None:
        d = piper_dir()
        try:
            for ext in (".onnx.json", ".onnx"):
                target = d / f"{self.voice}{ext}"
                tmp = target.with_suffix(target.suffix + ".part")
                req = urllib.request.Request(piper_url(self.voice, ext), headers={"User-Agent": "PyWriter"})
                with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    done = 0
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if ext == ".onnx":
                            self.progress.emit(done, total)
                tmp.replace(target)
            self.done.emit("")
        except Exception as e:
            self.done.emit(str(e))


# =============================================================== speech to text

PREFERRED_MODEL = ""  # set from Settings; a folder name inside the models folder


def installed_models() -> list[str]:
    """Names of Vosk model folders in the models folder (any language)."""
    return sorted(p.name for p in models_dir().glob("vosk-model*") if p.is_dir())


def model_path() -> Path | None:
    """Return the chosen Vosk model folder, or the best installed one."""
    base = models_dir()
    if PREFERRED_MODEL and (base / PREFERRED_MODEL).is_dir():
        return base / PREFERRED_MODEL
    for name in (LARGE_MODEL, DEFAULT_MODEL):  # prefer the more accurate model when installed
        preferred = base / name
        if (preferred / "am").exists() or (preferred / "conf").exists():
            return preferred
    for p in sorted(base.glob("vosk-model*")):
        if p.is_dir():
            return p
    return None


def stt_status() -> str:
    if vosk is None:
        return "The 'vosk' package is not installed."
    if sd is None:
        return "The 'sounddevice' package is not installed."
    if model_path() is None:
        return "No speech model yet. Use Voice ▸ Download Speech Model (one time, about 40 MB)."
    return ""


def input_devices() -> list[tuple[int, str]]:
    if sd is None:
        return []
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d["name"]))
    except Exception:
        pass
    return out


class _ListenWorker(QObject):
    partial = Signal(str)
    final = Signal(str)
    level = Signal(float)
    silence = Signal(float)     # seconds since last speech, emitted ~4x/second
    error = Signal(str)
    stopped = Signal()

    def __init__(self, device: int | None):
        super().__init__()
        self.device = device
        self._running = False

    @Slot()
    def run(self) -> None:
        mp = model_path()
        if vosk is None or sd is None or mp is None:
            self.error.emit(stt_status() or "Speech recognition unavailable.")
            self.stopped.emit()
            return
        try:
            model = _ModelCache.get(mp)
            rate = 16000
            rec = vosk.KaldiRecognizer(model, rate)
            q: queue.Queue[bytes] = queue.Queue()

            def cb(indata, frames, t, status):
                q.put(bytes(indata))

            self._running = True
            last_voice = time.monotonic()
            last_tick = 0.0
            with sd.RawInputStream(samplerate=rate, blocksize=4000, dtype="int16", channels=1,
                                   device=self.device, callback=cb):
                while self._running:
                    try:
                        data = q.get(timeout=0.25)
                    except queue.Empty:
                        data = b""
                    if data:
                        # RMS level for the meter (int16 little-endian)
                        import array
                        a = array.array("h", data)
                        if a:
                            rms = (sum(x * x for x in a[::8]) / max(1, len(a[::8]))) ** 0.5
                            lvl = min(1.0, rms / 6000.0)
                            self.level.emit(lvl)
                        if rec.AcceptWaveform(data):
                            text = json.loads(rec.Result()).get("text", "").strip()
                            if text:
                                last_voice = time.monotonic()
                                self.final.emit(text)
                        else:
                            p = json.loads(rec.PartialResult()).get("partial", "").strip()
                            if p:
                                last_voice = time.monotonic()
                                self.partial.emit(p)
                    now = time.monotonic()
                    if now - last_tick > 0.25:
                        last_tick = now
                        self.silence.emit(now - last_voice)
                tail = json.loads(rec.FinalResult()).get("text", "").strip()
                if tail:
                    self.final.emit(tail)
        except Exception as e:
            self.error.emit(f"Microphone error: {e}")
        self.stopped.emit()

    def stop(self) -> None:
        self._running = False


class _ModelCache:
    _models: dict[str, object] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, path: Path):
        with cls._lock:
            key = str(path)
            if key not in cls._models:
                cls._models[key] = vosk.Model(key)
            return cls._models[key]


class Listener(QObject):
    """Continuous speech recognition. Start/stop as needed; one at a time per app."""

    partial = Signal(str)
    final = Signal(str)
    level = Signal(float)
    silence = Signal(float)
    error = Signal(str)
    state_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.device: int | None = None
        self._thread: QThread | None = None
        self._worker: _ListenWorker | None = None

    @property
    def available(self) -> bool:
        return not stt_status()

    @property
    def listening(self) -> bool:
        return self._thread is not None

    def start(self) -> bool:
        if self._thread is not None:
            return True
        if not self.available:
            self.error.emit(stt_status())
            return False
        self._thread = QThread()
        self._worker = _ListenWorker(self.device)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.partial.connect(self.partial)
        self._worker.final.connect(self.final)
        self._worker.level.connect(self.level)
        self._worker.silence.connect(self.silence)
        self._worker.error.connect(self.error)
        self._worker.stopped.connect(self._on_stopped)
        self._thread.start()
        self.state_changed.emit(True)
        return True

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()

    def stop_and_wait(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._on_stopped()

    def _on_stopped(self) -> None:
        if self._thread is None:
            return
        th, self._thread, self._worker = self._thread, None, None
        th.quit()
        th.wait(2000)
        th.deleteLater()
        self.state_changed.emit(False)


class ModelDownloader(QThread):
    progress = Signal(int, int)  # bytes done, total
    done = Signal(str)           # error message, or "" on success

    def __init__(self, parent=None, model: str = DEFAULT_MODEL):
        super().__init__(parent)
        self.model = model

    def run(self) -> None:
        target = models_dir()
        zpath = target / f"{self.model}.zip"
        url = f"https://alphacephei.com/vosk/models/{self.model}.zip"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PyWriter"})
            with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    self.progress.emit(done, total)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(target)
            zpath.unlink(missing_ok=True)
            self.done.emit("")
        except Exception as e:
            try:
                zpath.unlink(missing_ok=True)
            except Exception:
                pass
            self.done.emit(str(e))


# =============================================================== spoken commands

_ADVANCE = r"(?:i'?m\s+)?(?:finished|done|next question|next|proceed|continue|move on)"
_CONFIRM = r"(?:confirm|confirmed|yes|yeah|yep|correct)"
_CMD_PATTERNS: list[tuple[str, str]] = [
    ("advance_confirmed", rf"\b{_ADVANCE}\s+(?:and\s+)?{_CONFIRM}\b"),
    ("back", r"\b(?:go back|previous question|last question)\b"),
    ("repeat", r"\b(?:repeat (?:the |that )?question|say (?:that|it) again|read the question)\b"),
    ("read_answer", r"\b(?:read (?:back )?(?:my |the )?answer|what did i say)\b"),
    ("skip", r"\b(?:skip (?:this |that |the )?question|skip it)\b"),
    ("scratch", r"\b(?:scratch that|delete that|undo that|strike that)\b"),
    ("pause", r"\b(?:stop listening|pause narration|pause listening)\b"),
    ("finish_interview", r"\b(?:end (?:the )?interview|finish (?:the )?interview|save and close)\b"),
    ("advance", rf"\b{_ADVANCE}\s*$"),
]
_YES = re.compile(r"^\s*(?:yes|yeah|yep|yup|confirm|confirmed|correct|sure|okay|ok|please do|go ahead)\b")
_NO = re.compile(r"^\s*(?:no|nope|not yet|wait|hold on|keep going|i'?m not)\b")


def parse_command(text: str) -> tuple[str | None, str]:
    """Return (command, remaining dictation text)."""
    t = text.strip().lower()
    for name, pat in _CMD_PATTERNS:
        m = re.search(pat, t)
        if m:
            remaining = (text[:m.start()] + text[m.end():]).strip(" ,.")
            return name, remaining
    return None, text


def is_yes(text: str) -> bool:
    return bool(_YES.search(text.lower()))


def is_no(text: str) -> bool:
    return bool(_NO.search(text.lower()))


def tidy_dictation(text: str, names: list[str] | None = None) -> str:
    """Light clean-up of recognizer output: spoken punctuation, capitals, and the
    project's own names ("port vell" -> "Port Vell")."""
    t = text.strip()
    if not t:
        return t
    repl = {
        r"\s*\bcomma\b": ",", r"\s*\bfull stop\b": ".",
        r"\s*\bquestion mark\b": "?", r"\s*\bexclamation (?:mark|point)\b": "!",
        r"\s*\bnew line\b\s*": "\n", r"\s*\bnew paragraph\b\s*": "\n\n",
    }
    for pat, rep in repl.items():
        t = re.sub(pat, rep, t, flags=re.I)
    t = re.sub(r"\bi\b", "I", t)
    for n in sorted(names or [], key=len, reverse=True):
        if len(n) >= 3:
            t = re.sub(rf"\b{re.escape(n)}\b", n, t, flags=re.I)
    t = re.sub(r"(^|[.!?]\s+|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    if t[-1] not in ".!?\n,":
        t += "."
    return t
