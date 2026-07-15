from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write

from app.config import RECORDINGS_DIR, RECORD_SECONDS, SAMPLE_RATE


def record_question(
    seconds: int = RECORD_SECONDS,
    sample_rate: int = SAMPLE_RATE,
    output_path: Path | None = None,
) -> Path:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        output_path = RECORDINGS_DIR / "current_question.wav"

    audio = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )

    sd.wait()

    audio = np.squeeze(audio)
    audio = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio * 32767).astype(np.int16)

    write(output_path, sample_rate, audio_int16)

    return output_path