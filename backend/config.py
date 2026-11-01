"""Runtime settings, read once from environment variables / the .env file."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

FROZEN = bool(getattr(sys, "frozen", False))  # True inside a PyInstaller build (Nexa.exe)

if FROZEN:
    # BUNDLE_DIR holds the files packed into the build (the React UI).
    # APP_DIR is the folder containing Nexa.exe: the user's .env and the log live there,
    # outside the bundle, so API keys are never packed into the build.
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    APP_DIR = Path(sys.executable).resolve().parent
else:
    BUNDLE_DIR = APP_DIR = Path(__file__).resolve().parent.parent

ROOT = APP_DIR  # kept for backwards compatibility
FRONTEND_DIST = BUNDLE_DIR / "frontend" / "dist"
ENV_FILE = APP_DIR / ".env"

load_dotenv(ENV_FILE)


def _csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    groq_api_key: str = ""
    # Tried in order. Model names get retired from time to time, so these are
    # overridable in .env; a retired model (404) is skipped automatically.
    gemini_models: tuple[str, ...] = ("gemini-3.5-flash-lite", "gemini-flash-latest")
    groq_models: tuple[str, ...] = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")

    whisper_model: str = "base"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    whisper_language: str = " "  # empty string = auto-detect (needs a multilingual model)

    silence_ms: int = 750  # pause that ends an utterance
    history_turns: int = 6  # Q/A pairs kept in memory for follow-up questions

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            gemini_models=_csv("GEMINI_MODELS", ",".join(defaults.gemini_models)),
            groq_models=_csv("GROQ_MODELS", ",".join(defaults.groq_models)),
            whisper_model=os.getenv("WHISPER_MODEL", defaults.whisper_model).strip(),
            whisper_device=os.getenv("WHISPER_DEVICE", defaults.whisper_device).strip(),
            whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", defaults.whisper_compute_type).strip(),
            whisper_language=os.getenv("WHISPER_LANGUAGE", defaults.whisper_language).strip(),
            silence_ms=_int("SILENCE_MS", defaults.silence_ms),
            history_turns=_int("HISTORY_TURNS", defaults.history_turns),
        )

    @property
    def has_llm_key(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key)

    @property
    def provider_names(self) -> list[str]:
        names = []
        if self.gemini_api_key:
            names.append("gemini")
        if self.groq_api_key:
            names.append("groq")
        return names
