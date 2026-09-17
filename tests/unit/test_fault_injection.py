"""Fault-injection tests: transport-level failures for both clients.

The ``faulty_server`` fixture runs a real localhost HTTP server that can
return canned 5xx responses, close connections without answering, and
truncate response bodies mid-stream. That exercises the real urllib3
retry machinery and real connection-reset/truncation paths that pure
mocks cannot reach.
"""

import socket
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
import requests
from requests.adapters import HTTPAdapter

from pyseaweed.async_client import AsyncConnection
from pyseaweed.utils import Connection


class _FaultyServer(ThreadingHTTPServer):
    daemon_threads = True
    script: list[Any]
    calls: int


class _ScriptHandler(BaseHTTPRequestHandler):
    """HTTP/1.1 handler executing a per-request script of canned behaviors.

    ``server.script`` entries are consumed one per request (the last entry
    repeats). Each entry is one of:
      - ``("status", code, body)``: respond normally
      - ``("partial", body, declared_length)``: declare a longer body than
        is actually sent, then close the connection abruptly
      - ``"reset"``: close the connection without answering
    """

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._serve(head=False)

    def do_HEAD(self) -> None:
        self._serve(head=True)

    def do_DELETE(self) -> None:
        self._serve(head=False)

    def _serve(self, head: bool) -> None:
        server = self.server
        assert isinstance(server, _FaultyServer)
        action = server.script[min(server.calls, len(server.script) - 1)]
        server.calls += 1

        if action == "reset":
            self.close_connection = True
            self.connection.close()
            return

        if action[0] == "partial":
            body, declared = action[1], action[2]
            self.send_response(200)
            self.send_header("Content-Length", str(declared))
            self.send_header("Connection", "close")
            self.end_headers()
            if not head:
                self.wfile.write(body)
                self.wfile.flush()
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return

        _, status, body = action
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if not head:
            self.wfile.write(body)
        self.close_connection = True

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture()
def faulty_server() -> Generator[_FaultyServer]:
    server = _FaultyServer(("127.0.0.1", 0), _ScriptHandler)
    server.script = [("status", 200, b"OK")]
    server.calls = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join()
    server.server_close()


def _url(server: _FaultyServer, path: str = "/x") -> str:
    return f"http://127.0.0.1:{server.server_address[1]}{path}"


class _RaisingAdapter(HTTPAdapter):
    """Adapter that always raises the given exception on send."""

    def __init__(self, exc: requests.RequestException) -> None:
        super().__init__()
        self.exc = exc

    def send(
        self, request: Any, stream: bool = False, timeout: Any = None, verify: bool | str = True, cert: Any = None, proxies: Any = None
    ) -> Any:
        raise self.exc


