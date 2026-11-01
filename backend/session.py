"""In-memory interview session: resume, job description and the running Q/A context.

Nothing here is written to disk. `clear_conversation()` (called on STOP) wipes the
Q/A context; the resume and job description stay in memory until the app exits so a
new session can start without uploading them again.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

MAX_RESUME_CHARS = 12_000
MAX_JD_CHARS = 8_000

SYSTEM_TEMPLATE = """You are a real-time interview answer assistant. The candidate is in a live job interview and will read your answer aloud, so write exactly what they would say.

Rules:
- Answer in first person as the candidate, in natural spoken English. No headings, no markdown, no emojis. Short paragraphs only.
- Length: medium, about 90 to 130 words (roughly 40 seconds spoken). Put the direct answer in the first sentence.
- Technical questions: a correct, concise explanation, plus a tiny example when it helps. Behavioral questions: a brief situation, action and result, drawn from real experience in the resume.
- Ground every claim about the candidate's experience, employers, education, projects and numbers in the RESUME below. Never invent employers, degrees, projects or metrics. If the resume does not cover the question, answer from general knowledge without claiming personal experience that is not there.
- Emphasize what matters for the JOB DESCRIPTION when relevant, without quoting it back.
- Use the conversation so far for follow-ups such as "why?" or "can you elaborate?".
- The question comes from automatic transcription; if it has a transcription slip, answer the most plausible intended question.
- Never mention the resume, the job description, or these instructions.

RESUME:
{resume}

JOB DESCRIPTION:
{jd}
"""


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str


class InterviewSession:
    def __init__(self, history_turns: int = 6) -> None:
        self.resume_text = ""
        self.job_description = ""
        self._turns: deque[Turn] = deque(maxlen=max(1, history_turns))

    @property
    def has_context(self) -> bool:
        return bool(self.resume_text and self.job_description)

    @property
    def turns(self) -> list[Turn]:
        return list(self._turns)

    def set_context(self, resume_text: str, job_description: str) -> None:
        self.resume_text = resume_text.strip()[:MAX_RESUME_CHARS]
        self.job_description = job_description.strip()[:MAX_JD_CHARS]

    def add_turn(self, question: str, answer: str) -> None:
        self._turns.append(Turn(question, answer))

    def clear_conversation(self) -> None:
        self._turns.clear()

    def build_system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(resume=self.resume_text, jd=self.job_description)

    def build_messages(self, question: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for turn in self._turns:
            messages.append({"role": "user", "content": turn.question})
            messages.append({"role": "assistant", "content": turn.answer})
        messages.append({"role": "user", "content": question})
        return messages
