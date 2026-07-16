from pathlib import Path
from collections import deque
from collections.abc import Callable
from typing import Any, NamedTuple
import sys

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write

from app.config import (
    AUTO_MIN_VOICE_SECONDS,
    AUTO_NOISE_MULTIPLIER,
    AUTO_PREROLL_SECONDS,
    AUTO_SILENCE_MULTIPLIER,
    AUTO_TRIGGER_CHUNKS,
    MIN_RECORD_SECONDS,
    PARTIAL_TRANSCRIBE_SECONDS,
    RECORDINGS_DIR,
    RECORD_SECONDS,
    SAMPLE_RATE,
    SILENCE_STOP_SECONDS,
    SPEECH_RMS_THRESHOLD,
)

try:
    import soundcard as sc
except ImportError:
    sc = None


class AudioSource(NamedTuple):
    id: str
    label: str
    kind: str
    device_index: int | None = None
    name: str | None = None


PartialAudioCallback = Callable[
    [np.ndarray[Any, np.dtype[np.float32]], int],
    None,
]
StopCallback = Callable[[], bool]
SpeechStartedCallback = Callable[[], None]


def list_audio_sources() -> list[AudioSource]:
    sources: list[AudioSource] = []

    for index, device in enumerate(sd.query_devices()):
        device_info = dict(device)
        input_channels = int(device_info.get("max_input_channels", 0))
        if input_channels <= 0:
            continue

        name = str(device_info.get("name", f"Device {index}"))
        hostapi = _hostapi_name(device_info)
        label_prefix = (
            "Системный звук / Meet"
            if _looks_like_virtual_system_audio(name)
            else "Микрофон/вход"
        )
        sources.append(
            AudioSource(
                id=f"input:{index}",
                label=f"{label_prefix}: {name} ({hostapi})",
                kind="input",
                device_index=index,
            )
        )

    sources.extend(_list_loopback_sources())
    return sources


def record_question(
    seconds: int = RECORD_SECONDS,
    sample_rate: int = SAMPLE_RATE,
    output_path: Path | None = None,
    audio_source_id: str | None = None,
    partial_audio_callback: PartialAudioCallback | None = None,
) -> Path:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        output_path = RECORDINGS_DIR / "current_question.wav"

    audio = _record_question_audio(
        seconds=seconds,
        sample_rate=sample_rate,
        audio_source_id=audio_source_id,
        partial_audio_callback=partial_audio_callback,
        wait_for_speech=False,
        stop_callback=None,
    )
    return _write_audio(output_path, audio, sample_rate)


def listen_for_question(
    seconds: int = RECORD_SECONDS,
    sample_rate: int = SAMPLE_RATE,
    output_path: Path | None = None,
    audio_source_id: str | None = None,
    partial_audio_callback: PartialAudioCallback | None = None,
    stop_callback: StopCallback | None = None,
    speech_started_callback: SpeechStartedCallback | None = None,
) -> Path | None:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        output_path = RECORDINGS_DIR / "auto_question.wav"

    audio = _record_question_audio(
        seconds=seconds,
        sample_rate=sample_rate,
        audio_source_id=audio_source_id,
        partial_audio_callback=partial_audio_callback,
        wait_for_speech=True,
        stop_callback=stop_callback,
        speech_started_callback=speech_started_callback,
    )

    if audio.size == 0:
        return None

    return _write_audio(output_path, audio, sample_rate)


