from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class TeachingSession:
    id: str
    problem: str
    history: list[dict] = field(default_factory=list)
    stage: str = "confirm"
    touched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TeachingOrchestrator:
    """Owns short-lived lesson state without persisting a student's raw media."""

    def __init__(self, max_sessions: int = 200):
        self.max_sessions = max_sessions
        self.sessions: dict[str, TeachingSession] = {}

    def get_or_create(self, session_id: str | None, problem: str) -> TeachingSession:
        session = self.sessions.get(session_id or "")
        if session is None or session.problem != problem:
            session = TeachingSession(id=session_id or uuid4().hex, problem=problem)
            self.sessions[session.id] = session
        session.touched_at = datetime.now(timezone.utc)
        self._trim()
        return session

    def commit(self, session: TeachingSession, user_message: str, assistant_message: str, stage: str) -> None:
        session.history.extend(
            [{"role": "user", "content": user_message}, {"role": "assistant", "content": assistant_message}]
        )
        session.history = session.history[-16:]
        session.stage = stage
        session.touched_at = datetime.now(timezone.utc)

    def delete(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        return self.sessions.pop(session_id, None) is not None

    def _trim(self) -> None:
        if len(self.sessions) <= self.max_sessions:
            return
        oldest = sorted(self.sessions.values(), key=lambda item: item.touched_at)[: len(self.sessions) - self.max_sessions]
        for session in oldest:
            self.sessions.pop(session.id, None)
