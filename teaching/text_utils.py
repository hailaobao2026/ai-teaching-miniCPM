from __future__ import annotations

import re


_PROBLEM_PUNCTUATION = re.compile(r"[\s，。！？、：；（）()【】\[\]{}]")
_UNIT_SUFFIX = re.compile(r"(平方厘米|平方单位|厘米|分米|米|单位|个|条|次|度|°)$")
_ANSWER_REPLACEMENTS = {
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "：": ":",
    "，": ",",
    "；": ";",
    "。": ".",
    "！": "!",
    "？": "?",
    "＋": "+",
    "－": "-",
    "×": "*",
    "÷": "/",
    "√": "sqrt",
    "π": "pi",
    "²": "^2",
    "³": "^3",
    "^": "**",
}


def normalize_problem_text(value: str | None) -> str:
    text = str(value or "").replace("＝", "=").lower()
    return _PROBLEM_PUNCTUATION.sub("", text)


def normalize_answer_text(value: str | None) -> str:
    text = str(value or "").strip().lower()
    for source, target in _ANSWER_REPLACEMENTS.items():
        text = text.replace(source, target)
    text = re.sub(r"sqrt(\d+)", r"sqrt(\1)", text)
    text = _UNIT_SUFFIX.sub("", text)
    return re.sub(r"\s+", "", text)
