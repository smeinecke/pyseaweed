"""PySeaweed - a Python client library for SeaweedFS."""

from pyseaweed.exceptions import BadFidFormat
from pyseaweed.seaweed import FileLocation, SeaweedFS
from pyseaweed.version import __version__

WeedFS = SeaweedFS  # for backward compatibility

VERSION = __version__

__all__ = [
    "VERSION",
    "BadFidFormat",
    "FileLocation",
    "SeaweedFS",
    "WeedFS",
    "__version__",
]
