"""Validate that each binary frame is a complete PCM WAV file."""

import io
import wave


class InvalidAudioChunk(ValueError):
    """A binary frame cannot be decoded as one complete WAV chunk."""


def validate_wav_chunk(data: bytes, max_bytes: int) -> None:
    if not data:
        raise InvalidAudioChunk("Empty audio chunk")
    if len(data) > max_bytes:
        raise InvalidAudioChunk("Audio chunk too large")
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise InvalidAudioChunk("Invalid WAV header")
    if int.from_bytes(data[4:8], "little") != len(data) - 8:
        raise InvalidAudioChunk("Incomplete WAV container")

    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if audio.getcomptype() != "NONE" or audio.getnframes() == 0:
                raise InvalidAudioChunk("Unsupported or empty WAV audio")
            frame_size = audio.getnchannels() * audio.getsampwidth()
            if frame_size <= 0 or audio.getframerate() <= 0:
                raise InvalidAudioChunk("Invalid WAV metadata")
            frames = audio.readframes(audio.getnframes())
            if len(frames) != audio.getnframes() * frame_size:
                raise InvalidAudioChunk("Incomplete WAV frames")
    except (EOFError, wave.Error) as exc:
        raise InvalidAudioChunk("Invalid WAV audio") from exc
