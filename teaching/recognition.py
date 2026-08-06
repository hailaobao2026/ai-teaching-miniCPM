from __future__ import annotations

import json
import re

from .models import Annotation


def parse_recognition(text: str) -> tuple[str, list[Annotation]]:
    """Parse the optional JSON contract emitted by the upstream vision prompt."""
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    loose = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else (loose.group(0) if loose else cleaned)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return cleaned, []
    if not isinstance(payload, dict):
        return cleaned, []
    problem = str(payload.get("problem", "")).strip()
    annotations: list[Annotation] = []
    for raw in payload.get("annotations", []):
        try:
            annotation = Annotation(**raw)
            if annotation.x + annotation.width <= 1 and annotation.y + annotation.height <= 1:
                annotations.append(annotation)
        except (TypeError, ValueError):
            continue
    return problem or cleaned, annotations[:12]
