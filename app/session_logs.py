from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any

from app.config import ANALYSIS_LOG_PATH, LOGS_DIR, QUESTIONS_LOG_PATH


_log_lock = Lock()


def log_question(
    mode: str,
    recognized_text: str,
    results: list[dict[str, Any]],
    audio_source: str,
    metrics: dict[str, Any] | None = None,
) -> None:
    text = recognized_text.strip()
    if not text:
        return

    best_result = results[0] if results else {}
    lines = [
        f"## {_timestamp()}",
        "",
        f"- Режим: {mode}",
        f"- Источник: {audio_source or 'не указан'}",
        f"- Распознанный вопрос: {text}",
    ]

    if best_result:
        score = int(best_result.get("score", 0))
        lines.extend(
            [
                f"- Лучшее совпадение: {score}%",
                f"- Надежность: {_reliability_label(score)}",
                f"- Найденный вопрос: {best_result.get('question', '')}",
            ]
        )
    else:
        lines.append("- Лучшее совпадение: не найдено")

    if metrics:
        lines.append(f"- Время обработки: {_format_seconds(metrics.get('total_seconds'))}")
        for key in (
            "waiting_seconds",
            "record_seconds",
            "transcribe_seconds",
            "search_seconds",
        ):
            if key in metrics:
                lines.append(f"- {_metric_label(key)}: {_format_metric(metrics[key])}")

    _append_block(QUESTIONS_LOG_PATH, "Журнал заданных вопросов", lines)


def log_analysis(
    event: str,
    mode: str,
    audio_source: str = "",
    recognized_text: str = "",
    results: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
    details: str = "",
) -> None:
    best_result = results[0] if results else {}
    lines = [
        f"## {_timestamp()}",
        "",
        f"- Событие: {event}",
        f"- Режим: {mode}",
    ]

    if audio_source:
        lines.append(f"- Источник: {audio_source}")

    if recognized_text.strip():
        lines.append(f"- Распознанный текст: {recognized_text.strip()}")

    if best_result:
        score = int(best_result.get("score", 0))
        lines.extend(
            [
                f"- Лучшее совпадение: {score}%",
                f"- Надежность: {_reliability_label(score)}",
                f"- Найденный вопрос: {best_result.get('question', '')}",
                f"- Топ совпадений: {_format_top_results(results or [])}",
            ]
        )

    if metrics:
        for key, value in metrics.items():
            lines.append(f"- {_metric_label(key)}: {_format_metric(value)}")

    if details:
        lines.append(f"- Детали: {details.strip()}")

    _append_block(ANALYSIS_LOG_PATH, "Технический журнал работы программы", lines)


def _append_block(path: Any, title: str, lines: list[str]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    with _log_lock:
        is_new_file = not path.exists()
        with path.open("a", encoding="utf-8") as file:
            if is_new_file:
                file.write(f"# {title}\n\n")

            file.write("\n".join(lines))
            file.write("\n\n")


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _format_top_results(results: list[dict[str, Any]]) -> str:
    formatted = []
    for result in results[:3]:
        formatted.append(f"{result.get('score', 0)}% - {result.get('question', '')}")

    return "; ".join(formatted) if formatted else "нет"


def _reliability_label(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 70:
        return "medium"
    return "low"


def _format_seconds(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f} сек"

    return "не измерено"


def _format_metric(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f} сек"

    return str(value)


def _metric_label(key: str) -> str:
    labels = {
        "audio_source_id": "ID источника",
        "waiting_seconds": "Ожидание речи",
        "record_seconds": "Запись вопроса",
        "listen_seconds": "Ожидание + запись",
        "transcribe_seconds": "Распознавание",
        "search_seconds": "Поиск ответа",
        "total_seconds": "Полный цикл",
        "used_partial_fallback": "Использован частичный текст",
        "raw_recognized_text": "Raw-текст",
        "reject_reason": "Причина отбраковки",
    }
    return labels.get(key, key)
