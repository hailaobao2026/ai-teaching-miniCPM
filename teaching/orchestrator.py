from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4


@dataclass
class TeachingSession:
    id: str
    problem: str
    owner_id: str
    subject: str = "math"
    history: list[dict] = field(default_factory=list)
    stage: str = "confirm"
    image_bytes: bytes | list[bytes] | None = None
    image_mime: str = "image/png"
    touched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TeachingOrchestrator:
    """Owns short-lived lesson state without persisting a student's raw media."""

    def __init__(self, max_sessions: int = 200, session_ttl_minutes: int = 30):
        self.max_sessions = max_sessions
        self.session_ttl = timedelta(minutes=session_ttl_minutes)
        self.sessions: dict[str, TeachingSession] = {}

    def create_recognition_session(
        self,
        problem: str,
        owner_id: str,
        image_bytes: bytes | list[bytes],
        image_mime: str,
        subject: str = "math",
    ) -> TeachingSession:
        session = TeachingSession(
            id=uuid4().hex,
            problem=problem,
            owner_id=owner_id,
            subject=subject,
            stage="confirm",
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
        self.sessions[session.id] = session
        self._trim()
        return session

    def get_or_create(self, session_id: str | None, problem: str, owner_id: str, subject: str = "math") -> TeachingSession:
        now = datetime.now(timezone.utc)
        self._drop_expired(now)
        session = self.sessions.get(session_id or "")
        owner_matches = session is not None and session.owner_id == owner_id
        can_confirm_image = bool(owner_matches and session and session.image_bytes and session.stage == "confirm")
        if session is None or not owner_matches or (session.problem != problem and not can_confirm_image) or (session and session.subject != subject):
            replacement_id = uuid4().hex
            session = TeachingSession(id=replacement_id, problem=problem, owner_id=owner_id, subject=subject)
            self.sessions[session.id] = session
        elif can_confirm_image:
            session.problem = problem
            session.subject = subject
        session.touched_at = now
        self._trim()
        return session

    def commit(self, session: TeachingSession, user_message: str, assistant_message: str, stage: str) -> None:
        session.history.extend(
            [{"role": "user", "content": user_message}, {"role": "assistant", "content": assistant_message}]
        )
        session.history = session.history[-16:]
        session.stage = stage
        session.touched_at = datetime.now(timezone.utc)

    def delete(self, session_id: str | None, owner_id: str) -> bool:
        if not session_id:
            return False
        session = self.sessions.get(session_id)
        if session is None or session.owner_id != owner_id:
            return False
        return self.sessions.pop(session_id, None) is not None

    def _trim(self) -> None:
        if len(self.sessions) <= self.max_sessions:
            return
        oldest = sorted(self.sessions.values(), key=lambda item: item.touched_at)[: len(self.sessions) - self.max_sessions]
        for session in oldest:
            self.sessions.pop(session.id, None)

    def _drop_expired(self, now: datetime) -> None:
        expired = [
            session_id
            for session_id, session in self.sessions.items()
            if now - session.touched_at > self.session_ttl
        ]
        for session_id in expired:
            self.sessions.pop(session_id, None)
