import html
import re
from typing import Any

from rapidfuzz import fuzz

from app.config import MIN_SEARCH_SCORE
from app.qa_loader import normalize_text


STOP_WORDS = {
    "а",
    "был",
    "была",
    "были",
    "было",
    "вашей",
    "ваш",
    "ваша",
    "ваше",
    "ваши",
    "в",
    "вас",
    "вам",
    "вы",
    "для",
    "и",
    "из",
    "или",
    "как",
    "какая",
    "какие",
    "каким",
    "какой",
    "компания",
    "компании",
    "команде",
    "которого",
    "которое",
    "которой",
    "которые",
    "который",
    "ли",
    "мне",
    "можете",
    "можешь",
    "над",
    "на",
    "об",
    "о",
    "организован",
    "организована",
    "организовано",
    "организованы",
    "организовывался",
    "организовывалась",
    "от",
    "по",
    "почему",
    "проводилась",
    "проводился",
    "проводилось",
    "проводили",
    "процесс",
    "процессы",
    "приходилось",
    "приходилось ли",
    "про",
    "проходив",
    "проходил",
    "проходила",
    "проходило",
    "проходили",
    "расскажи",
    "расскажите",
    "с",
    "самостоятельно",
    "у",
    "что",
    "это",
}

WORD_PATTERN = re.compile(r"[a-zа-я0-9#]+", re.IGNORECASE)
WORD_ENDINGS = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ыми",
    "ими",
    "ься",
    "ся",
    "ов",
    "ев",
    "ей",
    "ой",
    "ий",
    "ый",
    "ая",
    "ое",
    "ее",
    "ые",
    "ие",
    "ам",
    "ям",
    "ах",
    "ях",
    "ом",
    "ем",
    "ую",
    "юю",
    "а",
    "я",
    "ы",
    "и",
    "у",
    "ю",
    "е",
)


def search(
    query: str,
    items: list[dict[str, Any]],
    limit: int = 5,
    min_score: int = MIN_SEARCH_SCORE,
) -> list[dict[str, Any]]:
    normalized_query = normalize_text(query)
    content_query = _content_text(normalized_query)
    query_terms = _important_terms(normalized_query)

    if not normalized_query:
        return []

    results: list[dict[str, Any]] = []

    for item in items:
        normalized_question = normalize_text(item.get("question", ""))
        exact_title_match = normalized_query == normalized_question
        content_question = _content_text(normalized_question)
        search_text = item.get("search_text", "")
        content_search_text = _content_text(search_text)
        question_terms = _important_terms(normalized_question)
        search_terms = _important_terms(search_text)

        question_score = fuzz.WRatio(
            normalized_query,
            normalized_question,
        )

        question_token_score = fuzz.token_set_ratio(
            normalized_query,
            normalized_question,
        )

        partial_question_score = fuzz.partial_token_set_ratio(
            normalized_query,
            normalized_question,
        )

        full_text_score = fuzz.token_set_ratio(
            normalized_query,
            search_text,
        )

        content_question_score = fuzz.token_set_ratio(
            content_query,
            content_question,
        )

        content_full_text_score = fuzz.token_set_ratio(
            content_query,
            content_search_text,
        )

        question_overlap_score = _overlap_score(query_terms, question_terms)
        full_text_overlap_score = _overlap_score(query_terms, search_terms)

        title_similarity_score = int(
            question_score * 0.45
            + question_token_score * 0.30
            + partial_question_score * 0.15
            + content_question_score * 0.10
        )
        body_similarity_score = max(
            full_text_score,
            content_full_text_score,
            full_text_overlap_score,
        )
        title_meaning_score = max(content_question_score, question_overlap_score)

        final_score = max(
            int(title_similarity_score * 0.70 + body_similarity_score * 0.30),
            int(title_meaning_score * 0.85 + body_similarity_score * 0.15),
        )
        final_score = _apply_required_term_penalty(
            final_score,
            query_terms,
            question_terms,
            search_terms,
        )

        result = dict(item)
        result["score"] = 100 if exact_title_match else final_score
        result["_exact_title_match"] = exact_title_match
        results.append(result)

    results.sort(
        key=lambda item: (item.get("_exact_title_match", False), item["score"]),
        reverse=True,
    )
    confident_results = [item for item in results if item["score"] >= min_score]
    return (confident_results or results)[:limit]


