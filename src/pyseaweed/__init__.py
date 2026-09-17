"""PySeaweed - a Python client library for SeaweedFS."""

from typing import TYPE_CHECKING

from pyseaweed.exceptions import BadFidFormat
from pyseaweed.filer import Filer
from pyseaweed.seaweed import FileLocation, SeaweedFS
from pyseaweed.version import __version__

if TYPE_CHECKING:
    from pyseaweed.async_client import AsyncSeaweedFS
    from pyseaweed.async_filer import AsyncFiler

WeedFS = SeaweedFS  # for backward compatibility

VERSION = __version__

__all__ = [
    "VERSION",
    "AsyncFiler",
    "AsyncSeaweedFS",
    "BadFidFormat",
    "FileLocation",
    "Filer",
    "SeaweedFS",
    "WeedFS",
    "__version__",
]

_ASYNC_EXPORTS = {
    "AsyncSeaweedFS": "pyseaweed.async_client",
    "AsyncFiler": "pyseaweed.async_filer",
}


def __getattr__(name: str) -> object:
    """Lazily expose the async clients so httpx stays an optional dependency."""
    if name in _ASYNC_EXPORTS:
        try:
            module = __import__(_ASYNC_EXPORTS[name], fromlist=[name])
            return getattr(module, name)
        except ImportError as exc:
            raise ImportError(f"{name} requires httpx. Install it with: pip install pyseaweed[async]") from exc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
