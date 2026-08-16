from __future__ import annotations

import json
import re

from .models import Annotation, RecognizedProblem


def _unescape_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def _superscript(value: str) -> str:
    table = str.maketrans(
        {
            "0": "⁰",
            "1": "¹",
            "2": "²",
            "3": "³",
            "4": "⁴",
            "5": "⁵",
            "6": "⁶",
            "7": "⁷",
            "8": "⁸",
            "9": "⁹",
            "+": "⁺",
            "-": "⁻",
            "(": "⁽",
            ")": "⁾",
        }
    )
    return value.translate(table)


def _friendly_math(text: str) -> str:
    text = text.replace(r"\left", "").replace(r"\right", "")
    text = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\dfrac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", text)
    text = re.sub(r"\\sqrt\s*(\d|[a-zA-Z])", r"√\1", text)
    text = re.sub(r"\bsqrt\s*\(", "√(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsqrt\s*(\d|[a-zA-Z])", r"√\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\^\{([^{}]*)\}", lambda match: _superscript(match.group(1)), text)
    text = re.sub(r"\^(\d+|[a-zA-Z][a-zA-Z0-9]*)", lambda match: _superscript(match.group(1)), text)
    replacements = {
        r"\times": "×",
        r"\cdot": "·",
        r"\div": "÷",
        r"\ne": "≠",
        r"\le": "≤",
        r"\ge": "≥",
        r"\approx": "≈",
        r"\pi": "π",
        r"\infty": "∞",
        r"\angle": "∠",
        r"\triangle": "△",
        r"\parallel": "∥",
        r"\perp": "⊥",
        r"\degree": "°",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\\[（(\[]\s*", "", text)
    text = re.sub(r"\\[）)\]]", "", text)
    text = text.replace(r"\[", "").replace(r"\]", "")
    text = re.sub(r"\(|\[", "(", text)
    text = re.sub(r"\)|\]", ")", text)
    text = re.sub(r"(?<!\\)\\", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _clean_problem(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        lines[0] = re.sub(r"^.{0,40}?识别如下[:：]\s*", "", lines[0])
    lines = [
        line
        for line in lines
        if not re.match(r"^(图片中的|OCR|识别结果|识别如下|.{0,20}(综合练|创新练|基础练|提高练))[:：]?$", line)
    ]
    if not lines:
        return ""
    if len(lines) > 1 and re.search(r"[，,；;：:]$", lines[-1]):
        lines.pop()
    return _friendly_math("\n".join(lines))


def _split_numbered_problems(text: str) -> list[str]:
    normalized = text.replace("\r", "\n")
    normalized = re.sub(
        r"(?<!^)(?<!\n)[ \t]+(?=\d{1,3}\s*[.、．](?!\d))",
        "\n",
        normalized,
        flags=re.MULTILINE,
    )
    prefix = r"\s*\d{1,3}\s*[.、．](?!\d)"
    parts = re.split(rf"(?m)^(?={prefix})", normalized.rstrip())
    labels = [int(label) for label in re.findall(r"(?m)^\s*(\d{1,3})\s*[.、．](?!\d)", normalized)]
    if len(labels) < 2 or any(right <= left for left, right in zip(labels, labels[1:])):
        return [text]
    numbered = [part.strip() for part in parts if re.match(prefix, part)]
    return numbered or [text]


def _extract_json_string(candidate: str) -> str | None:
    match = re.search(r'"problem"\s*:\s*"', candidate)
    if not match:
        return None
    index = match.end()
    chars: list[str] = []
    while index < len(candidate):
        char = candidate[index]
        if char == "\\":
            if index + 1 >= len(candidate):
                break
            chars.append(candidate[index : index + 2])
            index += 2
            continue
        if char == '"':
            break
        chars.append(char)
        index += 1
    return "".join(chars)


def _valid_annotations(raw_items: object) -> list[Annotation]:
    annotations: list[Annotation] = []
    if not isinstance(raw_items, list):
        return annotations
    for raw in raw_items:
        try:
            annotation = Annotation(**raw)
            if annotation.x + annotation.width <= 1 and annotation.y + annotation.height <= 1:
                annotations.append(annotation)
        except (TypeError, ValueError):
            continue
    return annotations[:12]


def _problem_items(text: str) -> list[RecognizedProblem]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    loose = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else (loose.group(0) if loose else cleaned)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        values = re.findall(r'"problem"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned, flags=re.DOTALL)
        if values:
            problems = [
                _clean_problem(part)
                for value in values
                for part in _split_numbered_problems(_unescape_json_string(value))
            ]
        elif not (candidate.startswith("{") or candidate.startswith("```")):
            problems = [_clean_problem(cleaned)]
        else:
            problems = []
        items = [RecognizedProblem(id=f"problem-{index}", problem=value) for index, value in enumerate(problems, 1) if value]
        return items[:20]
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("problems")
    if not isinstance(raw_items, list):
        raw_items = [payload]
    items: list[RecognizedProblem] = []
    for index, raw in enumerate(raw_items, 1):
        if not isinstance(raw, dict):
            continue
        annotations = _valid_annotations(raw.get("annotations"))
        for part in _split_numbered_problems(str(raw.get("problem", ""))):
            problem = _clean_problem(part)
            if not problem:
                continue
            items.append(RecognizedProblem(id=f"problem-{len(items) + 1}", problem=problem, annotations=annotations))
    return items[:20]


def parse_recognition(text: str) -> tuple[str, list[Annotation]]:
    """Backward-compatible single-problem view of the recognition contract."""
    items = _problem_items(text)
    if not items:
        return "", []
    return items[0].problem, items[0].annotations


def parse_recognition_items(text: str) -> list[RecognizedProblem]:
    """Parse all recognized problems while keeping per-problem annotations."""
    return _problem_items(text)
