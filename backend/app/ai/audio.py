"""Bounded upload reading and basic audio format validation."""

from fastapi import HTTPException, UploadFile, status


ALLOWED_MEDIA_TYPES: dict[str, frozenset[str]] = {
    ".flac": frozenset({"audio/flac", "audio/x-flac"}),
    ".mp3": frozenset({"audio/mpeg", "audio/mp3"}),
    ".mp4": frozenset({"audio/mp4", "video/mp4"}),
    ".mpeg": frozenset({"audio/mpeg"}),
    ".mpga": frozenset({"audio/mpeg"}),
    ".m4a": frozenset({"audio/mp4", "audio/x-m4a", "audio/m4a"}),
    ".ogg": frozenset({"audio/ogg", "application/ogg"}),
    ".wav": frozenset({"audio/wav", "audio/x-wav", "audio/wave"}),
    ".webm": frozenset({"audio/webm", "video/webm"}),
}


def _looks_like_audio(data: bytes, extension: str) -> bool:
    if extension == ".wav":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    if extension == ".flac":
        return data.startswith(b"fLaC")
    if extension == ".ogg":
        return data.startswith(b"OggS")
    if extension == ".webm":
        return data.startswith(b"\x1a\x45\xdf\xa3")
    if extension in {".mp4", ".m4a"}:
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if extension in {".mp3", ".mpeg", ".mpga"}:
        return data.startswith(b"ID3") or (
            len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
        )
    return False


async def read_audio_upload(upload: UploadFile, max_bytes: int) -> tuple[bytes, str]:
    """Read at most one byte beyond the configured limit; never retain the file."""

    try:
        extension = "." + (upload.filename or "").rsplit(".", 1)[-1].lower()
        content_type = (upload.content_type or "").lower()
        if extension not in ALLOWED_MEDIA_TYPES or content_type not in ALLOWED_MEDIA_TYPES[extension]:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported audio type"
            )
        data = await upload.read(max_bytes + 1)
    finally:
        await upload.close()
    if not data:
        raise HTTPException(status_code=422, detail="Audio file is empty")
    if len(data) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Audio file is too large")
    if not _looks_like_audio(data, extension):
        raise HTTPException(status_code=415, detail="Unsupported or invalid audio data")
    return data, f"audio{extension}"
