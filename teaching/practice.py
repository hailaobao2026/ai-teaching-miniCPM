from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .subjects import normalize_subject, subject_name
from .text_utils import normalize_problem_text

TOPIC_LABELS = {
    "equation": "一元一次方程",
    "factor": "因式分解",
    "function": "一次函数",
    "geometry": "平面几何",
    "coordinate": "解析几何",
    "general": "综合练习",
}

_CATEGORY_TO_TOPIC = {
    "一元一次方程": "equation",
    "因式分解": "factor",
    "一次函数": "function",
    "平面几何": "geometry",
    "解析几何": "coordinate",
}

_QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "eval" / "questions.json"


def topic_label(topic: str | None) -> str:
    return TOPIC_LABELS.get(str(topic or "general"), TOPIC_LABELS["general"])


def _normalise(text: str) -> str:
    return normalize_problem_text(text)


def normalize_problem(text: str) -> str:
    return _normalise(text)


def classify_topic(problem: str | None) -> str:
    text = str(problem or "")
    compact = _normalise(text)
    if any(key in text or key in compact for key in ("因式", "平方差", "完全平方", "x²-9", "x2-9")):
        return "factor"
    if any(key in text for key in ("面积", "周长", "直角", "勾股", "梯形", "平行四边形", "正方形", "矩形", "三角形", "圆的")):
        return "geometry"
    if any(key in text for key in ("对称点", "中点", "到原点", "关于x轴", "关于y轴")):
        return "coordinate"
    if any(key in text for key in ("函数", "斜率", "一次函数", "与 x 轴", "与x轴", "与 y 轴", "与y轴")):
        return "function"
    if any(key in text or key in compact for key in ("方程", "解方程", "2x", "3x", "4x", "5x", "6x", "7x", "x/")):
        return "equation"
    return "general"


@lru_cache(maxsize=1)
def practice_bank() -> tuple[dict[str, Any], ...]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    if _QUESTIONS_PATH.exists():
        raw = json.loads(_QUESTIONS_PATH.read_text(encoding="utf-8"))
        for row in raw:
            problem = str(row.get("problem") or "").strip()
            key = _normalise(problem)
            if not problem or key in seen:
                continue
            topic = _CATEGORY_TO_TOPIC.get(str(row.get("category") or ""), classify_topic(problem))
            seen.add(key)
            items.append(
                {
                    "id": str(row.get("id") or f"eval-{len(items) + 1}"),
                    "title": str(row.get("category") or topic_label(topic)),
                    "problem": problem,
                    "topic": topic,
                    "topic_label": topic_label(topic),
                    "final_answer": str(row.get("final_answer") or row.get("answer") or "").strip(),
                }
            )

    return tuple(items)


def recommend_practice(
    *,
    problem: str | None = None,
    topic: str | None = None,
    exclude: list[str] | None = None,
    preferred_topics: list[str] | None = None,
    limit: int = 3,
    subject: str = "math",
) -> dict[str, Any]:
    limit = max(1, min(8, int(limit or 3)))
    chosen = str(topic or "").strip()
    if chosen not in TOPIC_LABELS:
        chosen = classify_topic(problem) if problem else ""
    if chosen not in TOPIC_LABELS or chosen == "general":
        preferred = [item for item in (preferred_topics or []) if item in TOPIC_LABELS and item != "general"]
        chosen = preferred[0] if preferred else "equation"

    excluded = {_normalise(item) for item in (exclude or []) if item}
    if problem:
        excluded.add(_normalise(problem))

    subject = normalize_subject(subject)
    if subject != "math":
        name = subject_name(subject)
        items = [
            {
                "id": f"{subject}-practice-{index}",
                "title": f"{name}基础巩固",
                "problem": f"请围绕当前{ name }题，写出一个关键概念、证据或解题步骤。",
                "topic": "general",
                "topic_label": f"{name}综合",
                "reason": f"与当前题同属{name}，适合巩固方法",
            }
            for index in range(1, min(limit, 3) + 1)
        ]
        return {"subject": subject, "topic": "general", "topic_label": f"{name}综合", "items": items}

    bank = list(practice_bank())
    same = [item for item in bank if item["topic"] == chosen and _normalise(item["problem"]) not in excluded]
    picked = same[:limit]
    items = [
        {
            "id": item["id"],
            "title": item["title"],
            "problem": item["problem"],
            "topic": item["topic"],
            "topic_label": item["topic_label"],
            "reason": (
                f"与当前题同属{topic_label(chosen)}"
                if item["topic"] == chosen
                else f"拓展练习 · {item['topic_label']}"
            ),
        }
        for item in picked
    ]
    return {
        "subject": subject,
        "topic": chosen,
        "topic_label": topic_label(chosen),
        "items": items,
    }
