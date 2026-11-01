"""Turns a stream of transcribed utterances into complete interview questions.

Rules of thumb:
  * A question has a "?" or opens with a question / request cue ("tell me about",
    "walk me through", "can you ...", "what ...").
  * Pleasantries and statements ("Thanks for joining.") are ignored.
  * If an interviewer pauses mid-question, the fragment is held and merged with
    the next utterance (or flushed after `hold_seconds` if it is long enough).
"""
from __future__ import annotations

import re

_WH = {"what", "why", "how", "when", "where", "which", "who", "whom", "whose"}
_AUX = {
    "can", "could", "would", "will", "should", "do", "does", "did", "have", "has",
    "had", "are", "is", "was", "were", "shall", "may",
}
_PRONOUNS = {"you", "we", "i", "they", "he", "she", "there", "it", "this", "that", "your"}
_IMPERATIVE = {
    "tell", "walk", "explain", "describe", "talk", "give", "share", "discuss",
    "elaborate", "compare", "define", "list", "name", "show", "introduce", "outline",
    "summarize", "summarise", "recall", "illustrate", "clarify", "demonstrate",
}
_PHRASES = (
    "let's talk", "let us talk", "let's discuss", "let me ask", "i'd like to know",
    "i would like to know", "i want to know", "i'm curious", "i am curious",
    "i'd like you to", "i would like you to", "i'd love to hear", "i want to ask",
    "i wanted to ask", "i'd like to ask", "my next question", "next question",
    "would you mind", "can you", "could you", "please",
)
_NOT_QUESTIONS = (
    "give me a sec", "give me a moment", "give me a minute", "can you hear",
    "can you see", "hear me", "tell me when", "share my screen", "sharing my screen",
)
_LEAD_WORDS = {
    "so", "and", "now", "okay", "ok", "alright", "right", "well", "then", "great",
    "good", "nice", "cool", "sure", "perfect", "awesome", "excellent", "yeah", "yes",
    "but", "also", "next", "um", "uh", "hmm",
}
_FILLER_SENTENCE_WORDS = _LEAD_WORDS | {
    "thanks", "thank", "you", "got", "it", "welcome", "hi", "hello", "hey", "interesting", "sounds",
    "that", "makes", "sense", "i", "see", "understood", "fair", "enough", "mm", "mhm",
}
_DANGLING = {
    "and", "or", "but", "so", "because", "the", "a", "an", "to", "of", "with", "that",
    "which", "about", "in", "on", "for", "from", "your", "my", "our", "is", "are", "was",
    "were", "do", "does", "did", "how", "what", "why", "when", "where", "if", "as", "at",
    "by", "between", "using", "you", "we", "i", "can", "could", "would",
}
_LEAD_RE = re.compile(r"^(?:(?:okay|ok|alright|so|well|now|great|right|yeah|um|uh)[,.]?\s+){1,3}", re.I)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))


def _ends_terminal(text: str) -> bool:
    return text.rstrip().endswith((".", "?", "!"))


def _skip_lead(words: list[str]) -> list[str]:
    i = 0
    while i < len(words) - 1 and i < 4 and words[i] in _LEAD_WORDS:
        i += 1
    return words[i:]


def looks_like_question(sentence: str, min_words: int = 3) -> bool:
    words = _words(sentence)
    if len(words) < min_words:
        return False
    if sentence.rstrip().endswith("?"):
        return True
    core = _skip_lead(words)
    if not core:
        return False
    first = core[0]
    if first in _WH or first in _IMPERATIVE:
        return True
    if first in _AUX and len(core) > 1 and core[1] in _PRONOUNS:
        return True
    lowered = " ".join(core)
    return any(lowered.startswith(phrase) for phrase in _PHRASES)


def _is_complete(sentence: str) -> bool:
    if _ends_terminal(sentence):
        return True
    words = _words(sentence)
    return len(words) >= 4 and words[-1] not in _DANGLING


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


def _is_filler_sentence(sentence: str) -> bool:
    words = _words(sentence)
    return len(words) <= 3 and all(w in _FILLER_SENTENCE_WORDS for w in words)


class QuestionDetector:
    def __init__(self, hold_seconds: float = 2.5, dedupe_seconds: float = 15.0) -> None:
        self.hold_seconds = hold_seconds
        self.dedupe_seconds = dedupe_seconds
        self.reset()

    def reset(self) -> None:
        self._held: str | None = None
        self._held_at = 0.0
        self._last_key = ""
        self._last_at = -1e9

    def feed(self, text: str, now: float) -> list[str]:
        """Add one transcribed utterance; return zero or one complete question."""
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []
        if self._held:
            text = f"{self._held} {text}"
            self._held = None
        return self._evaluate(text, now, force=False)

    def poll(self, now: float) -> list[str]:
        """Flush a held fragment that has waited long enough."""
        if self._held and now - self._held_at >= self.hold_seconds:
            text, self._held = self._held, None
            return self._evaluate(text, now, force=True)
        return []

    def _evaluate(self, text: str, now: float, force: bool) -> list[str]:
        sentences = _split_sentences(text)
        while sentences and _is_filler_sentence(sentences[0]):
            sentences.pop(0)
        if not sentences:
            return []

        is_question = any(looks_like_question(s) for s in sentences)
        last = sentences[-1]
        fragment = (not is_question) and (not _ends_terminal(last)) and looks_like_question(last, min_words=1)

        if (is_question or fragment) and not force and not _is_complete(last):
            self._held, self._held_at = " ".join(sentences), now
            return []
        if not is_question:
            return []
        if force and len(_words(" ".join(sentences))) < 4:
            return []

        question = _LEAD_RE.sub("", " ".join(sentences), count=1).strip()
        question = question[:1].upper() + question[1:]
        lowered = question.lower()
        if any(bad in lowered for bad in _NOT_QUESTIONS):
            return []

        key = " ".join(_words(question))
        if key == self._last_key and now - self._last_at < self.dedupe_seconds:
            return []
        self._last_key, self._last_at = key, now
        return [question]
