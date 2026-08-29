from __future__ import annotations

import re
from typing import Any

from sympy import Eq, simplify
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from .text_utils import normalize_answer_text


_TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)
_COORDINATE_PATTERN = re.compile(r"^\(([^,，;]+)[,，;]([^,，;]+)\)$")
_ASSIGNMENT_PATTERN = re.compile(r"^([a-zA-Z])\s*=\s*(.+)$")


def _normalize(value: str) -> str:
    return normalize_answer_text(value)


def _parse(text: str) -> Any:
    source = _normalize(text)
    assignment = _ASSIGNMENT_PATTERN.match(source)
    if assignment:
        source = assignment.group(2)
    return parse_expr(source, transformations=_TRANSFORMATIONS, evaluate=False)


def _equivalent_numbers(left: Any, right: Any) -> bool:
    try:
        return bool(simplify(left - right) == 0)
    except Exception:
        return False


def _equivalent_coordinates(expected: str, actual: str) -> bool | None:
    expected_match = _COORDINATE_PATTERN.match(_normalize(expected))
    actual_match = _COORDINATE_PATTERN.match(_normalize(actual))
    if not expected_match or not actual_match:
        return None
    return _equivalent_numbers(
        _parse(expected_match.group(1)),
        _parse(actual_match.group(1)),
    ) and _equivalent_numbers(
        _parse(expected_match.group(2)),
        _parse(actual_match.group(2)),
    )


def answers_equivalent(expected: str | None, actual: str | None) -> bool:
    expected_text = _normalize(expected)
    actual_text = _normalize(actual)
    if not expected_text or not actual_text:
        return False
    if expected_text == actual_text:
        return True
    if expected_text in {"是", "yes", "true"} and actual_text in {"是", "yes", "true"}:
        return True
    if expected_text in {"否", "no", "false"} and actual_text in {"否", "no", "false"}:
        return True

    expected_assignment = _ASSIGNMENT_PATTERN.match(expected_text)
    actual_assignment = _ASSIGNMENT_PATTERN.match(actual_text)
    if expected_assignment and actual_assignment and expected_assignment.group(1) != actual_assignment.group(1):
        return False

    coordinate_result = _equivalent_coordinates(expected_text, actual_text)
    if coordinate_result is not None:
        return coordinate_result
    try:
        expected_expr = _parse(expected_text)
        actual_expr = _parse(actual_text)
        if _equivalent_numbers(expected_expr, actual_expr):
            return True
        return bool(simplify(Eq(expected_expr, actual_expr)) is True)
    except Exception:
        return False
