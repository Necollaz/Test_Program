import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLED_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    BUNDLED_DIR = BASE_DIR

APP_DATA_DIR = Path.home() / "InterviewAssistant" if sys.platform == "darwin" else BASE_DIR

EXTERNAL_QUESTIONS_DIR = BASE_DIR / "questions"
BUNDLED_QUESTIONS_DIR = BUNDLED_DIR / "questions"

QUESTIONS_DIR = (
    EXTERNAL_QUESTIONS_DIR
    if EXTERNAL_QUESTIONS_DIR.exists()
    else BUNDLED_QUESTIONS_DIR
)
RECORDINGS_DIR = APP_DATA_DIR / "recordings"
LOGS_DIR = APP_DATA_DIR / "logs"
QUESTIONS_LOG_PATH = LOGS_DIR / "asked_questions.md"
ANALYSIS_LOG_PATH = LOGS_DIR / "program_analysis.md"

LANGUAGE = "ru"
WHISPER_MODEL = "small"
WHISPER_BEAM_SIZE = 1
WHISPER_INITIAL_PROMPT = (
    "Вопросы собеседования по C#, Unity и ООП. "
    "Термины: ООП, объектно-ориентированное программирование, "
    "инкапсуляция, наследование, полиморфизм, абстракция, MonoBehaviour, "
    "Unity, C#, Jira, WEEEK, Trello, Code Review, ревью кода, задачи, команда."
)

SAMPLE_RATE = 16000
RECORD_SECONDS = 8
MIN_RECORD_SECONDS = 2.0
PARTIAL_TRANSCRIBE_SECONDS = 2.0
SILENCE_STOP_SECONDS = 1.25
SPEECH_RMS_THRESHOLD = 0.0035
AUTO_PREROLL_SECONDS = 1.25
AUTO_TRIGGER_CHUNKS = 1
AUTO_NOISE_MULTIPLIER = 2.4
AUTO_SILENCE_MULTIPLIER = 1.6
AUTO_COOLDOWN_SECONDS = 0.8
AUTO_MIN_VOICE_SECONDS = 0.55
AUTO_MIN_RECOGNIZED_LETTERS = 4
AUTO_FRAGMENT_MIN_SCORE = 70
WHISPER_CPU_THREADS = 4

MIN_SEARCH_SCORE = 50
