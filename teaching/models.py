from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RecognizeResponse(BaseModel):
    problem: str
    confidence: float = Field(ge=0, le=1)
    source: Literal["mock", "minicpm"]
    needs_confirmation: bool = True
    annotations: list["Annotation"] = Field(default_factory=list)


class Annotation(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class LessonRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=80)
    problem: str = Field(min_length=1, max_length=4000)
    message: str = Field(default="请先给我一个提示，不要直接公布答案。", max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=16)
    stage: Literal["hint", "explain", "practice"] = "hint"
    tts: bool = True
    audio_base64: str | None = Field(default=None, max_length=8_000_000)
    audio_sample_rate: int = Field(default=16000, ge=8000, le=48000)


class Step(BaseModel):
    title: str
    body: str
    state: Literal["active", "done", "locked"] = "active"


class LessonResponse(BaseModel):
    session_id: str = ""
    reply: str
    steps: list[Step]
    final_answer: str | None = None
    next_question: str
    confidence: float = Field(ge=0, le=1)
    source: Literal["mock", "minicpm"]
    audio_base64: str | None = None
    audio_mime: str | None = None


class FeedbackRequest(BaseModel):
    problem: str
    helpful: bool
    note: str = Field(default="", max_length=500)
