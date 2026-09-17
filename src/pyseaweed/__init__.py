"""PySeaweed - a Python client library for SeaweedFS."""

from typing import TYPE_CHECKING

from pyseaweed.exceptions import BadFidFormat
from pyseaweed.filer import Filer
from pyseaweed.seaweed import FileLocation, SeaweedFS
from pyseaweed.version import __version__

if TYPE_CHECKING:
    from pyseaweed.async_client import AsyncSeaweedFS

WeedFS = SeaweedFS  # for backward compatibility

VERSION = __version__

__all__ = [
    "VERSION",
    "AsyncSeaweedFS",
    "BadFidFormat",
    "FileLocation",
    "Filer",
    "SeaweedFS",
    "WeedFS",
    "__version__",
]


def __getattr__(name: str) -> object:
    """Lazily expose AsyncSeaweedFS so httpx stays an optional dependency."""
    if name == "AsyncSeaweedFS":
        try:
            from pyseaweed.async_client import AsyncSeaweedFS
        except ImportError as exc:
            raise ImportError("AsyncSeaweedFS requires httpx. Install it with: pip install pyseaweed[async]") from exc
        return AsyncSeaweedFS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
