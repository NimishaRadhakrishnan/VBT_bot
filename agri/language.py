"""Tamil / English / Tanglish understanding: style detection, glossary normalisation, speech."""
from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from rapidfuzz import fuzz

from .config import get_settings
from .taxonomy import glossary

log = logging.getLogger(__name__)

TAMIL_RE = re.compile(r"[஀-௿]")
WORD_RE = re.compile(r"[a-z]+")

# Romanised Tamil function words and verbs that do not occur in English.
TANGLISH_WORDS = {
    "en", "enna", "ennoda", "enoda", "irukku", "iruku", "irukkudhu", "aaguthu", "aagudhu", "agudhu", "aguthu",
    "illa", "illai", "illaye", "romba", "konjam", "chedi", "chediyoda", "chedila", "ilai", "ilaigal", "ilaila",
    "poguthu", "pogudhu", "panna", "pannanum", "pannalam", "sollunga", "solunga", "eppadi", "yen", "edhuku",
    "ethuku", "thaan", "vandhu", "vanthu", "varudhu", "varuthu", "aana", "aanaa", "ippo", "nalla", "kudunga",
    "podanum", "podalam", "adikkanum", "marunthu", "marundhu", "noi", "pazhaya", "pudhu", "puthu", "mela",
    "keela", "theriyala", "theriyuma", "venum", "vendum", "seiyanum", "kaai", "pazham", "vayal", "thottam",
    "nilam", "anna", "akka", "sir", "ayya", "manjal", "manjala", "surundu", "pulli", "vaadi", "azhugal",
    "milagai", "thakkali", "nel", "vazhai", "vaazhai", "thennai", "elakkai", "milagu", "uram", "poochi", "puzhu",
    "vanakkam", "nandri", "seri", "sari", "aamaa", "aama", "illainga", "aamanga", "ennanga", "pathi",
}
ENGLISH_HINT = {"the", "is", "are", "my", "what", "which", "how", "why", "leaves", "plant", "plants", "and", "of", "to"}


def detect_style(text: str, previous: str | None = None) -> str:
    """'ta' (Tamil script), 'ta-Latn' (Tanglish) or 'en'. Very short replies inherit the previous style."""
    text = (text or "").strip()
    if not text:
        return previous or "en"
    tamil_chars = len(TAMIL_RE.findall(text))
    letters = sum(ch.isalpha() for ch in text) or 1
    if tamil_chars / letters >= 0.25:
        return "ta"
    words = WORD_RE.findall(text.lower())
    if not words:
        return previous or "en"
    tl = sum(w in TANGLISH_WORDS for w in words)
    en = sum(w in ENGLISH_HINT for w in words)
    if tl and (tl >= en or tl / len(words) >= 0.2):
        return "ta-Latn"
    if len(words) <= 2 and previous and tl == 0 and en == 0:
        return previous  # "ok", "yes", "older leaves" keep the conversation's language
    return "en"


@dataclass
class Extraction:
    crops: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    leaf_age: str | None = None
    intents: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)


def _match(text: str, forms: list[str]) -> bool:
    low = text.lower()
    tokens = WORD_RE.findall(low)
    for f in forms:
        f = str(f).lower()
        if TAMIL_RE.search(f):
            if f in text:
                return True
        elif " " in f:
            if re.search(rf"\b{re.escape(f)}\b", low):
                return True
        else:
            if f in tokens:
                return True
            if len(f) >= 5 and any(len(t) >= 5 and t[0] == f[0] and fuzz.ratio(t, f) >= 86 for t in tokens):
                return True  # Tanglish spelling variation: milagai / milaghai
    return False


def extract(text: str) -> Extraction:
    g = glossary()
    out = Extraction()
    if not text:
        return out
    for key, forms in g["crop"].items():
        if _match(text, forms):
            out.crops.append(key)
    for key, forms in g["symptom"].items():
        if _match(text, forms):
            out.symptoms.append(key)
    for key, forms in g["leaf_age"].items():
        if _match(text, forms):
            out.leaf_age = key
    for key, forms in g["intent"].items():
        if _match(text, forms):
            out.intents.append(key)
    return out


# --- Speech ------------------------------------------------------------------

def to_wav(path: str) -> str:
    """Telegram voice notes are OGG/Opus; STT wants 16 kHz mono WAV."""
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000", out], check=True)
    return out


class STT:
    def transcribe(self, path: str) -> tuple[str | None, str | None]:
        """Returns (transcript, language_code) or (None, None)."""
        raise NotImplementedError


class SarvamSTT(STT):
    def __init__(self, key: str, model: str):
        self.key, self.model = key, model

    def transcribe(self, path):
        wav = to_wav(path)
        try:
            with open(wav, "rb") as f:
                r = httpx.post(
                    "https://api.sarvam.ai/speech-to-text",
                    headers={"api-subscription-key": self.key},
                    data={"model": self.model, "language_code": "unknown"},
                    files={"file": ("audio.wav", f, "audio/wav")},
                    timeout=60,
                )
            r.raise_for_status()
            j = r.json()
            return (j.get("transcript") or "").strip() or None, j.get("language_code")
        except Exception as e:
            log.warning("Sarvam STT failed: %s", e)
            return None, None
        finally:
            Path(wav).unlink(missing_ok=True)


class NoSTT(STT):
    def transcribe(self, path):
        return None, None


_stt: STT | None = None


def get_stt() -> STT:
    global _stt
    if _stt is None:
        s = get_settings()
        _stt = SarvamSTT(s.sarvam_api_key, s.sarvam_stt_model) if s.stt_provider == "sarvam" and s.sarvam_api_key else NoSTT()
    return _stt


def set_stt(stt: STT | None) -> None:
    global _stt
    _stt = stt


def synthesize(text: str, style: str, out_dir: Path) -> str | None:
    """Optional Tamil/English voice reply (Sarvam Bulbul). Returns a WAV path or None."""
    s = get_settings()
    if not (s.tts_enabled and s.sarvam_api_key):
        return None
    try:
        import base64

        r = httpx.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": s.sarvam_api_key},
            json={"text": text[:1500], "target_language_code": "en-IN" if style == "en" else "ta-IN", "model": s.sarvam_tts_model},
            timeout=60,
        )
        r.raise_for_status()
        audio = base64.b64decode(r.json()["audios"][0])
        out_dir.mkdir(parents=True, exist_ok=True)
        p = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=out_dir).name)
        p.write_bytes(audio)
        return str(p)
    except Exception as e:
        log.warning("TTS failed: %s", e)
        return None
