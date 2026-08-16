from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from teaching.answers import answers_equivalent
from teaching.minicpm_client import MiniCPMClient, configured_client, structured_steps
from teaching.recognition import parse_recognition
from teaching.runtime_env import load_runtime_env


@dataclass
class QuestionResult:
    id: str
    category: str
    hint_ok: bool
    full_ok: bool
    answer: str | None
    expected_answer: str
    first_event_ms: int
    hint_latency_ms: int
    full_latency_ms: int
    error: str | None = None


async def call_with_metrics(
    client: MiniCPMClient,
    problem: str,
    message: str,
    stage: str,
    tts: bool,
    history: list[dict[str, Any]],
) -> tuple[str, int, int, str | None]:
    started = time.perf_counter()
    chunks: list[str] = []
    first_event_ms = 0
    try:
        async for event in client.stream(problem, message, history, tts, stage=stage):
            if not first_event_ms:
                first_event_ms = int((time.perf_counter() - started) * 1000)
            if event.get("type") == "text_delta" and event.get("text_delta"):
                chunks.append(str(event["text_delta"]))
        return (
            "".join(chunks).strip(),
            first_event_ms,
            int((time.perf_counter() - started) * 1000),
            None,
        )
    except Exception as exc:
        return "", first_event_ms, int((time.perf_counter() - started) * 1000), f"{type(exc).__name__}: {exc}"


async def evaluate_question(
    client: MiniCPMClient,
    question: dict[str, str],
    tts_sample: bool,
) -> QuestionResult:
    hint_text, _, hint_ms, hint_error = await call_with_metrics(
        client,
        question["problem"],
        "请给我一个提示，不要公布最终答案。",
        "hint",
        False,
        [],
    )
    _, parsed_hint_answer = structured_steps(hint_text)
    hint_ok = bool(hint_text) and parsed_hint_answer is None and hint_error is None

    full_text, full_first_ms, full_ms, full_error = await call_with_metrics(
        client,
        question["problem"],
        "请给出完整、可核验的分步解析，最后单独一行输出“最终答案：...”。",
        "explain",
        tts_sample,
        [
            {"role": "user", "content": "请给我一个提示，不要公布最终答案。"},
            {"role": "assistant", "content": hint_text or "先回顾相关公式。"},
        ],
    )
    _, actual_answer = structured_steps(full_text)
    expected = question.get("answer")
    actual_answer = normalize_actual_answer(actual_answer, expected)
    full_ok = actual_answer is not None and answers_equivalent(expected, actual_answer)
    error = hint_error or full_error
    return QuestionResult(
        id=question["id"],
        category=question.get("category", "general"),
        hint_ok=hint_ok,
        full_ok=full_ok,
        answer=actual_answer,
        expected_answer=expected or "",
        first_event_ms=full_first_ms,
        hint_latency_ms=hint_ms,
        full_latency_ms=full_ms,
        error=error,
    )


def normalize_actual_answer(actual: str | None, expected: str | None) -> str | None:
    if actual is None or expected is None:
        return actual
    value = actual.strip().strip("$").replace("\\(", "").replace("\\)", "")
    if "=" in value and expected.startswith("("):
        value = value.rsplit("=", 1)[1].strip()
    if expected.startswith("(") and "(" in value and value.endswith(")"):
        value = value[value.rfind("(") :]
    if expected == "是" and "在" in value:
        return "是"
    return value.strip() or None


async def evaluate(
    client: MiniCPMClient,
    questions: list[dict[str, str]],
    concurrency: int,
) -> list[QuestionResult]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def worker(question: dict[str, str], index: int) -> QuestionResult:
        async with semaphore:
            result = await evaluate_question(client, question, tts_sample=index == 0)
            print(
                f"[{index + 1}/{len(questions)}] {result.id}: "
                f"hint={'ok' if result.hint_ok else 'fail'}, "
                f"answer={'ok' if result.full_ok else 'fail'}"
            )
            return result

    return list(await asyncio.gather(*(worker(question, index) for index, question in enumerate(questions))))


