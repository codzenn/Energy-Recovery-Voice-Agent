import io
import wave
from uuid import uuid4

import pytest

from app.services.speech_service import SpeechService


def post_audio(client, call, data=b"audio", event_id=None, content_type="audio/wav"):
    return client.post(
        f"/api/voice/{call['call_id']}/audio?event_id={event_id or uuid4()}",
        content=data, headers={"Content-Type": content_type},
    )


def test_audio_consent_and_handoff(client, services, call, monkeypatch):
    texts = iter([("yes", 0.99), ("demo value", 0.99), ("I need a human", 0.99)])
    monkeypatch.setattr(services.speech, "transcribe", lambda _: next(texts))
    result = post_audio(client, call).json()["call"]
    assert result["consent_given"]
    result = post_audio(client, call).json()["call"]
    assert result["collected_fields"]["field_1"] == "demo value"
    result = post_audio(client, call).json()["call"]
    assert result["status"] == "HANDOFF"
    assert result["escalation"]["collected_fields"]["field_1"] == "demo value"
    assert post_audio(client, call).status_code == 409


def test_audio_payment_never_echoed(client, services, call, monkeypatch):
    monkeypatch.setattr(services.speech, "transcribe", lambda _: ("My card is 4111 1111 1111 1111", 0.99))
    response = post_audio(client, call)
    assert response.json()["call"]["escalation"]["reason"] == "PAYMENT"
    assert "4111" not in response.text
    assert "4111" not in client.get(f"/api/calls/{call['call_id']}").text


def test_audio_without_consent_does_not_collect(client, services, call, monkeypatch):
    monkeypatch.setattr(services.speech, "transcribe", lambda _: ("My name is Example", 0.99))
    result = post_audio(client, call).json()["call"]
    assert not result["consent_given"]
    assert result["collected_fields"] == {}
    assert "Example" not in str(result["transcript"])


def test_audio_silence_and_replay(client, services, call, monkeypatch):
    monkeypatch.setattr(services.speech, "transcribe", lambda _: ("", 1.0))
    assert not post_audio(client, call).json()["heard"]
    event_id = str(uuid4())
    monkeypatch.setattr(services.speech, "transcribe", lambda _: ("yes", 0.99))
    first = post_audio(client, call, event_id=event_id).json()
    monkeypatch.setattr(services.speech, "transcribe", lambda _: pytest.fail("Replay transcribed again"))
    assert post_audio(client, call, event_id=event_id).json() == first


def test_audio_input_limits(client, call):
    assert post_audio(client, call, content_type="text/plain").status_code == 415
    assert post_audio(client, call, data=b"x" * 3_000_001).status_code == 413
    assert post_audio(client, call, data=b"not wav").status_code == 422
    assert post_audio(client, call, event_id="bad-id").status_code == 422


def test_audio_model_unavailable(client, services, call, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("internal details must not leak")
    monkeypatch.setattr(services.speech, "prepare", unavailable)
    monkeypatch.setattr(services.speech, "transcribe", unavailable)
    response = post_audio(client, call)
    assert response.status_code == 503
    assert "internal details" not in response.text
    assert client.get("/api/voice/capabilities").status_code == 503


@pytest.mark.parametrize("seconds,channels,width", [(32, 1, 2), (1, 2, 2), (1, 1, 1)])
def test_wav_validation_before_model_loading(seconds, channels, width):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(16000)
        wav.writeframes(b"\0" * (16000 * seconds * channels * width))
    with pytest.raises(ValueError):
        SpeechService().transcribe(stream.getvalue())
