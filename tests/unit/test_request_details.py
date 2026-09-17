"""Request-level assertions: verify what actually reaches the wire.

Covers the mutation surface that response-level tests alone cannot
kill: forwarded headers, timeout values, accepted status codes, the
multipart field layout, and retry adapter configuration.
"""

from io import BytesIO
from typing import Any

import httpx
import pytest
import requests
from requests.adapters import HTTPAdapter

from pyseaweed.async_client import AsyncConnection, AsyncSeaweedFS
from pyseaweed.async_filer import AsyncFiler
from pyseaweed.filer import Filer
from pyseaweed.seaweed import SeaweedFS
from pyseaweed.utils import Connection


class _BytesRaw:
    """Minimal urllib3-style raw object for hand-built Responses."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def stream(self, chunk_size: int, decode_content: bool = True) -> Any:
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i : i + chunk_size]

    def read(self, amt: int = -1) -> bytes:
        return self.data

    def close(self) -> None:
        pass


class _SpyAdapter(HTTPAdapter):
    """Adapter that records send() calls and returns a canned response."""

    def __init__(self, status: int = 200, body: bytes = b"OK") -> None:
        super().__init__()
        self.status = status
        self.body = body
        self.requests: list[requests.PreparedRequest] = []
        self.kwargs_list: list[dict[str, Any]] = []

    def send(
        self, request: Any, stream: bool = False, timeout: Any = None, verify: bool | str = True, cert: Any = None, proxies: Any = None
    ) -> requests.Response:
        self.requests.append(request)
        self.kwargs_list.append({"timeout": timeout})
        resp = requests.Response()
        resp.status_code = self.status
        resp.raw = _BytesRaw(self.body)
        resp.url = request.url
        resp.request = request
        return resp


def _spy_conn(status: int = 200, body: bytes = b"OK", **conn_kwargs: Any) -> tuple[Connection, _SpyAdapter]:
    conn = Connection(use_session=True, **conn_kwargs)
    adapter = _SpyAdapter(status=status, body=body)
    conn._conn.mount("http://", adapter)
    conn._conn.mount("https://", adapter)
    return conn, adapter


def _spy_async(status: int = 200, **conn_kwargs: Any) -> tuple[AsyncConnection, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=b"OK")

    conn = AsyncConnection(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **conn_kwargs)
    return conn, seen


class TestSyncRequestDetails:
    def test_default_connection_uses_plain_requests(self) -> None:
        conn = Connection()
        assert conn._conn is requests
        assert conn.timeout is None
        conn.close()

    def test_chunk_size_default(self) -> None:
        conn, _spy = _spy_conn(body=b"z" * 20000)
        stream = conn.get_stream("http://x")
        assert stream is not None
        assert [len(c) for c in stream] == [8192, 8192, 3616]
        conn.close()

    def test_user_agent_without_additional_headers(self) -> None:
        conn, spy = _spy_conn()
        conn.get_data("http://x")
        assert str(spy.requests[0].headers["User-Agent"]).startswith("pyseaweed/")
        conn.close()

    def test_headers_reach_wire(self) -> None:
        conn, spy = _spy_conn()
        conn.get_data("http://x", additional_headers={"X-Custom": "v"})
        conn.get_raw_data("http://x", additional_headers={"X-Custom": "v"})
        conn.get_stream("http://x", additional_headers={"X-Custom": "v"})
        conn.head("http://x", additional_headers={"X-Custom": "v"})
        conn.delete_data("http://x", additional_headers={"X-Custom": "v"})
        conn.post("http://x", additional_headers={"X-Custom": "v"})
        conn.put("http://x", additional_headers={"X-Custom": "v"})
        with open(__file__, "rb") as f:
            conn.post_file("http://x", "t.py", f, additional_headers={"X-Custom": "v"})
        assert len(spy.requests) == 8
        for req in spy.requests:
            assert str(req.headers["user-agent"]).startswith("pyseaweed/")
            assert req.headers["X-Custom"] == "v"
        conn.close()

    def test_timeout_reaches_transport(self) -> None:
        conn, spy = _spy_conn(timeout=12.5)
        conn.get_data("http://x")
        conn.get_data("http://x", timeout=1.0)
        conn.head("http://x")
        conn.head("http://x", timeout=1.1)
        conn.get_raw_data("http://x")
        conn.get_raw_data("http://x", timeout=1.2)
        conn.get_stream("http://x")
        conn.get_stream("http://x", timeout=1.3)
        conn.delete_data("http://x")
        conn.delete_data("http://x", timeout=1.4)
        conn.post("http://x")
        conn.post("http://x", timeout=1.5)
        conn.put("http://x")
        conn.put("http://x", timeout=1.6)
        with open(__file__, "rb") as f:
            conn.post_file("http://x", "t.py", f)
        with open(__file__, "rb") as f:
            conn.post_file("http://x", "t.py", f, timeout=2.5)
        expected = [12.5, 1.0, 12.5, 1.1, 12.5, 1.2, 12.5, 1.3, 12.5, 1.4, 12.5, 1.5, 12.5, 1.6, 12.5, 2.5]
        assert [kw["timeout"] for kw in spy.kwargs_list] == expected
        conn.close()

    def test_no_timeout_by_default(self) -> None:
        conn, spy = _spy_conn()
        conn.get_data("http://x")
        assert spy.kwargs_list[0]["timeout"] is None
        conn.close()

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(199, False), (200, True), (204, True), (299, True), (300, False), (301, False), (404, False), (500, False)],
    )
    def test_status_boundaries(self, status: int, expected: bool) -> None:
        conn, _spy = _spy_conn(status=status)
        assert (conn.get_data("http://x") is not None) == expected
        assert (conn.get_raw_data("http://x") is not None) == expected
        assert (conn.get_stream("http://x") is not None) == expected
        assert (conn.head("http://x") is not None) == expected
        assert conn.delete_data("http://x") == expected
        assert conn.post("http://x") == expected
        assert conn.put("http://x") == expected
        with open(__file__, "rb") as f:
            assert (conn.post_file("http://x", "t.py", f) is not None) == expected
        conn.close()

    def test_multipart_structure(self) -> None:
        conn, spy = _spy_conn()
        conn.post_file("http://x", "myfile.bin", BytesIO(b"payload"))
        conn.post_file("http://x", "myfile.bin", BytesIO(b"payload"), content_type="application/x-bin")
        body0 = spy.requests[0].body
        body1 = spy.requests[1].body
        assert isinstance(body0, bytes) and isinstance(body1, bytes)
        # 2-tuple form: no per-part content type header
        assert b'name="file"; filename="myfile.bin"\r\n\r\npayload' in body0
        # 3-tuple form: content type lands on the part
        assert b'name="file"; filename="myfile.bin"\r\nContent-Type: application/x-bin\r\n\r\npayload' in body1
        conn.close()

    def test_retry_adapter_configuration(self) -> None:
        conn = Connection(retries=3)
        session = conn._conn
        assert isinstance(session, requests.Session)
        for scheme in ("http://", "https://"):
            adapter = session.adapters[scheme]
            assert isinstance(adapter, HTTPAdapter)
            retry = adapter.max_retries
            assert retry.total == 3
            assert retry.backoff_factor == 0.3
            assert set(retry.status_forcelist) == {500, 502, 503, 504}
        conn.close()


class TestAsyncRequestDetails:
    async def test_chunk_size_default(self) -> None:
        transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"z" * 20000))
        conn = AsyncConnection(client=httpx.AsyncClient(transport=transport))
        sizes = [len(c) async for c in conn.get_stream("http://x")]
        assert sizes == [8192, 8192, 3616]
        await conn.close()

    async def test_user_agent_without_additional_headers(self) -> None:
        conn, seen = _spy_async()
        await conn.get_data("http://x")
        assert seen[0].headers["user-agent"].startswith("pyseaweed/")
        await conn.close()

    async def test_headers_reach_wire(self) -> None:
        conn, seen = _spy_async()
        await conn.get_data("http://x", additional_headers={"X-Custom": "v"})
        await conn.get_raw_data("http://x", additional_headers={"X-Custom": "v"})
        async for _ in conn.get_stream("http://x", additional_headers={"X-Custom": "v"}):
            pass
        await conn.head("http://x", additional_headers={"X-Custom": "v"})
        await conn.delete_data("http://x", additional_headers={"X-Custom": "v"})
        await conn.post("http://x", additional_headers={"X-Custom": "v"})
        await conn.put("http://x", additional_headers={"X-Custom": "v"})
        with open(__file__, "rb") as f:
            await conn.post_file("http://x", "t.py", f, additional_headers={"X-Custom": "v"})
        assert len(seen) == 8
        for req in seen:
            assert str(req.headers["user-agent"]).startswith("pyseaweed/")
            assert req.headers["x-custom"] == "v"
        await conn.close()

    async def test_timeout_reaches_transport(self) -> None:
        conn, seen = _spy_async(timeout=12.5)
        await conn.get_data("http://x")
        await conn.get_data("http://x", timeout=1.0)
        await conn.head("http://x")
        await conn.head("http://x", timeout=1.1)
        await conn.get_raw_data("http://x")
        await conn.get_raw_data("http://x", timeout=1.2)
        async for _ in conn.get_stream("http://x"):
            pass
        async for _ in conn.get_stream("http://x", timeout=1.3):
            pass
        await conn.delete_data("http://x")
        await conn.delete_data("http://x", timeout=1.4)
        await conn.post("http://x")
        await conn.post("http://x", timeout=1.5)
        await conn.put("http://x")
        await conn.put("http://x", timeout=1.6)
        with open(__file__, "rb") as f:
            await conn.post_file("http://x", "t.py", f)
        with open(__file__, "rb") as f:
            await conn.post_file("http://x", "t.py", f, timeout=2.5)
        expected = [12.5, 1.0, 12.5, 1.1, 12.5, 1.2, 12.5, 1.3, 12.5, 1.4, 12.5, 1.5, 12.5, 1.6, 12.5, 2.5]
        assert [set(req.extensions["timeout"].values()).pop() for req in seen] == expected
        await conn.close()

    async def test_no_timeout_by_default(self) -> None:
        conn, seen = _spy_async()
        await conn.get_data("http://x")
        assert set(seen[0].extensions["timeout"].values()) == {None}
        await conn.close()

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(199, False), (200, True), (204, True), (299, True), (300, False), (301, False), (404, False), (500, False)],
    )
    async def test_status_boundaries(self, status: int, expected: bool) -> None:
        conn, _seen = _spy_async(status=status)
        assert (await conn.get_data("http://x") is not None) == expected
        assert (await conn.get_raw_data("http://x") is not None) == expected
        chunks = [c async for c in conn.get_stream("http://x")]
        assert bool(chunks) == expected
        assert (await conn.head("http://x") is not None) == expected
        assert await conn.delete_data("http://x") == expected
        assert await conn.post("http://x") == expected
        assert await conn.put("http://x") == expected
        with open(__file__, "rb") as f:
            assert (await conn.post_file("http://x", "t.py", f) is not None) == expected
        await conn.close()

    async def test_multipart_structure(self) -> None:
        conn, seen = _spy_async()
        with open(__file__, "rb") as f:
            await conn.post_file("http://x", "myfile.bin", f)
        with open(__file__, "rb") as f:
            await conn.post_file("http://x", "myfile.bin", f, content_type="application/x-bin")
        body0 = await seen[0].aread()
        body1 = await seen[1].aread()
        assert b'name="file"' in body0
        assert b'filename="myfile.bin"' in body0
        assert b"Content-Type: application/x-bin" in body1
        await conn.close()

    async def test_chunk_size_passthrough(self) -> None:
        def big_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"0123456789")

        conn = AsyncConnection(client=httpx.AsyncClient(transport=httpx.MockTransport(big_handler)))
        chunks = [c async for c in conn.get_stream("http://x", chunk_size=4)]
        assert [len(c) for c in chunks] == [4, 4, 2]
        await conn.close()

    async def test_retry_backoff_delays(self, monkeypatch: pytest.MonkeyPatch) -> None:
        delays: list[float] = []

        async def record_sleep(d: float) -> None:
            delays.append(d)

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", record_sleep)
        conn, _seen = _spy_async(status=503, retries=2)
        assert await conn.get_data("http://x") is None
        assert delays == [0.3, 0.6]
        await conn.close()

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    async def test_retryable_statuses(self, status: int) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(status if calls["n"] == 1 else 200, text="OK")

        conn = AsyncConnection(retries=1, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await conn.get_data("http://x") == "OK"
        assert calls["n"] == 2
        await conn.close()


class TestConstructorPassthrough:
    def test_filer_conn_settings(self) -> None:
        filer = Filer(filer_addr="10.0.0.1", filer_port=9999, timeout=4.5, retries=2)
        assert filer.filer_addr == "10.0.0.1"
        assert filer.filer_port == 9999
        assert filer.conn.timeout == 4.5
        session = filer.conn._conn
        assert isinstance(session, requests.Session)
        adapter = session.adapters["http://"]
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == 2
        filer.close()

    def test_seaweed_conn_settings(self) -> None:
        w = SeaweedFS(master_addr="10.0.0.1", master_port=9999, timeout=4.5, retries=2)
        assert w.master_addr == "10.0.0.1"
        assert w.master_port == 9999
        assert w.conn.timeout == 4.5
        session = w.conn._conn
        assert isinstance(session, requests.Session)
        adapter = session.adapters["http://"]
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == 2
        w.close()

    async def test_async_filer_conn_settings(self) -> None:
        filer = AsyncFiler(filer_addr="10.0.0.1", filer_port=9999, timeout=4.5, retries=2)
        assert filer.filer_addr == "10.0.0.1"
        assert filer.filer_port == 9999
        assert filer.conn.timeout == 4.5
        assert filer.conn.retries == 2
        await filer.close()

    async def test_async_seaweed_conn_settings(self) -> None:
        w = AsyncSeaweedFS(master_addr="10.0.0.1", master_port=9999, timeout=4.5, retries=2)
        assert w.master_addr == "10.0.0.1"
        assert w.master_port == 9999
        assert w.conn.timeout == 4.5
        assert w.conn.retries == 2
        await w.close()

    async def test_async_defaults_no_retries(self) -> None:
        w = AsyncSeaweedFS()
        assert w.conn.retries == 0
        await w.close()
        filer = AsyncFiler()
        assert filer.conn.retries == 0
        await filer.close()

    def test_getattr_raises_attribute_error(self) -> None:
        import pyseaweed

        with pytest.raises(AttributeError, match="no attribute"):
            pyseaweed.NoSuchThing  # noqa: B018
