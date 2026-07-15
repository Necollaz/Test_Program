from pathlib import Path

from faster_whisper import WhisperModel

from app.config import LANGUAGE, WHISPER_MODEL


_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model

    if _model is None:
        _model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        )

    return _model


def transcribe_audio(audio_path: Path) -> str:
    model = get_model()

    segments, _info = model.transcribe(
        str(audio_path),
        language=LANGUAGE,
        beam_size=5,
        vad_filter=True,
    )

    text_parts = [segment.text.strip() for segment in segments if segment.text.strip()]
    return " ".join(text_parts).strip()