def _record_question_audio(
    seconds: int,
    sample_rate: int,
    audio_source_id: str | None,
    partial_audio_callback: PartialAudioCallback | None,
    wait_for_speech: bool,
    stop_callback: StopCallback | None,
    speech_started_callback: SpeechStartedCallback | None = None,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    source = _find_audio_source(audio_source_id)
    if source and source.kind == "loopback":
        return _record_loopback(
            source,
            seconds,
            sample_rate,
            partial_audio_callback,
            wait_for_speech,
            stop_callback,
            speech_started_callback,
        )

    return _record_input(
        source,
        seconds,
        sample_rate,
        partial_audio_callback,
        wait_for_speech,
        stop_callback,
        speech_started_callback,
    )


def _write_audio(
    output_path: Path,
    audio: np.ndarray[Any, np.dtype[np.float32]],
    sample_rate: int,
) -> Path:
    audio = _prepare_audio(audio)
    audio_int16 = (audio * 32767).astype(np.int16)

    write(output_path, sample_rate, audio_int16)

    return output_path


def _record_input(
    source: AudioSource | None,
    seconds: int,
    sample_rate: int,
    partial_audio_callback: PartialAudioCallback | None,
    wait_for_speech: bool,
    stop_callback: StopCallback | None,
    speech_started_callback: SpeechStartedCallback | None,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    chunks: list[np.ndarray[Any, np.dtype[np.float32]]] = []
    chunk_frames = int(0.25 * sample_rate)
    last_partial_seconds = 0.0
    max_chunks = _max_chunks(seconds, chunk_frames, sample_rate)
    speech_started = not wait_for_speech
    speech_threshold = SPEECH_RMS_THRESHOLD
    silence_threshold = SPEECH_RMS_THRESHOLD
    noise_floor = SPEECH_RMS_THRESHOLD / AUTO_NOISE_MULTIPLIER
    pre_speech_chunks: deque[np.ndarray[Any, np.dtype[np.float32]]] = deque(
        maxlen=_preroll_chunk_count(sample_rate, chunk_frames)
    )
    loud_chunks = 0
    reads = 0

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=source.device_index if source else None,
    ) as stream:
        while True:
            if stop_callback and stop_callback():
                break

            chunk, _overflowed = stream.read(chunk_frames)
            reads += 1

            if not speech_started:
                pre_speech_chunks.append(chunk.copy())
                level = _audio_level(chunk)
                speech_threshold = _speech_threshold(noise_floor)
                if level >= speech_threshold:
                    loud_chunks += 1
                else:
                    loud_chunks = 0
                    noise_floor = _updated_noise_floor(noise_floor, level)

                if loud_chunks < AUTO_TRIGGER_CHUNKS:
                    continue

                speech_started = True
                silence_threshold = _silence_threshold(noise_floor)
                chunks.extend(pre_speech_chunks)
                if speech_started_callback is not None:
                    speech_started_callback()
                last_partial_seconds = _emit_partial_audio_if_needed(
                    chunks,
                    sample_rate,
                    last_partial_seconds,
                    partial_audio_callback,
                )
                continue

            chunks.append(chunk)
            last_partial_seconds = _emit_partial_audio_if_needed(
                chunks,
                sample_rate,
                last_partial_seconds,
                partial_audio_callback,
            )
            if _should_stop_recording(chunks, sample_rate, silence_threshold):
                break

            if len(chunks) >= max_chunks:
                break

            if not wait_for_speech and reads >= max_chunks:
                break

    if not chunks:
        return np.array([], dtype=np.float32)

    if wait_for_speech and not _has_enough_active_audio(
        chunks,
        sample_rate,
        silence_threshold,
    ):
        return np.array([], dtype=np.float32)

    return np.concatenate(chunks, axis=0)


def _record_loopback(
    source: AudioSource,
    seconds: int,
    sample_rate: int,
    partial_audio_callback: PartialAudioCallback | None,
    wait_for_speech: bool,
    stop_callback: StopCallback | None,
    speech_started_callback: SpeechStartedCallback | None,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    if sc is None:
        raise RuntimeError(
            "Для записи системного звука нужна библиотека soundcard. "
            "Запусти build_windows.ps1 на Windows или build_macos.sh на macOS, "
            "чтобы установить зависимости заново."
        )

    microphone = sc.get_microphone(source.name, include_loopback=True)
    chunks: list[np.ndarray[Any, np.dtype[np.float32]]] = []
    chunk_frames = int(0.25 * sample_rate)
    last_partial_seconds = 0.0
    max_chunks = _max_chunks(seconds, chunk_frames, sample_rate)
    speech_started = not wait_for_speech
    speech_threshold = SPEECH_RMS_THRESHOLD
    silence_threshold = SPEECH_RMS_THRESHOLD
    noise_floor = SPEECH_RMS_THRESHOLD / AUTO_NOISE_MULTIPLIER
    pre_speech_chunks: deque[np.ndarray[Any, np.dtype[np.float32]]] = deque(
        maxlen=_preroll_chunk_count(sample_rate, chunk_frames)
    )
    loud_chunks = 0

    with microphone.recorder(samplerate=sample_rate) as recorder:
        while True:
            if stop_callback and stop_callback():
                break

            chunk = recorder.record(numframes=chunk_frames)
            chunk = np.asarray(chunk, dtype=np.float32)

            if not speech_started:
                pre_speech_chunks.append(chunk.copy())
                level = _audio_level(chunk)
                speech_threshold = _speech_threshold(noise_floor)
                if level >= speech_threshold:
                    loud_chunks += 1
                else:
                    loud_chunks = 0
                    noise_floor = _updated_noise_floor(noise_floor, level)

                if loud_chunks < AUTO_TRIGGER_CHUNKS:
                    continue

                speech_started = True
                silence_threshold = _silence_threshold(noise_floor)
                chunks.extend(pre_speech_chunks)
                if speech_started_callback is not None:
                    speech_started_callback()
                last_partial_seconds = _emit_partial_audio_if_needed(
                    chunks,
                    sample_rate,
                    last_partial_seconds,
                    partial_audio_callback,
                )
                continue

            chunks.append(chunk)
            last_partial_seconds = _emit_partial_audio_if_needed(
                chunks,
                sample_rate,
                last_partial_seconds,
                partial_audio_callback,
            )
            if _should_stop_recording(chunks, sample_rate, silence_threshold):
                break

            if len(chunks) >= max_chunks:
                break

    if not chunks:
        return np.array([], dtype=np.float32)

    if wait_for_speech and not _has_enough_active_audio(
        chunks,
        sample_rate,
        silence_threshold,
    ):
        return np.array([], dtype=np.float32)

    return np.concatenate(chunks, axis=0)


def _emit_partial_audio_if_needed(
    chunks: list[np.ndarray[Any, np.dtype[np.float32]]],
    sample_rate: int,
    last_partial_seconds: float,
    partial_audio_callback: PartialAudioCallback | None,
) -> float:
    if partial_audio_callback is None:
        return last_partial_seconds

    total_frames = sum(chunk.shape[0] for chunk in chunks)
    recorded_seconds = total_frames / sample_rate
    if recorded_seconds - last_partial_seconds < PARTIAL_TRANSCRIBE_SECONDS:
        return last_partial_seconds

    audio = _prepare_audio(np.concatenate(chunks, axis=0))
    partial_audio_callback(audio.copy(), sample_rate)
    return recorded_seconds


def _max_chunks(seconds: int, chunk_frames: int, sample_rate: int) -> int:
    total_frames = int(seconds * sample_rate)
    return max(1, int(np.ceil(total_frames / chunk_frames)))


def _preroll_chunk_count(sample_rate: int, chunk_frames: int) -> int:
    preroll_frames = int(AUTO_PREROLL_SECONDS * sample_rate)
    return max(1, int(np.ceil(preroll_frames / chunk_frames)))


def _should_stop_recording(
    chunks: list[np.ndarray[Any, np.dtype[np.float32]]],
    sample_rate: int,
    silence_threshold: float,
) -> bool:
    total_frames = sum(chunk.shape[0] for chunk in chunks)
    recorded_seconds = total_frames / sample_rate
    if recorded_seconds < MIN_RECORD_SECONDS:
        return False

    speech_seen = any(_audio_level(chunk) >= silence_threshold for chunk in chunks)
    if not speech_seen:
        return False

    silence_chunks = int(np.ceil(SILENCE_STOP_SECONDS / 0.25))
    recent_chunks = chunks[-silence_chunks:]
    return all(_audio_level(chunk) < silence_threshold for chunk in recent_chunks)


def _speech_threshold(noise_floor: float) -> float:
    return max(SPEECH_RMS_THRESHOLD, noise_floor * AUTO_NOISE_MULTIPLIER)


def _silence_threshold(noise_floor: float) -> float:
    return max(SPEECH_RMS_THRESHOLD, noise_floor * AUTO_SILENCE_MULTIPLIER)


def _updated_noise_floor(noise_floor: float, level: float) -> float:
    if level <= 0:
        return noise_floor

    return (noise_floor * 0.92) + (level * 0.08)


def _has_enough_active_audio(
    chunks: list[np.ndarray[Any, np.dtype[np.float32]]],
    sample_rate: int,
    silence_threshold: float,
) -> bool:
    active_frames = sum(
        chunk.shape[0]
        for chunk in chunks
        if _audio_level(chunk) >= silence_threshold
    )
    return (active_frames / sample_rate) >= AUTO_MIN_VOICE_SECONDS


def _prepare_audio(
    audio: np.ndarray[Any, np.dtype[np.float32]],
) -> np.ndarray[Any, np.dtype[np.float32]]:
    audio = np.asarray(audio, dtype=np.float32)
    audio = np.squeeze(audio)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    audio = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0.003:
        audio = audio * min(4.0, 0.95 / peak)

    return np.clip(audio, -1.0, 1.0)


def _audio_level(audio: np.ndarray[Any, np.dtype[np.float32]]) -> float:
    prepared_audio = np.asarray(audio, dtype=np.float32)
    if prepared_audio.ndim > 1:
        prepared_audio = prepared_audio.mean(axis=1)

    if prepared_audio.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(np.square(prepared_audio))))


