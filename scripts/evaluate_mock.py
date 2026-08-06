from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from teaching.mock_tutor import lesson


def main() -> int:
    questions = json.loads((Path(__file__).parents[1] / "eval/questions.json").read_text())
    hint_ok = 0
    full_ok = 0
    supported = 0
    for question in questions:
        hint = lesson(question["problem"], "请给我一个提示。", "hint")
        full = lesson(question["problem"], "请给完整解析。", "explain")
        hint_ok += int(hint.final_answer is None)
        if full.steps and full.confidence >= 0.9:
            supported += 1
            full_ok += int(full.final_answer is not None)
    print(f"questions={len(questions)} hint_guard={hint_ok}/{len(questions)} mock_supported={supported} full_response={full_ok}/{supported}")
    return 0 if hint_ok == len(questions) and full_ok == supported else 1


if __name__ == "__main__":
    raise SystemExit(main())
