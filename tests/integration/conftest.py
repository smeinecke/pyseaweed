"""Shared fixtures for integration tests.

Provides the toxiproxy fixtures used by the live fault-injection tests.
toxiproxy is started by ``make weed-up`` (and CI) on admin port 8474;
two proxies are pre-configured:

- ``master-proxy``: localhost:29333 -> localhost:9333
- ``filer-proxy``:  localhost:28888 -> localhost:8888
"""

from collections.abc import Callable, Generator
from typing import Any

import pytest
import requests

TOXIPROXY_API = "http://localhost:8474"

PROXIES = {
    "master-proxy": ("localhost:29333", "localhost:9333"),
    "filer-proxy": ("localhost:28888", "localhost:8888"),
}

ToxicAdder = Callable[[str, str, str, dict[str, Any]], None]


def _toxiproxy_available() -> bool:
    try:
        return requests.get(f"{TOXIPROXY_API}/version", timeout=2).ok
    except requests.RequestException:
        return False


@pytest.fixture(scope="session")
def toxiproxy() -> Generator[str]:
    """Provide the toxiproxy admin URL with proxies configured.

    Skips when toxiproxy isn't running so integration tests can still
    run against a bare ``weed server`` without the fault-injection
    sidecar.
    """
    if not _toxiproxy_available():
        pytest.skip("toxiproxy not running on :8474 (started by make weed-up)")
    for name, (listen, upstream) in PROXIES.items():
        requests.delete(f"{TOXIPROXY_API}/proxies/{name}")
        res = requests.post(
            f"{TOXIPROXY_API}/proxies",
            json={"name": name, "listen": f"{listen}", "upstream": upstream},
        )
        assert res.status_code == 201, res.text
    yield TOXIPROXY_API
    requests.post(f"{TOXIPROXY_API}/reset")


@pytest.fixture()
def add_toxic(toxiproxy: str) -> Generator[ToxicAdder]:
    """Add a toxic to a proxy; all toxics are removed after the test."""

    def _add(proxy: str, name: str, toxic_type: str, attributes: dict[str, Any]) -> None:
        res = requests.post(
            f"{toxiproxy}/proxies/{proxy}/toxics",
            json={
                "name": name,
                "type": toxic_type,
                "stream": "downstream",
                "toxicity": 1.0,
                "attributes": attributes,
            },
        )
        assert res.status_code == 200, res.text

    yield _add
    requests.post(f"{toxiproxy}/reset")
