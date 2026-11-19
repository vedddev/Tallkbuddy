from io import BytesIO
import base64
import json
import wave

import httpx
import numpy as np
import pytest

from desktop_bridge.audio_devices import AudioDevice, DeviceError
from desktop_bridge.live_client import (
    LiveClientError, TranslationConnection, login, parse_speech_audio, server_origin,
)
from desktop_bridge.live_translate import select_live_devices
from desktop_bridge.microphone import encode_phrase


def wav() -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(b"\x01\x00" * 1600)
    return buffer.getvalue()


def test_server_requires_tls_remotely_and_rejects_embedded_secrets() -> None:
    assert server_origin("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert server_origin("https://talkbuddy.example") == "https://talkbuddy.example"
    with pytest.raises(LiveClientError, match="HTTPS"):
        server_origin("http://talkbuddy.example:8000")
    with pytest.raises(LiveClientError, match="without credentials"):
        server_origin("https://user:pass@talkbuddy.example")


def test_login_keeps_cookie_in_memory_and_origin_is_sent() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["origin"] = request.headers.get("origin")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "x"}, headers={"set-cookie": "talkbuddy_session=secret; HttpOnly; Path=/"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert login("http://localhost:8000", "user@example.com", "password", client=client) is client
        assert client.cookies.get("talkbuddy_session") == "secret"
    assert seen == {"origin": "http://localhost:8000", "body": {"email": "user@example.com", "password": "password"}}


def test_login_rejects_missing_session() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401))) as client:
        with pytest.raises(LiveClientError, match="Login failed"):
            login("http://localhost:8000", "user@example.com", "bad", client=client)


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(value)

    def recv(self, timeout):
        return json.dumps(next(self.messages))

    def close(self):
        self.closed = True


def test_socket_handshake_phrase_order_audio_and_cleanup() -> None:
    fake = Socket([
        {"type": "ready", "target_language": "hi"},
        {"type": "processing", "chunk_id": 1},
        {"type": "result", "chunk_id": 1, "original": "Hello", "translated": "नमस्ते",
         "transcription_time_ms": 100, "translation_time_ms": 80},
        {"type": "speech_audio", "chunk_id": 1, "audio_format": "wav",
         "audio_base64": base64.b64encode(wav()).decode(), "preparation_time_ms": 120},
    ])
    connector_args = {}

    def connector(url, **kwargs):
        connector_args.update(url=url, **kwargs)
        return fake

    phrase = encode_phrase(np.ones(1600, dtype=np.float32) * 0.1, 16000, 10)
    with TranslationConnection("http://localhost:8000", "secret", "auto", "hi", connector=connector) as connection:
        result = connection.translate(phrase)
        assert result.wav_bytes == wav()
        assert result.chunk_id == 1
        assert result.stt_ms == 100 and result.tts_ms == 120
    assert connector_args["origin"] == "http://localhost:8000"
    assert connector_args["additional_headers"] == {"Cookie": "talkbuddy_session=secret"}
    assert json.loads(fake.sent[0]) == {"type": "start", "target_language": "hi", "audio_format": "wav",
                                        "save_history": False, "synthesize_speech": True}
    assert fake.sent[1] == phrase.wav_bytes
    assert json.loads(fake.sent[-1]) == {"type": "stop"}
    assert fake.closed


def test_history_requires_explicit_opt_in_and_reuses_phrase_uuid() -> None:
    phrase = encode_phrase(np.ones(1600, dtype=np.float32) * 0.1, 16000, 10)
    fake = Socket([{"type": "ready", "target_language": "fr"},
                   {"type": "processing", "chunk_id": 1},
                   {"type": "result", "chunk_id": 1, "original": "a", "translated": "b"},
                   {"type": "speech_error", "chunk_id": 1, "code": "speech_unavailable"}])
    with pytest.raises(LiveClientError, match="History requires"):
        TranslationConnection("http://localhost:8000", "secret", "en", "fr", session_id=str(phrase.phrase_id))
    with TranslationConnection("http://localhost:8000", "secret", "en", "fr", save_history=True,
                               session_id=phrase.phrase_id, connector=lambda *a, **kw: fake) as connection:
        result = connection.translate(phrase)
        assert result.wav_bytes is None
        assert result.speech_error == "speech_unavailable"
    assert json.loads(fake.sent[1]) == {"type": "chunk", "request_id": phrase.phrase_id}
    assert fake.sent[2] == phrase.wav_bytes


def test_invalid_speech_audio_and_wrong_order_rejected() -> None:
    with pytest.raises(LiveClientError):
        parse_speech_audio({"type": "speech_audio", "chunk_id": 1, "audio_format": "wav", "audio_base64": "###"}, 1)
    with pytest.raises(LiveClientError):
        parse_speech_audio({"type": "speech_audio", "chunk_id": 2, "audio_format": "wav", "audio_base64": base64.b64encode(wav()).decode()}, 1)
    fake = Socket([{"type": "ready", "target_language": "hi"}, {"type": "result", "chunk_id": 2, "original": "a", "translated": "b"}])
    with TranslationConnection("http://localhost:8000", "secret", "en", "hi", connector=lambda *a, **kw: fake) as connection:
        with pytest.raises(LiveClientError, match="order"):
            connection.translate(encode_phrase(np.ones(1600, dtype=np.float32), 16000, 0))


def test_live_device_selection_never_routes_to_speakers_or_cable_capture() -> None:
    mic = AudioDevice(18, "Realtek Mic", 2, 0, 48000)
    cable_input = AudioDevice(14, "CABLE Input", 0, 2, 48000)
    cable_output = AudioDevice(17, "CABLE Output", 2, 0, 48000)
    speakers = AudioDevice(16, "Speakers", 0, 2, 48000)
    devices = [mic, cable_input, cable_output, speakers]
    assert select_live_devices("18", "14", devices) == (mic, cable_input)
    with pytest.raises(DeviceError, match="CABLE Output"):
        select_live_devices("17", "14", devices)
    with pytest.raises(DeviceError, match="CABLE Input"):
        select_live_devices("18", "16", devices)
