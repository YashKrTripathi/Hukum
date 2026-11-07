import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

import time as _t
TZ_NAME = os.getenv("TZ_NAME", "Asia/Kolkata")
os.environ["TZ"] = TZ_NAME            # server clock -> your timezone (Linux)
if hasattr(_t, "tzset"):
    _t.tzset()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-5-5"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")          # speech-to-text (free tier), Whisper
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")      # alternative speech-to-text
TTS_VOICE_HI = os.getenv("TTS_VOICE_HI", "hi-IN-SwaraNeural")
TTS_VOICE_EN = os.getenv("TTS_VOICE_EN", "en-IN-NeerjaNeural")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

TG_API_ID = int(os.getenv("TG_API_ID") or 0)
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_CALL_TARGET = os.getenv("TG_CALL_TARGET", "")

NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
LEETCODE_USERNAME = os.getenv("LEETCODE_USERNAME", "")

MORNING_TIME =os.getenv("MORNING_TIME", "07:30")
DEFAULT_STUDY_TIME = os.getenv("DEFAULT_STUDY_TIME", "19:00")

# Goals
JAVA_DEADLINE = date(2027, 1, 15)    # finish the Udemy course (exam weeks are skipped automatically)
FINAL_DEADLINE = date(2027, 3, 31)   # Striver sheet + 300 LeetCode done
BUFFER_DAYS = 10                     # finish early; last days are revision
TARGET_LEETCODE = 300
DAILY_TARGET_MINUTES = 180           # study minutes expected on a normal day

DB_PATH = os.path.join(os.path.dirname(__file__), "placement.db")