def _find_audio_source(audio_source_id: str | None) -> AudioSource | None:
    if not audio_source_id:
        return None

    for source in list_audio_sources():
        if source.id == audio_source_id:
            return source

    raise RuntimeError(f"Выбранное аудио-устройство не найдено: {audio_source_id}")


def _list_loopback_sources() -> list[AudioSource]:
    if sc is None:
        return []

    if sys.platform == "darwin":
        return []

    try:
        speaker_names = {speaker.name for speaker in sc.all_speakers()}
        microphones = sc.all_microphones(include_loopback=True)
    except Exception:
        return []

    sources: list[AudioSource] = []
    seen_names: set[str] = set()

    for microphone in microphones:
        name = microphone.name
        if name not in speaker_names or name in seen_names:
            continue

        seen_names.add(name)
        sources.append(
            AudioSource(
                id=f"loopback:{len(sources)}",
                label=f"Системный звук / Meet: {name}",
                kind="loopback",
                name=name,
            )
        )

    return sources


def _hostapi_name(device_info: dict[str, Any]) -> str:
    try:
        hostapi_index = int(device_info.get("hostapi", -1))
        return str(sd.query_hostapis(hostapi_index)["name"])
    except Exception:
        return "Audio"


def _looks_like_virtual_system_audio(name: str) -> bool:
    normalized_name = name.lower()
    markers = [
        "blackhole",
        "soundflower",
        "loopback",
        "vb-cable",
        "virtual audio",
        "aggregate device",
        "multi-output device",
    ]
    return any(marker in normalized_name for marker in markers)
