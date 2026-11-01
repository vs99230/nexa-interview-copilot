import importlib
import sys

import pytest

import backend.config as config


@pytest.fixture(autouse=True)
def restore_config():
    yield
    importlib.reload(config)  # back to the normal (non-frozen) paths for other tests


def test_source_run_uses_project_root():
    importlib.reload(config)
    assert config.FROZEN is False
    assert config.APP_DIR == config.BUNDLE_DIR
    assert config.FRONTEND_DIST == config.APP_DIR / "frontend" / "dist"
    assert config.ENV_FILE == config.APP_DIR / ".env"


def test_frozen_build_reads_ui_from_bundle_and_env_from_next_to_exe(monkeypatch, tmp_path):
    bundle = tmp_path / "Nexa" / "_internal"
    app = tmp_path / "Nexa"
    bundle.mkdir(parents=True)
    (app / "Nexa.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "Nexa.exe"))
    (app / ".env").write_text("GROQ_API_KEY=test-key-from-exe-folder\nSILENCE_MS=900\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("SILENCE_MS", raising=False)

    importlib.reload(config)

    assert config.FROZEN is True
    assert config.FRONTEND_DIST == bundle / "frontend" / "dist"
    assert config.ENV_FILE == app / ".env"
    settings = config.Settings.from_env()
    assert settings.groq_api_key == "test-key-from-exe-folder"
    assert settings.silence_ms == 900
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("SILENCE_MS", raising=False)
