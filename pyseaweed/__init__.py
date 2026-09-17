# vi:si:et:sw=4:sts=4:ts=4


"""PySeaweed - a Python client library for SeaweedFS."""

from pyseaweed.seaweed import SeaweedFS  # noqa: F401
from pyseaweed.version import __version__

WeedFS = SeaweedFS  # for backward compatibilty

VERSION: str = __version__
