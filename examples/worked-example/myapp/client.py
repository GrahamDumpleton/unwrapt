"""The client module: a from-import, which the report flags as
deferrable on Python 3.15 but not by the shim on older versions."""

from difflib import SequenceMatcher

import wave


def match(left: str, right: str) -> float:
    """Compare two strings."""

    return SequenceMatcher(None, left, right).ratio()


def silence(seconds: float) -> bytes:
    """Return that many seconds of silence."""

    import io

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(1)
        writer.setframerate(8000)
        writer.writeframes(b"\x00" * int(seconds * 8000))

    return buffer.getvalue()
