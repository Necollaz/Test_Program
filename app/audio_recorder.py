from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write

from app.config import RECORDINGS_DIR, RECORD_SECONDS, SAMPLE_RATE

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
) -> Path:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        output_path = RECORDINGS_DIR / "current_question.wav"

    source = _find_audio_source(audio_source_id)
    if source and source.kind == "loopback":
        audio = _record_loopback(source, seconds, sample_rate)
    else:
        audio = _record_input(source, seconds, sample_rate)

    audio = np.squeeze(audio)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    audio = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio * 32767).astype(np.int16)

    write(output_path, sample_rate, audio_int16)

    return output_path


def _record_input(
    source: AudioSource | None,
    seconds: int,
    sample_rate: int,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    audio = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=source.device_index if source else None,
    )
    sd.wait()
    return audio


def _record_loopback(
    source: AudioSource,
    seconds: int,
    sample_rate: int,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    if sc is None:
        raise RuntimeError(
            "Для записи системного звука нужна библиотека soundcard. "
            "Запусти build_windows.ps1 на Windows или build_macos.sh на macOS, "
            "чтобы установить зависимости заново."
        )

    microphone = sc.get_microphone(source.name, include_loopback=True)
    with microphone.recorder(samplerate=sample_rate) as recorder:
        audio = recorder.record(numframes=int(seconds * sample_rate))

    return np.asarray(audio, dtype=np.float32)


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
