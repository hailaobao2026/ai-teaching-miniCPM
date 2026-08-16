"""Shared subject catalog for the all-subject primary and secondary coach."""

from __future__ import annotations

from typing import Any, Literal

SubjectCode = Literal[
    "chinese",
    "math",
    "english",
    "physics",
    "chemistry",
    "politics",
    "history",
    "geography",
    "biology",
]

SUBJECTS: tuple[dict[str, Any], ...] = (
    {"code": "chinese", "name": "语文", "icon": "文", "focus": "阅读理解、古诗文、写作与语言运用"},
    {"code": "math", "name": "数学", "icon": "数", "focus": "概念、推理、计算与图形关系"},
    {"code": "english", "name": "英语", "icon": "英", "focus": "词汇、语法、阅读、写作与口语表达"},
    {"code": "physics", "name": "物理", "icon": "物", "focus": "现象、模型、公式、实验与单位"},
    {"code": "chemistry", "name": "化学", "icon": "化", "focus": "物质、反应、方程式、实验与守恒"},
    {"code": "politics", "name": "政治", "icon": "政", "focus": "概念辨析、材料分析与观点论证"},
    {"code": "history", "name": "历史", "icon": "史", "focus": "时间线、因果关系、材料与史实"},
    {"code": "geography", "name": "地理", "icon": "地", "focus": "地图、区域特征、自然与人文规律"},
    {"code": "biology", "name": "生物", "icon": "生", "focus": "结构功能、生命过程、实验与证据"},
)

SUBJECT_CODES = frozenset(item["code"] for item in SUBJECTS)
SUBJECT_LABELS = {item["code"]: item["name"] for item in SUBJECTS}
SUBJECT_FOCUS = {item["code"]: item["focus"] for item in SUBJECTS}


def normalize_subject(value: object) -> str:
    code = str(value or "math").strip().lower()
    aliases = {"语文": "chinese", "数学": "math", "英语": "english", "物理": "physics", "化学": "chemistry", "政治": "politics", "历史": "history", "地理": "geography", "生物": "biology"}
    code = aliases.get(code, code)
    return code if code in SUBJECT_CODES else "math"


def subject_name(value: object) -> str:
    return SUBJECT_LABELS.get(normalize_subject(value), "数学")


def subject_info() -> list[dict[str, Any]]:
    return [dict(item) for item in SUBJECTS]
