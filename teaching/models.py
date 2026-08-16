from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .subjects import SubjectCode


class Annotation(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class RecognizedProblem(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    problem: str = Field(min_length=1, max_length=4000)
    annotations: list[Annotation] = Field(default_factory=list)


class RecognizeResponse(BaseModel):
    subject: str = "math"
    problem: str
    problems: list[RecognizedProblem] = Field(default_factory=list)
    selected_problem_id: str | None = Field(default=None, max_length=40)
    confidence: float = Field(ge=0, le=1)
    source: Literal["mock", "minicpm"]
    needs_confirmation: bool = True
    annotations: list[Annotation] = Field(default_factory=list)
    session_id: str | None = Field(default=None, max_length=80)
    degraded: bool = False
    degraded_reason: str | None = Field(default=None, max_length=300)
    no_problems: bool = False
    message: str | None = Field(default=None, max_length=300)


class LessonRequest(BaseModel):
    subject: SubjectCode = "math"
    session_id: str | None = Field(default=None, max_length=80)
    problem: str = Field(min_length=1, max_length=4000)
    message: str = Field(default="请先给我一个提示，不要直接公布答案。", max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=16)
    stage: Literal["hint", "explain", "practice"] = "hint"

    @field_validator("stage", mode="before")
    @classmethod
    def normalize_stage(cls, value: object) -> object:
        if value == "confirm":
            return "hint"
        return value
    tts: bool = False
    audio_base64: str | None = Field(default=None, max_length=4_000_000)
    audio_sample_rate: int = Field(default=16000, ge=8000, le=48000)


class Step(BaseModel):
    title: str
    body: str
    state: Literal["active", "done", "locked"] = "active"


class LessonResponse(BaseModel):
    subject: str = "math"
    session_id: str = ""
    stage: str = "hint"
    reply: str
    steps: list[Step]
    final_answer: str | None = None
    next_question: str
    confidence: float = Field(ge=0, le=1)
    source: Literal["mock", "minicpm"]
    audio_base64: str | None = None
    audio_mime: str | None = None


class SpeechRequest(BaseModel):
    subject: SubjectCode = "math"
    text: str = Field(min_length=1, max_length=4000)


class SpeechResponse(BaseModel):
    audio_base64: str
    audio_mime: str = "audio/wav"
    source: Literal["minicpm"] = "minicpm"


class FeedbackRequest(BaseModel):
    subject: SubjectCode = "math"
    problem: str = Field(min_length=1, max_length=4000)
    helpful: bool
    note: str = Field(default="", max_length=500)
    session_id: str | None = Field(default=None, max_length=80)
    stage: str | None = Field(default=None, max_length=32)
    final_answer: str | None = Field(default=None, max_length=500)
    reply: str | None = Field(default=None, max_length=4000)


class PracticeRecommendRequest(BaseModel):
    subject: SubjectCode = "math"
    problem: str | None = Field(default=None, max_length=4000)
    topic: str | None = Field(default=None, max_length=32)
    limit: int = Field(default=3, ge=1, le=8)
    exclude: list[str] = Field(default_factory=list, max_length=20)


class NotebookAttemptRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=500)