async def multimodal_probe(client: MiniCPMClient, image_path: Path | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": await safe_probe(probe_text(client)),
        "tts": await safe_probe(probe_tts(client)),
    }
    if image_path:
        payload["image_recognition"] = await safe_probe(probe_image(client, image_path))
    return payload


async def safe_probe(coroutine: Any) -> dict[str, Any]:
    try:
        return await coroutine
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def probe_text(client: MiniCPMClient) -> dict[str, Any]:
    started = time.perf_counter()
    result = await client.chat(
        "解方程：2x + 5 = 17。",
        "请最后单独一行输出“最终答案：...”。",
        [],
        False,
        stage="explain",
    )
    text = result.get("text") or ""
    _, answer = structured_steps(text)
    return {
        "ok": answers_equivalent("x = 6", answer),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "answer": answer,
        "audio": bool(result.get("audio_base64")),
    }


async def probe_tts(client: MiniCPMClient) -> dict[str, Any]:
    started = time.perf_counter()
    result = await client.chat(
        "解方程：2x + 5 = 17。",
        "请用一句话提醒学生先移项，最后单独一行输出“最终答案：...”。",
        [],
        True,
        stage="hint",
    )
    return {
        "ok": bool(result.get("audio_base64")),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "audio_mime": result.get("audio_mime"),
    }


async def probe_image(client: MiniCPMClient, image_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    result = await client.chat(
        "请识别图片中的初中数学题。",
        '只返回 JSON：{"problem":"可编辑题面","annotations":[]}。不要解题。',
        [],
        False,
        stage="recognition",
        image_bytes=image_path.read_bytes(),
        image_mime="image/png",
    )
    problem, annotations = parse_recognition(result.get("text") or "")
    expected_core = "2x+5=17"
    normalized_problem = problem.replace(" ", "").replace("：", "").replace(":", "").rstrip("。.")
    return {
        "ok": expected_core in normalized_problem,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "recognized_problem": problem,
        "annotations": len(annotations),
    }


def write_report(results: list[QuestionResult], probe: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    successful = [item for item in results if item.error is None]
    latencies = sorted(item.full_latency_ms for item in successful)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "questions_total": len(results),
        "hint_guard_passed": sum(item.hint_ok for item in results),
        "answer_correct": sum(item.full_ok for item in results),
        "request_errors": sum(item.error is not None for item in results),
        "p50_full_ms": latencies[len(latencies) // 2] if latencies else None,
        "p95_full_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None,
        "first_event_ms": [item.first_event_ms for item in successful],
        "multimodal_probe": probe,
        "results": [asdict(item) for item in results],
    }
    output = output_dir / f"real-model-{timestamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    load_runtime_env()
    parser = argparse.ArgumentParser(description="Evaluate the configured real MiniCPM-o 4.5 endpoint")
    parser.add_argument("--limit", type=int, default=30, help="Number of questions, starting from --offset")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--image", type=Path, help="Optional PNG used for real image-recognition probe")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval" / "results")
    args = parser.parse_args()

    client = configured_client()
    if client is None:
        raise SystemExit("MiniCPM-o endpoint is not configured")
    questions = json.loads((ROOT / "eval/questions.json").read_text(encoding="utf-8"))
    selected = questions[args.offset : args.offset + args.limit]
    results = asyncio.run(evaluate(client, selected, args.concurrency))
    probe = asyncio.run(multimodal_probe(client, args.image))
    output = write_report(results, probe, args.output_dir)
    print(json.dumps({
        "report": str(output),
        "hint_guard_passed": f"{sum(x.hint_ok for x in results)}/{len(results)}",
        "answer_correct": f"{sum(x.full_ok for x in results)}/{len(results)}",
        "multimodal_probe": probe,
    }, ensure_ascii=False, indent=2))
    return 0 if results and all(x.hint_ok and not x.error for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
