import pytest

from backend.question_detector import QuestionDetector, looks_like_question


def feed(det, text, now=0.0):
    return det.feed(text, now)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Tell me about yourself.", "Tell me about yourself."),
        ("Okay, so tell me about yourself", "Tell me about yourself"),
        ("What is the difference between a process and a thread?", "What is the difference between a process and a thread?"),
        ("Can you walk me through your RAG project?", "Can you walk me through your RAG project?"),
        ("Walk me through how you handled chunking.", "Walk me through how you handled chunking."),
        ("Great. Now, how would you design a rate limiter?", "How would you design a rate limiter?"),
        ("You mentioned XGBoost, why did you pick it over a neural net?", "You mentioned XGBoost, why did you pick it over a neural net?"),
        ("Do you have any experience with Docker?", "Do you have any experience with Docker?"),
        ("Let's talk about your internship at Zidio.", "Let's talk about your internship at Zidio."),
    ],
)
def test_detects_questions(text, expected):
    assert feed(QuestionDetector(), text) == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "Thanks for joining us today.",
        "Hi, thank you.",
        "Okay.",
        "Great.",
        "I'm Priya, I lead the data platform team here.",
        "Give me a second, let me pull up your resume.",
        "Can you hear me okay?",
        "Have a seat.",
        "",
    ],
)
def test_ignores_non_questions(text):
    assert feed(QuestionDetector(), text) == []


def test_merges_question_split_by_a_pause():
    det = QuestionDetector()
    assert feed(det, "So tell me about a time when", 0.0) == []
    assert feed(det, "you disagreed with a teammate.", 1.5) == ["Tell me about a time when you disagreed with a teammate."]


def test_flushes_long_unpunctuated_fragment_after_hold():
    det = QuestionDetector(hold_seconds=2.5)
    assert feed(det, "what do you think about the trade offs between", 0.0) == []
    assert det.poll(1.0) == []
    assert det.poll(3.0) == ["What do you think about the trade offs between"]


def test_short_fragment_is_dropped_not_flushed():
    det = QuestionDetector(hold_seconds=2.5)
    assert feed(det, "Tell me about", 0.0) == []
    assert det.poll(5.0) == []


def test_dedupes_repeated_question_but_allows_it_later():
    det = QuestionDetector(dedupe_seconds=15)
    q = "What is your biggest weakness?"
    assert feed(det, q, 0.0) == [q]
    assert feed(det, q, 5.0) == []
    assert feed(det, q, 30.0) == [q]


def test_reset_clears_held_fragment():
    det = QuestionDetector()
    feed(det, "So tell me about a time when", 0.0)
    det.reset()
    assert det.poll(10.0) == []


def test_looks_like_question_basics():
    assert looks_like_question("Why?", min_words=1)
    assert not looks_like_question("Why?")
    assert looks_like_question("is it thread safe?")
    assert not looks_like_question("The weather is nice today.")
