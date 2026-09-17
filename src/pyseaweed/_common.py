"""Shared helpers used by the sync and async SeaweedFS clients."""

import os
import re
from typing import BinaryIO

from pyseaweed.version import __version__

FID_PATTERN = re.compile(r"^(\d+),([0-9a-fA-F]+(?:\.[A-Za-z0-9_-]+)?)$")


def prepare_headers(additional_headers: dict[str, str] | None = None) -> dict[str, str]:
    """Prepare headers for http communication.

    Return dict of headers to be used in requests.

    Args:
        additional_headers: Additional headers to be used
            with the request.

    Returns:
        Headers dict. Keys and values are strings.

    """
    user_agent = f"pyseaweed/{__version__}"
    headers = {"User-Agent": user_agent}
    if additional_headers is not None:
        headers.update(additional_headers)
    return headers


def range_headers(byte_range: tuple[int | None, int | None] | None) -> dict[str, str] | None:
    """Build a ``Range`` request header from a (start, end) tuple.

    Either bound may be None to leave it open (e.g. ``(None, 500)``
    requests the last 500 bytes, ``(100, None)`` requests from byte
    100 to the end). ``(None, None)`` is treated like no range.
    """
    if byte_range is None or byte_range == (None, None):
        return None
    start, end = byte_range
    return {"Range": f"bytes={'' if start is None else start}-{'' if end is None else end}"}


def prepare_stream(
    path: str | None,
    stream: BinaryIO | None,
    name: str | None,
) -> tuple[str, BinaryIO, bool]:
    """Resolve path/stream/name into a (filename, stream, close) triple.

    The returned flag indicates whether the caller owns the stream
    (opened from ``path``) and must close it afterwards.
    """
    if path is not None:
        filename = os.path.basename(path) if name is None else name
        return filename, open(path, "rb"), True
    if stream is not None and name is not None:
        return name, stream, False
    raise ValueError("If `path` is None then *both* `stream` and `name` must not be None")