def _content_text(text: str) -> str:
    words = _words(text)
    useful_words = [word for word in words if word not in STOP_WORDS]
    return " ".join(useful_words)


def _important_terms(text: str) -> set[str]:
    terms = set()
    stop_terms = {_word_key(word) for word in STOP_WORDS}

    for word in _words(text):
        key = _word_key(word)
        if len(key) < 2 or word in STOP_WORDS or key in stop_terms:
            continue

        terms.add(key)

    return terms


def _words(text: str) -> list[str]:
    return WORD_PATTERN.findall(normalize_text(text))


def _word_key(word: str) -> str:
    if word in {"c#", "csharp", "unity", "ооп"}:
        return word

    synonym_prefixes = {
        "созда": "созда",
        "созд": "созда",
        "задач": "задач",
        "таск": "задач",
        "тикет": "задач",
        "ticket": "задач",
        "jira": "задач",
        "trello": "задач",
        "weeek": "задач",
        "week": "задач",
        "джира": "задач",
        "жира": "задач",
        "трелло": "задач",
        "wee": "задач",
        "таски": "задач",
        "code": "код",
        "код": "код",
        "кода": "код",
        "провер": "ревью",
        "просмотр": "ревью",
        "ревю": "ревью",
        "ревью": "ревью",
        "review": "ревью",
        "reviews": "ревью",
        "merge": "merge",
        "request": "merge",
        "pull": "merge",
        "pr": "merge",
        "мр": "merge",
        "mr": "merge",
        "пул": "merge",
        "мерж": "merge",
        "стратег": "strategy",
        "strategy": "strategy",
        "паттерн": "паттерн",
        "pattern": "паттерн",
        "получ": "получ",
        "выдав": "получ",
        "распредел": "получ",
        "оцен": "оцен",
        "срок": "срок",
        "команд": "команд",
        "состав": "состав",
    }

    for prefix, key in synonym_prefixes.items():
        if word.startswith(prefix):
            return key

    for ending in WORD_ENDINGS:
        if len(word) > len(ending) + 3 and word.endswith(ending):
            return word[: -len(ending)]

    return word


def _overlap_score(query_terms: set[str], target_terms: set[str]) -> int:
    if not query_terms:
        return 0

    matched_terms = query_terms & target_terms
    return int(len(matched_terms) / len(query_terms) * 100)


def _apply_required_term_penalty(
    score: int,
    query_terms: set[str],
    question_terms: set[str],
    search_terms: set[str],
) -> int:
    target_terms = question_terms | search_terms

    if "ревью" in query_terms:
        if "ревью" in question_terms:
            return score
        if "ревью" in target_terms:
            return min(score, 60)
        return min(score, 45)

    if {"созда", "задач"}.issubset(query_terms) and not {
        "созда",
        "задач",
    }.issubset(target_terms):
        return min(score, 55)

    return score


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


def format_answer_html(item: dict[str, Any]) -> str:
    question = html.escape(str(item.get("question", "")))
    score = int(item.get("score", 0))
    answer = _combine_answer_parts(item)

    return f"""
<div style="font-family: Segoe UI, Arial, sans-serif; font-size: 15px; line-height: 1.45;">
  <div><b>Вопрос:</b> {question}</div>
  <div><b>Совпадение:</b> {score}%</div>

  <div style="height: 14px;"></div>
  <div style="font-size: 19px; font-weight: 700; margin-bottom: 8px;">Ответ:</div>
  <div style="white-space: pre-wrap;">{html.escape(answer)}</div>
</div>
""".strip()


def _combine_answer_parts(item: dict[str, Any]) -> str:
    parts = []

    short_answer = item.get("short_answer", "")
    if short_answer:
        parts.append(str(short_answer).strip())

    full_answer = item.get("full_answer", "")
    if full_answer:
        parts.append(str(full_answer).strip())

    example = item.get("example", "")
    if example:
        parts.append(str(example).strip())

    return "\n\n".join(part for part in parts if part)
