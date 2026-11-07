"""Speech in/out. STT: Groq or OpenAI Whisper (handles Hindi/Hinglish/English).
TTS: edge-tts (free Microsoft neural voices, incl. Hindi and Indian English)."""
import os
import re
import httpx
from config import GROQ_API_KEY, OPENAI_API_KEY, TTS_VOICE_HI, TTS_VOICE_EN

HINT = "Hinglish, Hindi or English. Topics: DSA, Java, LeetCode, Striver sheet, exams, cloud, study plan."


def stt_available() -> bool:
    return bool(GROQ_API_KEY or OPENAI_API_KEY)


async def transcribe(path: str) -> str:
    if GROQ_API_KEY:
        url, key, model = "https://api.groq.com/openai/v1/audio/transcriptions", GROQ_API_KEY, "whisper-large-v3-turbo"
    elif OPENAI_API_KEY:
        url, key, model = "https://api.openai.com/v1/audio/transcriptions", OPENAI_API_KEY, "whisper-1"
    else:
        raise RuntimeError("Set GROQ_API_KEY (free) in .env to understand voice notes")
    async with httpx.AsyncClient(timeout=90) as c:
        with open(path, "rb") as f:
            r = await c.post(url, headers={"Authorization": f"Bearer {key}"},
                             data={"model": model, "prompt": HINT, "response_format": "json"},
                             files={"file": (os.path.basename(path), f, "audio/ogg")})
    r.raise_for_status()
    return r.json()["text"].strip()


def _clean(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"[^\w\s.,!?'\-:%()ऀ-ॿ]", " ", text)


async def speak(text: str, out_path: str):
    """Writes an mp3. Devanagari text -> Hindi voice, else Indian English voice."""
    import edge_tts
    voice = TTS_VOICE_HI if re.search(r"[ऀ-ॿ]", text) else TTS_VOICE_EN
    await edge_tts.Communicate(_clean(text), voice).save(out_path)
