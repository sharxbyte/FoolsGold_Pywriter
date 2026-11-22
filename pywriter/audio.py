"""Audio devices, microphone clean-up and optional session recording.

Devices
    By default PyWriter uses Windows' *communication* devices (the microphone and
    speaker Windows uses for calls), falling back to the normal defaults on other
    systems. Any device can be chosen in Settings; choices are remembered by name,
    because device numbers change when hardware is plugged in or out.

Microphone clean-up (applied before speech recognition, all optional)
    * noise reduction - spectral subtraction against a continuously learned
      background-noise profile (fans, hum, hiss)
    * noise gate      - silences the signal between words when it falls below a
      threshold above the noise floor
    * compressor      - evens out loud and quiet speech, with make-up gain, so
      soft-spoken words are still recognized

Recording
    Off by default (only the text transcript is kept). When turned on, each
    listening session is saved in the project's ``audio`` folder as WAV, FLAC or MP3.
"""
from __future__ import annotations

import datetime as _dt
import sys
import wave
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover
    sd = None  # type: ignore

SAMPLE_RATE = 16000
COMM = ""            # setting value: Windows communication device (default)
SYSTEM = "system"    # setting value: the system's normal default device


# =============================================================== devices

def _hostapi_index() -> int | None:
    """Use one host API so devices aren't listed several times. On Windows MME
    resamples to 16 kHz for us and works with every device."""
    if sd is None:
        return None
    try:
        apis = sd.query_hostapis()
        if sys.platform.startswith("win"):
            for i, a in enumerate(apis):
                if a["name"] == "MME":
                    return i
        return sd.default.hostapi if isinstance(sd.default.hostapi, int) else 0
    except Exception:
        return None


def rescan_devices() -> None:
    """Ask PortAudio to look for newly plugged-in devices. Only call while no audio stream is open."""
    if sd is None:
        return
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def list_devices(kind: str) -> list[tuple[int, str]]:
    """[(index, name)] for 'input' or 'output' devices currently connected to this computer."""
    if sd is None:
        return []
    api = _hostapi_index()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get(key, 0) > 0 and (api is None or d["hostapi"] == api) and "Sound Mapper" not in d["name"]:
                out.append((i, d["name"].strip()))
    except Exception:
        pass
    return out


