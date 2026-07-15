import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLED_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    BUNDLED_DIR = BASE_DIR

EXTERNAL_QUESTIONS_DIR = BASE_DIR / "questions"
BUNDLED_QUESTIONS_DIR = BUNDLED_DIR / "questions"

QUESTIONS_DIR = (
    EXTERNAL_QUESTIONS_DIR
    if EXTERNAL_QUESTIONS_DIR.exists()
    else BUNDLED_QUESTIONS_DIR
)
RECORDINGS_DIR = BASE_DIR / "recordings"

LANGUAGE = "ru"
WHISPER_MODEL = "small"

SAMPLE_RATE = 16000
RECORD_SECONDS = 6

MIN_SEARCH_SCORE = 50
