from pathlib import Path
from typing import Any

from app.config import QUESTIONS_DIR


SECTION_NAMES = {
    "Ответ": "short_answer",
    "Краткий ответ": "short_answer",
    "Развернутый ответ": "full_answer",
    "Пример": "example",
    "Теги": "tags",
    "Уровень": "level",
    "Варианты": "aliases",
    "Синонимы": "aliases",
    "Ключевые слова": "keywords",
}


def load_questions(questions_dir: Path = QUESTIONS_DIR) -> list[dict[str, Any]]:
    questions_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []

    for file_path in sorted(questions_dir.glob("*.md")):
        text = file_path.read_text(encoding="utf-8")
        items.extend(parse_markdown_file(text, file_path.name))

    return items


def parse_markdown_file(text: str, source: str) -> list[dict[str, Any]]:
    blocks = split_question_blocks(text)
    items: list[dict[str, Any]] = []

    for block in blocks:
        item = parse_question_block(block, source)
        if item["question"] and item["short_answer"]:
            items.append(item)

    return items


def split_question_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []

    for line in text.splitlines():
        if line.startswith("# "):
            if current:
                blocks.append("\n".join(current).strip())
            current = [line]
        else:
            if current:
                current.append(line)

    if current:
        blocks.append("\n".join(current).strip())

    return blocks


def parse_question_block(block: str, source: str) -> dict[str, Any]:
    lines = block.splitlines()
    question = lines[0].replace("#", "", 1).strip() if lines else ""

    sections: dict[str, list[str]] = {
        "short_answer": [],
        "full_answer": [],
        "example": [],
        "tags": [],
        "level": [],
        "aliases": [],
        "keywords": [],
    }

    current_section: str | None = "short_answer"

    for raw_line in lines[1:]:
        line = raw_line.strip()

        if not line and not sections[current_section]:
            continue

        section_key = get_section_key(line)
        if section_key:
            current_section = section_key
            value_after_colon = line.split(":", 1)[1].strip()
            if value_after_colon:
                sections[current_section].append(value_after_colon)
            continue

        if current_section:
            sections[current_section].append(raw_line)

    short_answer = clean_text("\n".join(sections["short_answer"]))
    full_answer = clean_text("\n".join(sections["full_answer"]))
    example = clean_text("\n".join(sections["example"]))
    tags = parse_tags(clean_text("\n".join(sections["tags"])))
    level = clean_text("\n".join(sections["level"]))
    aliases = clean_text("\n".join(sections["aliases"]))
    keywords = clean_text("\n".join(sections["keywords"]))

    search_text = " ".join(
        [
            question,
            aliases,
            keywords,
            short_answer,
            full_answer,
            example,
            " ".join(tags),
            level,
        ]
    )

    return {
        "question": question,
        "short_answer": short_answer,
        "full_answer": full_answer,
        "example": example,
        "tags": tags,
        "level": level,
        "aliases": aliases,
        "keywords": keywords,
        "source": source,
        "search_text": normalize_text(search_text),
    }


def get_section_key(line: str) -> str | None:
    for section_name, key in SECTION_NAMES.items():
        if line.lower().startswith(section_name.lower() + ":"):
            return key
    return None


def parse_tags(text: str) -> list[str]:
    if not text:
        return []

    return [tag.strip() for tag in text.split(",") if tag.strip()]


def clean_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def normalize_text(text: str) -> str:
    normalized = text.lower().replace("ё", "е")

    replacements = {
        "лупое": "ооп",
        "лупо": "ооп",
        "о о п": "ооп",
        "о-о-п": "ооп",
        "о.о.п": "ооп",
        "объектно ориентированное": "объектно-ориентированное",
        "си шарп": "csharp",
        "си-шарп": "csharp",
        "c sharp": "csharp",
        "с sharp": "csharp",
        "ю нити": "unity",
        "юнити": "unity",
    }

    for source, target in replacements.items():
        normalized = normalized.replace(source, target)

    return " ".join(normalized.split())
