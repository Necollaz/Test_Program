from pathlib import Path
import re
from threading import Lock

from faster_whisper import WhisperModel

from app.config import (
    LANGUAGE,
    WHISPER_BEAM_SIZE,
    WHISPER_INITIAL_PROMPT,
    WHISPER_MODEL,
)


_model: WhisperModel | None = None
_model_lock = Lock()


def get_model() -> WhisperModel:
    global _model

    with _model_lock:
        if _model is None:
            _model = WhisperModel(
                WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
            )

    return _model


def transcribe_audio(audio_path: Path) -> str:
    model = get_model()

    try:
        segments, _info = model.transcribe(
            str(audio_path),
            language=LANGUAGE,
            beam_size=WHISPER_BEAM_SIZE,
            initial_prompt=WHISPER_INITIAL_PROMPT,
            condition_on_previous_text=False,
            vad_filter=True,
        )
        text_parts = [
            segment.text.strip() for segment in segments if segment.text.strip()
        ]
    except Exception as error:
        if not _is_missing_vad_asset_error(error):
            raise

        segments, _info = model.transcribe(
            str(audio_path),
            language=LANGUAGE,
            beam_size=WHISPER_BEAM_SIZE,
            initial_prompt=WHISPER_INITIAL_PROMPT,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        text_parts = [
            segment.text.strip() for segment in segments if segment.text.strip()
        ]

    return _correct_domain_terms(" ".join(text_parts).strip())


def _is_missing_vad_asset_error(error: Exception) -> bool:
    message = str(error).lower()
    return "silero" in message and (
        "no suchfile" in message
        or "no_suchfile" in message
        or "file doesn't exist" in message
    )


def _correct_domain_terms(text: str) -> str:
    corrections = [
        (r"\bлупое\b", "ООП"),
        (r"\bлупо\b", "ООП"),
        (r"\bо[\s\-.]*о[\s\-.]*п\b", "ООП"),
        (r"\bси[\s-]*шарп\b", "C#"),
        (r"\bc[\s-]*sharp\b", "C#"),
        (r"\bс[\s-]*sharp\b", "C#"),
        (r"\bюнити\b", "Unity"),
        (r"\bю\s+нити\b", "Unity"),
    ]

    corrected = text
    for pattern, replacement in corrections:
        corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)

    return corrected