class TestSyncFaultInjection:
    def test_session_transport_faults(self) -> None:
        for exc in (requests.ConnectionError("down"), requests.Timeout("slow"), requests.exceptions.SSLError("bad cert")):
            conn = Connection(use_session=True)
            conn._conn.mount("http://", _RaisingAdapter(exc))
            assert conn.get_data("http://utek.pl") is None
            assert conn.get_raw_data("http://utek.pl") is None
            assert conn.get_stream("http://utek.pl") is None
            assert conn.head("http://utek.pl") is None
            assert not conn.delete_data("http://utek.pl")
            assert not conn.post("http://utek.pl")
            assert not conn.put("http://utek.pl")
            with open(__file__, "rb") as f:
                assert conn.post_file("http://utek.pl", "t.py", f) is None
            conn.close()

    def test_retry_recovers_from_5xx(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = [("status", 503, b"err"), ("status", 503, b"err"), ("status", 200, b"OK")]
        conn = Connection(retries=3)
        assert conn.get_data(_url(faulty_server)) == "OK"
        assert faulty_server.calls == 3

    def test_retry_exhausted(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = [("status", 503, b"err")]
        conn = Connection(retries=1)
        assert conn.get_data(_url(faulty_server)) is None
        assert faulty_server.calls == 2

    def test_no_retry_without_retries(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = [("status", 503, b"err")]
        conn = Connection()
        assert conn.get_data(_url(faulty_server)) is None
        assert faulty_server.calls == 1

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_each_retryable_status_recovers(self, faulty_server: _FaultyServer, status: int) -> None:
        faulty_server.script = [("status", status, b"err"), ("status", 200, b"OK")]
        conn = Connection(retries=1)
        assert conn.get_data(_url(faulty_server)) == "OK"
        assert faulty_server.calls == 2

    def test_chunk_size_passthrough(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = [("status", 200, b"0123456789")]
        conn = Connection()
        stream = conn.get_stream(_url(faulty_server), chunk_size=4)
        assert stream is not None
        assert [len(c) for c in stream] == [4, 4, 2]

    def test_connection_reset(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = ["reset"]
        conn = Connection()
        assert conn.get_data(_url(faulty_server)) is None
        assert conn.head(_url(faulty_server)) is None
        assert not conn.delete_data(_url(faulty_server))

    def test_truncated_body_get_raw_data(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = [("partial", b"short", 100)]
        conn = Connection()
        assert conn.get_raw_data(_url(faulty_server)) is None

    def test_truncated_body_stream_propagates(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = [("partial", b"short", 100)]
        conn = Connection()
        stream = conn.get_stream(_url(faulty_server))
        assert stream is not None
        # the declared body never completes: iterating raises
        # ChunkedEncodingError (IncompleteRead), propagated to the caller
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            b"".join(stream)


class TestAsyncFaultInjection:
    async def test_transport_error_variety(self) -> None:
        exc_types: list[Any] = [
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ]
        for exc_type in exc_types:
            def handler(request: httpx.Request, exc_type: Any = exc_type) -> httpx.Response:
                raise exc_type("boom", request=request)

            conn = AsyncConnection(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
            assert await conn.get_data("http://utek.pl") is None
            assert await conn.head("http://utek.pl") is None
            assert not await conn.delete_data("http://utek.pl")
            with open(__file__, "rb") as f:
                assert await conn.post_file("http://utek.pl", "t.py", f) is None
            await conn.close()

    async def test_retry_recovers_from_5xx(self, faulty_server: _FaultyServer, monkeypatch: pytest.MonkeyPatch) -> None:
        async def no_sleep(_: float) -> None:
            pass

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", no_sleep)
        faulty_server.script = [("status", 503, b"err"), ("status", 200, b"OK")]
        conn = AsyncConnection(retries=2)
        assert await conn.get_data(_url(faulty_server)) == "OK"
        assert faulty_server.calls == 2
        await conn.close()

    async def test_retry_exhausted_async(self, faulty_server: _FaultyServer, monkeypatch: pytest.MonkeyPatch) -> None:
        async def no_sleep(_: float) -> None:
            pass

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", no_sleep)
        faulty_server.script = [("status", 503, b"err")]
        conn = AsyncConnection(retries=1)
        assert await conn.get_data(_url(faulty_server)) is None
        assert faulty_server.calls == 2
        await conn.close()

    async def test_connection_reset_async(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = ["reset"]
        conn = AsyncConnection()
        assert await conn.get_data(_url(faulty_server)) is None
        assert await conn.head(_url(faulty_server)) is None
        assert not await conn.delete_data(_url(faulty_server))
        await conn.close()

    async def test_truncated_body_stream_async(self, faulty_server: _FaultyServer) -> None:
        faulty_server.script = [("partial", b"short", 100)]
        conn = AsyncConnection()
        stream = conn.get_stream(_url(faulty_server))
        chunks = [c async for c in stream]
        # mid-stream HTTP errors are swallowed: the iterator ends
        # silently (httpx discards the incomplete buffered chunk)
        assert chunks == []
        await conn.close()

    async def test_stream_retry_exhaustion_count(self, faulty_server: _FaultyServer, monkeypatch: pytest.MonkeyPatch) -> None:
        async def no_sleep(_: float) -> None:
            pass

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", no_sleep)
        faulty_server.script = [("status", 503, b"e"), ("status", 503, b"e"), ("status", 503, b"e")]
        conn = AsyncConnection(retries=1)
        chunks = [c async for c in conn.get_stream(_url(faulty_server))]
        assert chunks == []
        assert faulty_server.calls == 2
        await conn.close()

    async def test_truncated_body_stream_retries(self, faulty_server: _FaultyServer, monkeypatch: pytest.MonkeyPatch) -> None:
        async def no_sleep(_: float) -> None:
            pass

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", no_sleep)
        faulty_server.script = [("partial", b"short", 100), ("status", 200, b"full-body")]
        conn = AsyncConnection(retries=1)
        stream = conn.get_stream(_url(faulty_server))
        # the retry re-requests from scratch: the truncated first
        # attempt delivers nothing, the retried attempt succeeds
        chunks = [c async for c in stream]
        assert b"".join(chunks) == b"full-body"
        assert faulty_server.calls == 2
        await conn.close()
