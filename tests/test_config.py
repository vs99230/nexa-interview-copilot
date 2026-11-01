from backend.config import Settings


def test_defaults_use_current_gemini_model_and_faster_listening_settings():
    settings = Settings()

    assert settings.gemini_models == ("gemini-3.5-flash-lite", "gemini-flash-latest")
    assert settings.whisper_model == "base"
    assert settings.silence_ms == 750
