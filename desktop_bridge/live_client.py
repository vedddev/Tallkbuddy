"""In-memory cookie login and the existing authenticated translation socket protocol."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from io import BytesIO
import json
import time
from typing import Any
from urllib.parse import urlsplit
import uuid
import wave

import httpx
from websockets.sync.client import connect

from desktop_bridge.config import load_language_registry
from desktop_bridge.microphone import CapturedPhrase
from desktop_bridge.wav_player import WavError, load_pcm_wav_bytes


class LiveClientError(RuntimeError):
    pass


def server_origin(server: str) -> str:
    parsed = urlsplit(server)
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise LiveClientError("Use a server origin without credentials, path, query, or fragment.")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LiveClientError("Server must include an HTTP(S) scheme and hostname.")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise LiveClientError("Remote servers require HTTPS/WSS.")
    return f"{parsed.scheme}://{parsed.netloc}"


def language_code(code: str, *, allow_auto: bool = False) -> str:
    if allow_auto and code == "auto":
        return code
    valid = {entry.code for entry in load_language_registry() if entry.api_enabled}
    if code not in valid:
        raise LiveClientError("Unsupported language. Use a code from shared/languages.json.")
    return code


def login(server: str, email: str, password: str, *, client: httpx.Client | None = None) -> httpx.Client:
    origin = server_origin(server)
    owns_client = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=False, trust_env=False)
    try:
        response = client.post(f"{origin}/api/auth/login", json={"email": email, "password": password},
                               headers={"Origin": origin})
        if response.status_code != 200 or not client.cookies.get("talkbuddy_session"):
            raise LiveClientError("Login failed. Check credentials and backend availability.")
        return client
    except httpx.HTTPError as exc:
        if owns_client:
            client.close()
        raise LiveClientError("Could not reach the backend login endpoint.") from exc
    except Exception:
        if owns_client:
            client.close()
        raise


def logout(server: str, client: httpx.Client) -> None:
    origin = server_origin(server)
    csrf = client.cookies.get("talkbuddy_csrf")
    if not csrf:
        return
    try:
        client.post(f"{origin}/api/auth/logout", headers={"Origin": origin, "X-CSRF-Token": csrf})
    except httpx.HTTPError:
        pass


@dataclass(frozen=True)
class SpeechResponse:
    chunk_id: int
    original: str
    translated: str
    wav_bytes: bytes | None
    submitted_at_ms: float
    websocket_roundtrip_ms: float
    stt_ms: int | None
    translation_ms: int | None
    tts_ms: int | None
    audio_received_at_ms: float
    speech_error: str | None = None


def parse_speech_audio(message: dict[str, Any], expected_chunk: int, max_bytes: int = 2 * 1024 * 1024) -> bytes:
    if message.get("type") != "speech_audio" or message.get("chunk_id") != expected_chunk or message.get("audio_format") != "wav":
        raise LiveClientError("Unexpected speech audio response.")
    encoded = message.get("audio_base64")
    if not isinstance(encoded, str) or len(encoded) > (max_bytes * 4 // 3 + 8):
        raise LiveClientError("Speech audio is missing or too large.")
    try:
        data = base64.b64decode(encoded, validate=True)
        audio = load_pcm_wav_bytes(data)
        with wave.open(BytesIO(data), "rb") as reader:
            if reader.getsampwidth() != 2 or reader.getnframes() > 24000 * 30 or int.from_bytes(data[4:8], "little") != len(data) - 8:
                raise LiveClientError("Translated speech audio has an incompatible format.")
    except (binascii.Error, WavError, wave.Error) as exc:
        raise LiveClientError("Invalid translated speech audio.") from exc
    if len(data) > max_bytes or audio.sample_rate != 24000 or audio.samples.shape[1] != 1 or not data.startswith(b"RIFF"):
        raise LiveClientError("Translated speech audio has an incompatible format.")
    return data


class TranslationConnection:
    """One phrase at a time: result then optional speech_audio or speech_error."""

    def __init__(self, server: str, session_cookie: str, source: str, target: str,
                 *, save_history: bool = False, session_id: str | None = None,
                 connector: Any = connect) -> None:
        self.origin = server_origin(server)
        self.source = language_code(source, allow_auto=True)
        self.target = language_code(target)
        if save_history != (session_id is not None):
            raise LiveClientError("History requires both --save-history and --session-id.")
        if session_id:
            try:
                uuid.UUID(session_id)
            except ValueError as exc:
                raise LiveClientError("History session ID must be a UUID.") from exc
        self.save_history = save_history
        self.session_id = session_id
        self.cookie = session_cookie
        self.connector = connector
        self.socket: Any = None
        self.next_chunk_id = 1

    def __enter__(self) -> "TranslationConnection":
        ws_url = self.origin.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws/translate"
        try:
            self.socket = self.connector(ws_url, origin=self.origin,
                                         additional_headers={"Cookie": f"talkbuddy_session={self.cookie}"},
                                         open_timeout=10, max_size=4 * 1024 * 1024)
            start = {"type": "start", "target_language": self.target, "audio_format": "wav",
                     "save_history": self.save_history, "synthesize_speech": True}
            if self.source != "auto":
                start["source_language"] = self.source
            if self.session_id:
                start["session_id"] = self.session_id
            self.socket.send(json.dumps(start))
            message = self._receive()
            if message.get("type") != "ready" or message.get("target_language") != self.target:
                raise LiveClientError("Translation socket did not become ready. Check authentication, language, and TTS configuration.")
            return self
        except Exception as exc:
            self.close()
            if isinstance(exc, LiveClientError):
                raise
            raise LiveClientError("Translation connection failed. Check backend, authentication, and Origin settings.") from exc

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self.socket is not None:
            try:
                self.socket.send(json.dumps({"type": "stop"}))
            except Exception:
                pass
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None

    def _receive(self) -> dict[str, Any]:
        try:
            raw = self.socket.recv(timeout=145)
            if not isinstance(raw, str):
                raise LiveClientError("Unexpected binary server message.")
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise LiveClientError("Invalid server message.")
            return message
        except (ValueError, TypeError) as exc:
            raise LiveClientError("Invalid server response.") from exc
        except LiveClientError:
            raise
        except Exception as exc:
            raise LiveClientError("Translation socket disconnected or timed out.") from exc

    def translate(self, phrase: CapturedPhrase) -> SpeechResponse:
        if self.socket is None:
            raise LiveClientError("Translation socket is closed.")
        if len(phrase.wav_bytes) > 1024 * 1024:
            raise LiveClientError("Phrase exceeds the backend audio limit.")
        if self.save_history:
            self.socket.send(json.dumps({"type": "chunk", "request_id": phrase.phrase_id}))
        submitted = time.perf_counter() * 1000
        self.socket.send(phrase.wav_bytes)
        expected = self.next_chunk_id
        result: dict[str, Any] | None = None
        while result is None:
            message = self._receive()
            kind = message.get("type")
            if kind == "processing" and message.get("chunk_id") == expected:
                continue
            if kind == "error":
                raise LiveClientError(f"Translation failed ({str(message.get('code', 'unknown'))[:40]}).")
            if kind != "result" or message.get("chunk_id") != expected:
                raise LiveClientError("Unexpected translation response order.")
            if not isinstance(message.get("original"), str) or not isinstance(message.get("translated"), str):
                raise LiveClientError("Translation result is incomplete.")
            result = message
        roundtrip = time.perf_counter() * 1000 - submitted
        audio_message = self._receive()
        if audio_message.get("type") == "speech_error" and audio_message.get("chunk_id") == expected:
            audio = None
            speech_error = str(audio_message.get("code", "speech_unavailable"))[:40]
            tts_ms = None
        else:
            audio = parse_speech_audio(audio_message, expected)
            speech_error = None
            tts_ms = audio_message.get("preparation_time_ms") if isinstance(audio_message.get("preparation_time_ms"), int) else None
        self.next_chunk_id += 1
        return SpeechResponse(
            expected, result["original"], result["translated"], audio, submitted, roundtrip,
            result.get("transcription_time_ms") if isinstance(result.get("transcription_time_ms"), int) else None,
            result.get("translation_time_ms") if isinstance(result.get("translation_time_ms"), int) else None,
            tts_ms, time.perf_counter() * 1000, speech_error,
        )
