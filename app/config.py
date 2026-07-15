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
WHISPER_BEAM_SIZE = 1
WHISPER_INITIAL_PROMPT = (
    "Вопросы собеседования по C#, Unity и ООП. "
    "Термины: ООП, объектно-ориентированное программирование, "
    "инкапсуляция, наследование, полиморфизм, абстракция, MonoBehaviour."
)

SAMPLE_RATE = 16000
RECORD_SECONDS = 4

MIN_SEARCH_SCORE = 50