def windows_comm_device_name(kind: str) -> str | None:
    """Friendly name of Windows' default *communications* device (Core Audio API)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import comtypes  # type: ignore
        from pycaw.api.mmdeviceapi import IMMDeviceEnumerator  # type: ignore
        from pycaw.constants import CLSID_MMDeviceEnumerator  # type: ignore
        from pycaw.pycaw import AudioUtilities  # type: ignore
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        en = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator,
                                       comtypes.CLSCTX_INPROC_SERVER)
        flow = 1 if kind == "input" else 0          # eCapture / eRender
        dev = en.GetDefaultAudioEndpoint(flow, 2)    # eCommunications
        return AudioUtilities.CreateDevice(dev).FriendlyName
    except Exception:
        return None


def _match(name: str, devices: list[tuple[int, str]]) -> int | None:
    """Match a full device name to a (possibly truncated) PortAudio device name."""
    n = name.strip().lower()
    for i, d in devices:
        if d.lower() == n:
            return i
    for i, d in devices:
        dl = d.lower()
        if n.startswith(dl) or dl.startswith(n):
            return i
    return None


def _linux_default_device(devices: list[tuple[int, str]]) -> int | None:
    """On Linux the 'pipewire', 'pulse' or 'default' PortAudio device follows whatever
    the user picked in their system sound settings (PipeWire/PulseAudio)."""
    for wanted in ("pipewire", "pulse", "default"):
        for i, d in devices:
            if d.lower() == wanted or d.lower().startswith(wanted + " "):
                return i
    return None


def resolve_device(setting: str | None, kind: str) -> int | None:
    """Turn a saved setting into a sounddevice index for whoever is running PyWriter
    (None = PortAudio's default). Nothing is hard-coded: devices are discovered at run time.

    * ''       -> Windows: the default *communications* device; Linux: the PipeWire/PulseAudio
                  default; macOS and others: the system default
    * 'system' -> the system's normal default device
    * a name   -> that device, if it's connected (otherwise falls back to the default)
    """
    devices = list_devices(kind)
    if setting == SYSTEM:
        return None
    if setting:
        found = _match(setting, devices)
        if found is not None:
            return found
    if sys.platform.startswith("win"):
        comm = windows_comm_device_name(kind)
        return _match(comm, devices) if comm else None
    if sys.platform.startswith("linux"):
        return _linux_default_device(devices)
    return None


def comm_differs_from_default(kind: str) -> bool:
    """True when the Windows communication device isn't the normal default device."""
    if sd is None:
        return False
    comm = resolve_device(COMM, kind)
    if comm is None:
        return False
    try:
        default = sd.default.device[0 if kind == "input" else 1]
        api = _hostapi_index()
        apis = sd.query_hostapis()
        if api is not None:
            default = apis[api]["default_input_device" if kind == "input" else "default_output_device"]
        return comm != default
    except Exception:
        return False


def describe_setting(setting: str | None, kind: str) -> str:
    if setting == SYSTEM:
        return "System default"
    if setting:
        return setting
    comm = windows_comm_device_name(kind)
    return f"Windows communication device ({comm})" if comm else "Default device"


# =============================================================== microphone clean-up

class VoiceProcessor:
    """Streaming noise reduction -> noise gate -> compressor for 16 kHz mono int16 audio."""

    FRAME = 512
    HOP = 256

    def __init__(self, noise_reduction: bool = True, gate: bool = True, compressor: bool = True,
                 strength: float = 0.7, gate_margin_db: float = 6.0):
        self.noise_reduction = noise_reduction
        self.gate = gate
        self.compressor = compressor
        self.strength = strength            # over-subtraction factor for noise reduction
        self.gate_margin_db = gate_margin_db
        self._win = np.hanning(self.FRAME + 1)[:-1].astype(np.float32)
        self._in_buf = np.zeros(0, dtype=np.float32)
        self._ola = np.zeros(self.FRAME, dtype=np.float32)
        self._noise_mag: np.ndarray | None = None
        self._noise_rms = 1e-3
        self._frames_seen = 0
        self._gate_gain = 1.0
        self._floor = None   # noise floor of the (processed) signal, for the gate
        self._env = 0.0
        self.last_level = 0.0

    @property
    def active(self) -> bool:
        return self.noise_reduction or self.gate or self.compressor

    def process(self, data: bytes) -> bytes:
        if not self.active or not data:
            self._update_level(np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0)
            return data
        x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        y = self._spectral(x) if self.noise_reduction else x
        if self.gate:
            y = self._apply_gate(y)
        if self.compressor:
            y = self._compress(y)
        self._update_level(y)
        return (np.clip(y, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()

    def _update_level(self, y: np.ndarray) -> None:
        if len(y):
            self.last_level = float(min(1.0, np.sqrt(np.mean(y * y)) * 6.0))

    # -- noise reduction: STFT spectral subtraction with overlap-add
    def _spectral(self, x: np.ndarray) -> np.ndarray:
        buf = np.concatenate([self._in_buf, x])
        out = []
        pos = 0
        while pos + self.FRAME <= len(buf):
            frame = buf[pos:pos + self.FRAME] * self._win
            spec = np.fft.rfft(frame)
            mag, phase = np.abs(spec), np.angle(spec)
            frame_rms = float(np.sqrt(np.mean(frame * frame))) + 1e-9
            self._frames_seen += 1
            if self._noise_mag is None:
                self._noise_mag = mag.copy()
            # learn the noise profile from quiet frames (and quickly during the first ~0.5 s)
            if self._frames_seen < 30 or frame_rms < self._noise_rms * 2.0:
                a = 0.2 if self._frames_seen < 30 else 0.03
                self._noise_mag = (1 - a) * self._noise_mag + a * mag
                self._noise_rms = (1 - a) * self._noise_rms + a * frame_rms
            clean = np.maximum(mag - self.strength * self._noise_mag, 0.2 * mag)
            frame_out = np.fft.irfft(clean * np.exp(1j * phase), n=self.FRAME).astype(np.float32)
            self._ola += frame_out
            out.append(self._ola[:self.HOP].copy())
            self._ola = np.concatenate([self._ola[self.HOP:], np.zeros(self.HOP, dtype=np.float32)])
            pos += self.HOP
        self._in_buf = buf[pos:]
        # Hann windows at 50% overlap sum to 1, so no extra normalization is needed
        return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)

    # -- noise gate with smooth attack/release (10 ms steps)
    def _apply_gate(self, y: np.ndarray) -> np.ndarray:
        step = 160
        out = y.copy()
        margin = 10 ** (self.gate_margin_db / 20)
        for i in range(0, len(y), step):
            seg = y[i:i + step]
            rms = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0
            # track the background level: follow drops quickly, rises very slowly
            if self._floor is None:
                self._floor = max(rms, 1e-5)
            elif rms < self._floor:
                self._floor += (rms - self._floor) * 0.3
            else:
                self._floor *= 1.0015
            thresh = max(self._floor, 1e-5) * margin
            target = 1.0 if rms > thresh else 0.15
            coef = 0.5 if target > self._gate_gain else 0.05   # fast open, slow close
            self._gate_gain += (target - self._gate_gain) * coef
            out[i:i + step] = seg * self._gate_gain
        return out

    # -- compressor: -24 dBFS threshold, 3:1, make-up gain to bring speech up
    def _compress(self, y: np.ndarray, threshold_db: float = -24.0, ratio: float = 3.0,
                  makeup_db: float = 9.0) -> np.ndarray:
        step = 160
        out = y.copy()
        makeup = 10 ** (makeup_db / 20)
        for i in range(0, len(y), step):
            seg = y[i:i + step]
            rms = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0
            coef = 0.4 if rms > self._env else 0.05
            self._env += (rms - self._env) * coef
            level_db = 20 * np.log10(self._env + 1e-9)
            gain_db = 0.0 if level_db < threshold_db else (threshold_db - level_db) * (1 - 1 / ratio)
            out[i:i + step] = seg * (10 ** (gain_db / 20)) * makeup
        return out


# =============================================================== recording

RECORD_FORMATS = {"": "Don't record audio (transcript only)", "wav": "WAV (uncompressed, largest)",
                  "flac": "FLAC (lossless, about half the size)", "mp3": "MP3 (smallest)"}


class SessionRecorder:
    """Writes one listening session to an audio file."""

    def __init__(self, path: Path, fmt: str):
        self.path = path
        self.fmt = fmt
        path.parent.mkdir(parents=True, exist_ok=True)
        self._sf = None
        self._wav = None
        try:
            import soundfile as sfile  # type: ignore
            sub = {"wav": "PCM_16", "flac": "PCM_16", "mp3": "MPEG_LAYER_III"}[fmt]
            self._sf = sfile.SoundFile(str(path), "w", samplerate=SAMPLE_RATE, channels=1,
                                       format=fmt.upper(), subtype=sub)
        except Exception:
            if fmt != "wav":
                self.path = path.with_suffix(".wav")
            self._wav = wave.open(str(self.path), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(SAMPLE_RATE)

    def write(self, data: bytes) -> None:
        if self._sf is not None:
            self._sf.write(np.frombuffer(data, dtype=np.int16))
        elif self._wav is not None:
            self._wav.writeframes(data)

    def close(self) -> None:
        for f in (self._sf, self._wav):
            try:
                if f is not None:
                    f.close()
            except Exception:
                pass
        self._sf = self._wav = None


def recording_path(project_folder: Path, title: str, fmt: str) -> Path:
    ts = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return project_folder / "audio" / f"{title}_{ts}.{fmt}"
