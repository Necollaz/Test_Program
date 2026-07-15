from typing import Any

from rapidfuzz import fuzz

from app.config import MIN_SEARCH_SCORE
from app.qa_loader import normalize_text


def search(
    query: str,
    items: list[dict[str, Any]],
    limit: int = 5,
    min_score: int = MIN_SEARCH_SCORE,
) -> list[dict[str, Any]]:
    normalized_query = normalize_text(query)

    if not normalized_query:
        return []

    results: list[dict[str, Any]] = []

    for item in items:
        question_score = fuzz.WRatio(
            normalized_query,
            normalize_text(item.get("question", "")),
        )

        full_text_score = fuzz.token_set_ratio(
            normalized_query,
            item.get("search_text", ""),
        )

        final_score = int(question_score * 0.65 + full_text_score * 0.35)

        if final_score >= min_score:
            result = dict(item)
            result["score"] = final_score
            results.append(result)

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def format_answer(item: dict[str, Any]) -> str:
    parts = []

    parts.append(f"Вопрос: {item.get('question', '')}")
    parts.append(f"Совпадение: {item.get('score', 0)}%")

    short_answer = item.get("short_answer", "")
    if short_answer:
        parts.append("\nКраткий ответ:")
        parts.append(short_answer)

    full_answer = item.get("full_answer", "")
    if full_answer:
        parts.append("\nРазвернутый ответ:")
        parts.append(full_answer)

    example = item.get("example", "")
    if example:
        parts.append("\nПример:")
        parts.append(example)

    tags = item.get("tags", [])
    if tags:
        parts.append("\nТеги:")
        parts.append(", ".join(tags))

    level = item.get("level", "")
    if level:
        parts.append("\nУровень:")
        parts.append(level)

    source = item.get("source", "")
    if source:
        parts.append("\nИсточник:")
        parts.append(source)

    return "\n".join(parts)