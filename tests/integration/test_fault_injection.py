"""Live fault-injection tests against SeaweedFS through toxiproxy.

These tests route client traffic through a real TCP proxy and inject
network-level faults (latency, connection resets, stalled responses,
truncated bodies) to verify client behavior under real failure
conditions.

Requires the toxiproxy sidecar started by ``make weed-up`` /
``make test-integration-local`` and CI.
"""

import io
import uuid

import pytest
import requests

from pyseaweed.async_filer import AsyncFiler
from pyseaweed.filer import Filer
from pyseaweed.seaweed import SeaweedFS

from .conftest import TOXIPROXY_API, ToxicAdder

pytestmark = pytest.mark.integration

FILER_PROXY_PORT = 28888
MASTER_PROXY_PORT = 29333


@pytest.fixture()
def base() -> str:
    return f"/test-fault-{uuid.uuid4().hex[:12]}"


class TestSyncFaults:
    def test_latency_causes_client_timeout(self, add_toxic: ToxicAdder) -> None:
        add_toxic("filer-proxy", "lat", "latency", {"latency": 3000})
        filer = Filer(filer_port=FILER_PROXY_PORT, timeout=0.5)
        assert filer.exists("/") is False
        filer.close()

    def test_timeout_toxic_stalls_response(self, add_toxic: ToxicAdder) -> None:
        add_toxic("filer-proxy", "stop", "timeout", {"timeout": 3000})
        filer = Filer(filer_port=FILER_PROXY_PORT, timeout=0.5)
        assert filer.download_file("/x") is None
        filer.close()

    def test_reset_peer(self, add_toxic: ToxicAdder) -> None:
        add_toxic("filer-proxy", "rst", "reset_peer", {"timeout": 0})
        filer = Filer(filer_port=FILER_PROXY_PORT, timeout=5)
        assert filer.exists("/") is False
        filer.close()

    def test_limit_data_truncates_download(self, add_toxic: ToxicAdder, base: str) -> None:
        direct = Filer(timeout=10)
        direct.upload_file(f"{base}/big.bin", stream=io.BytesIO(b"x" * 65536), name="big.bin")
        try:
            # 4 KiB lets the response headers through, truncates the body
            add_toxic("filer-proxy", "limit", "limit_data", {"bytes": 4096})
            filer = Filer(filer_port=FILER_PROXY_PORT, timeout=10)
            stream = filer.get_file_stream(f"{base}/big.bin")
            assert stream is not None
            with pytest.raises(requests.exceptions.ChunkedEncodingError):
                b"".join(stream)
            filer.close()
        finally:
            assert direct.delete(base, recursive=True)
            direct.close()

    def test_master_latency_causes_timeout(self, add_toxic: ToxicAdder) -> None:
        add_toxic("master-proxy", "lat", "latency", {"latency": 3000})
        weed = SeaweedFS(master_port=MASTER_PROXY_PORT, timeout=0.5)
        assert weed.is_healthy() is False
        weed.close()

    def test_recovery_after_toxic_removed(self, add_toxic: ToxicAdder) -> None:
        add_toxic("filer-proxy", "rst", "reset_peer", {"timeout": 0})
        filer = Filer(filer_port=FILER_PROXY_PORT, timeout=5)
        assert filer.exists("/") is False
        requests.delete(f"{TOXIPROXY_API}/proxies/filer-proxy/toxics/rst")
        assert filer.exists("/") is True
        filer.close()


class TestAsyncFaults:
    async def test_latency_causes_client_timeout(self, add_toxic: ToxicAdder) -> None:
        add_toxic("filer-proxy", "lat", "latency", {"latency": 3000})
        async with AsyncFiler(filer_port=FILER_PROXY_PORT, timeout=0.5) as filer:
            assert await filer.exists("/") is False

    async def test_reset_peer(self, add_toxic: ToxicAdder) -> None:
        add_toxic("filer-proxy", "rst", "reset_peer", {"timeout": 0})
        async with AsyncFiler(filer_port=FILER_PROXY_PORT, timeout=5) as filer:
            assert await filer.exists("/") is False

    async def test_limit_data_truncates_stream(self, add_toxic: ToxicAdder, base: str) -> None:
        async with AsyncFiler(timeout=10) as direct:
            await direct.upload_file(f"{base}/big.bin", stream=io.BytesIO(b"x" * 65536), name="big.bin")
            try:
                add_toxic("filer-proxy", "limit", "limit_data", {"bytes": 4096})
                async with AsyncFiler(filer_port=FILER_PROXY_PORT, timeout=10) as filer:
                    chunks = [c async for c in await filer.get_file_stream(f"{base}/big.bin")]
                    # the mid-stream error is swallowed: at most the
                    # truncated prefix is delivered
                    assert len(b"".join(chunks)) < 65536
            finally:
                assert await direct.delete(base, recursive=True)
