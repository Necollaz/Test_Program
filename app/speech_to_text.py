from pathlib import Path
import os
import re
from threading import Lock

import numpy as np
from faster_whisper import WhisperModel
from scipy.io.wavfile import write

from app.config import (
    AUTO_MIN_RECOGNIZED_LETTERS,
    LANGUAGE,
    WHISPER_BEAM_SIZE,
    WHISPER_CPU_THREADS,
    WHISPER_INITIAL_PROMPT,
    WHISPER_MODEL,
)


_model: WhisperModel | None = None
_model_lock = Lock()
_transcribe_lock = Lock()


def get_model() -> WhisperModel:
    global _model

    with _model_lock:
        if _model is None:
            _model = WhisperModel(
                WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
                cpu_threads=_cpu_threads(),
                num_workers=1,
            )

    return _model


def _cpu_threads() -> int:
    available_threads = os.cpu_count() or WHISPER_CPU_THREADS
    return max(1, min(WHISPER_CPU_THREADS, available_threads - 1))


def transcribe_audio(audio_path: Path) -> str:
    with _transcribe_lock:
        return _transcribe_audio_locked(audio_path, prefer_vad=False)


def transcribe_auto_audio(audio_path: Path) -> str:
    details = transcribe_auto_audio_details(audio_path)
    return str(details["text"])


def transcribe_auto_audio_details(audio_path: Path) -> dict[str, str]:
    with _transcribe_lock:
        raw_text = _transcribe_audio_locked(audio_path, prefer_vad=True)
        if not raw_text:
            return {
                "raw_text": "",
                "text": "",
                "reject_reason": "empty_after_vad",
            }

        if not _looks_like_question_text(raw_text):
            return {
                "raw_text": raw_text,
                "text": "",
                "reject_reason": "too_short_or_noise_text",
            }

        return {
            "raw_text": raw_text,
            "text": raw_text,
            "reject_reason": "",
        }


def transcribe_audio_samples(
    audio: np.ndarray,
    sample_rate: int,
    output_path: Path,
) -> str:
    audio = np.asarray(audio, dtype=np.float32)
    audio = np.squeeze(audio)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    audio = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio * 32767).astype(np.int16)
    write(output_path, sample_rate, audio_int16)
    return transcribe_audio(output_path)


def _transcribe_audio_locked(audio_path: Path, prefer_vad: bool) -> str:
    model = get_model()

    if prefer_vad:
        try:
            text = _transcribe_with_vad(model, audio_path, vad_filter=True)
        except Exception as error:
            if not _is_missing_vad_asset_error(error):
                raise

            text = ""

        if text:
            return _correct_domain_terms(text)

    try:
        text = _transcribe_with_vad(model, audio_path, vad_filter=False)
    except Exception as error:
        if not _is_missing_vad_asset_error(error):
            raise

        text = _transcribe_with_vad(model, audio_path, vad_filter=False)

    if not text:
        try:
            text = _transcribe_with_vad(model, audio_path, vad_filter=True)
        except Exception as error:
            if not _is_missing_vad_asset_error(error):
                raise

    return _correct_domain_terms(text)


def _looks_like_question_text(text: str) -> bool:
    normalized_text = re.sub(r"\s+", " ", text).strip().lower()
    if not normalized_text:
        return False

    noise_words = {
        "а",
        "ах",
        "мм",
        "м",
        "эм",
        "ээ",
        "угу",
        "ага",
        "ой",
        "ох",
        "да",
        "нет",
    }
    if normalized_text in noise_words:
        return False

    letters = re.findall(r"[a-zа-яё#]+", normalized_text, flags=re.IGNORECASE)
    letter_count = sum(len(word.replace("#", "")) for word in letters)
    return letter_count >= AUTO_MIN_RECOGNIZED_LETTERS


def _transcribe_with_vad(
    model: WhisperModel,
    audio_path: Path,
    vad_filter: bool,
) -> str:
    segments, _info = model.transcribe(
        str(audio_path),
        language=LANGUAGE,
        beam_size=WHISPER_BEAM_SIZE,
        initial_prompt=WHISPER_INITIAL_PROMPT,
        condition_on_previous_text=False,
        vad_filter=vad_filter,
    )
    text_parts = [segment.text.strip() for segment in segments if segment.text.strip()]
    return " ".join(text_parts).strip()


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
        (r"\bкод[\s-]*ревью\b", "Code Review"),
        (r"\bкод[\s-]*review\b", "Code Review"),
        (r"\bcode[\s-]*ревью\b", "Code Review"),
        (r"\bкод[\s-]*ревю\b", "Code Review"),
        (r"\bджир[аеуы]?\b", "Jira"),
        (r"\bжир[аеуы]?\b", "Jira"),
        (r"\bтрелл[оа]\b", "Trello"),
        (r"\bпаттерн\s+стратеги[яи]\b", "паттерн Strategy"),
        (r"\bстратеги[яи]\b", "Strategy"),
    ]

    corrected = text
    for pattern, replacement in corrections:
        corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)

    return corrected
