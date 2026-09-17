import json
from collections.abc import Callable, Sequence
from io import BytesIO
from typing import Any

import httpx
import pytest

from pyseaweed.async_filer import AsyncFiler

Handler = Callable[[httpx.Request], httpx.Response]

ENTRY = {"FullPath": "/docs/report.txt", "FileSize": 12, "Extended": {"Seaweed-Color": "cmVk"}}
LISTING = {"Path": "/docs", "Entries": [ENTRY], "LastFileName": "report.txt", "ShouldDisplayLoadMore": False}


def json_resp(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(data).encode())


def dispatch(routes: Sequence[tuple[str, Handler | httpx.Response]]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, resp in routes:
            if request.url.path.startswith(prefix):
                return resp(request) if callable(resp) else resp
        return httpx.Response(404, text="NOK")

    return handler


def file_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path != "/docs/report.txt":
        return httpx.Response(404, text="NOK")
    if request.method == "HEAD":
        return httpx.Response(200, headers={"content-length": "12"})
    if request.method == "GET":
        return httpx.Response(200, content=b"file-content")
    if request.method == "DELETE":
        return httpx.Response(204)
    return httpx.Response(404, text="NOK")


FULL = dispatch([
    ("/docs/report.txt", file_handler),
    ("/docs/missing.txt", httpx.Response(404, text="NOK")),
    ("/docs/", json_resp(LISTING)),
    ("/meta/", json_resp(ENTRY)),
    ("/mkdir/", httpx.Response(201)),
    ("/moved.txt", httpx.Response(204)),
])


def make_filer(handler: Handler = FULL, **kwargs: Any) -> AsyncFiler:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AsyncFiler(client=client, **kwargs)


class TestAsyncFiler:
    async def test_repr_and_context_manager(self) -> None:
        filer = make_filer()
        assert repr(filer) == "<AsyncFiler localhost:8888>"
        async with filer as f:
            assert f is filer
        assert filer.conn._client.is_closed

    async def test_url_normalization(self) -> None:
        filer = make_filer()
        assert filer._url("docs/a.txt") == "http://localhost:8888/docs/a.txt"
        assert filer._url("/docs/a.txt") == "http://localhost:8888/docs/a.txt"
        assert filer._url("/d", {"a": "b"}) == "http://localhost:8888/d?a=b"
        await filer.close()

    async def test_upload_file(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return json_resp({"name": "tests.py", "size": 42})

        filer = make_filer(handler)
        assert await filer.upload_file("/docs/report.txt", __file__) == {"name": "tests.py", "size": 42}
        assert seen[0] == "http://localhost:8888/docs/report.txt"

    async def test_upload_file_stream_and_params(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return json_resp({"name": "d.bin", "size": 4})

        filer = make_filer(handler)
        data = await filer.upload_file("/docs/d.bin", stream=BytesIO(b"data"), name="d.bin", collection="c", ttl="3d")
        assert data is not None
        assert "collection=c" in seen[0]
        assert "ttl=3d" in seen[0]

    async def test_upload_file_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.read()
            captured["headers"] = request.headers
            return json_resp({"name": "d.bin", "size": 4})

        filer = make_filer(handler)
        await filer.upload_file(
            "/docs/d.bin", stream=BytesIO(b"data"), name="d.bin", additional_headers={"X-Extra": "1"}, content_type="text/x"
        )
        body = captured["body"]
        assert b'name="file"; filename="d.bin"' in body
        assert b"Content-Type: text/x" in body
        assert b"\r\ndata\r\n" in body
        assert captured["headers"]["x-extra"] == "1"

    async def test_upload_file_default_filename_is_basename(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.read()
            return json_resp({"name": "x", "size": 1})

        filer = make_filer(handler)
        await filer.upload_file("/docs/x", __file__)
        assert f'filename="{__file__.rsplit("/", 1)[-1]}"'.encode() in captured["body"]

    async def test_upload_file_failures(self) -> None:
        filer = make_filer(lambda request: httpx.Response(500))
        assert await filer.upload_file("/docs/x", __file__) is None
        filer = make_filer(lambda request: httpx.Response(200, content=b"not json"))
        with pytest.raises(RuntimeError, match="Upload failed"):
            await filer.upload_file("/docs/x", __file__)
        filer = make_filer(lambda request: json_resp({"error": "bad"}))
        with pytest.raises(RuntimeError, match="Upload failed"):
            await filer.upload_file("/docs/x", __file__)
        with pytest.raises(ValueError):
            await make_filer().upload_file("/docs/x")

    async def test_download_file(self) -> None:
        filer = make_filer()
        assert await filer.download_file("/docs/report.txt") == b"file-content"
        assert await filer.download_file("/docs/missing.txt") is None

    async def test_download_file_forwards_params(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=b"data")

        filer = make_filer(handler)
        assert await filer.download_file("/docs/report.txt", params={"x": "9"}) == b"data"
        assert "x=9" in seen[0]
        assert await filer.download_file("/docs/report.txt") == b"data"
        assert "?" not in seen[1]

    async def test_default_conn_settings(self) -> None:
        filer = AsyncFiler()
        assert filer.conn.retries == 0
        assert filer.conn.timeout is None
        await filer.close()

    async def test_download_file_byte_range(self) -> None:
        seen: list[Any] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("range"))
            return httpx.Response(200, content=b"part")

        filer = make_filer(handler)
        assert await filer.download_file("/docs/report.txt", byte_range=(0, 3)) == b"part"
        assert seen[0] == "bytes=0-3"

    async def test_get_file_stream(self) -> None:
        filer = make_filer()
        stream = await filer.get_file_stream("/docs/report.txt", chunk_size=4)
        chunks = [c async for c in stream]
        assert b"".join(chunks) == b"file-content"

    async def test_exists(self) -> None:
        filer = make_filer()
        assert await filer.exists("/docs/report.txt")
        assert not await filer.exists("/docs/missing.txt")

    async def test_stat(self) -> None:
        filer = make_filer()
        meta = await filer.stat("/meta/report.txt")
        assert meta is not None
        assert meta["FullPath"] == "/docs/report.txt"
        assert await filer.stat("/missing") is None

    async def test_stat_bad_json(self) -> None:
        filer = make_filer(lambda request: httpx.Response(200, content=b"not json"))
        assert await filer.stat("/x") is None
        filer = make_filer(lambda request: json_resp([1]))
        assert await filer.stat("/x") is None

    async def test_stat_requests_metadata_param(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return json_resp(ENTRY)

        filer = make_filer(handler)
        await filer.stat("/docs/report.txt")
        assert seen[0] == "http://localhost:8888/docs/report.txt?metadata=true"

    async def test_list_dir_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["accept"] = request.headers.get("accept")
            return json_resp(LISTING)

        filer = make_filer(handler)
        await filer.list_dir("/docs/")
        assert captured["url"] == "http://localhost:8888/docs/"
        assert captured["accept"] == "application/json"

    async def test_get_file_stream_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["range"] = request.headers.get("range")
            return httpx.Response(206, content=b"abc")

        filer = make_filer(handler)
        stream = await filer.get_file_stream("/docs/report.txt", byte_range=(10, 20), chunk_size=2)
        chunks = [c async for c in stream]
        assert chunks == [b"ab", b"c"]
        assert captured["url"] == "http://localhost:8888/docs/report.txt"
        assert captured["range"] == "bytes=10-20"

    async def test_get_file_stream_forwards_params(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["range"] = request.headers.get("range")
            return httpx.Response(200, content=b"abc")

        filer = make_filer(handler)
        stream = await filer.get_file_stream("/docs/report.txt", params={"x": "1"})
        assert [c async for c in stream] == [b"abc"]
        assert "x=1" in captured["url"]
        assert captured["range"] is None

    async def test_get_file_stream_default_chunk_size(self) -> None:
        filer = make_filer(lambda request: httpx.Response(200, content=b"z" * 20000))
        stream = await filer.get_file_stream("/docs/report.txt")
        sizes = [len(c) async for c in stream]
        assert sizes == [8192, 8192, 3616]

    async def test_list_dir(self) -> None:
        filer = make_filer()
        listing = await filer.list_dir("/docs")
        assert listing is not None
        assert listing["Entries"][0]["FullPath"] == "/docs/report.txt"
        assert listing["ShouldDisplayLoadMore"] is False

    async def test_list_dir_pagination_params(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return json_resp(LISTING)

        filer = make_filer(handler)
        await filer.list_dir("/docs", limit=50, last_file_name="prev.txt")
        assert "limit=50" in seen[0]
        assert "lastFileName=prev.txt" in seen[0]

    async def test_list_dir_failures(self) -> None:
        filer = make_filer(lambda request: httpx.Response(404))
        assert await filer.list_dir("/missing") is None
        filer = make_filer(lambda request: httpx.Response(200, content=b"not json"))
        assert await filer.list_dir("/x") is None

    async def test_mkdir(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url) + " " + request.method)
            return httpx.Response(201)

        filer = make_filer(handler)
        assert await filer.mkdir("/new/dir")
        assert seen[0] == "http://localhost:8888/new/dir/?mode=mkdir POST"

    async def test_move(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url) + " " + request.method)
            return httpx.Response(204)

        filer = make_filer(handler)
        assert await filer.move("/a.txt", "/b.txt")
        assert seen[0] == "http://localhost:8888/b.txt?mv.from=%2Fa.txt POST"

    async def test_delete(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(204)

        filer = make_filer(handler)
        assert await filer.delete("/docs/report.txt")
        assert "?" not in seen[0]
        assert await filer.delete("/docs", recursive=True)
        assert "recursive=true" in seen[1]
        assert await filer.delete("/docs", recursive=True, ignore_recursive_error=True)
        assert "ignoreRecursiveError=true" in seen[2]

    async def test_tags(self) -> None:
        seen_headers: list[Any] = []
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.append(dict(request.headers))
            seen_urls.append(str(request.url))
            if request.method == "GET":
                return json_resp(ENTRY)
            return httpx.Response(202)

        filer = make_filer(handler)
        assert await filer.set_tags("/docs/report.txt", {"color": "red", "my-tag": "v"})
        assert seen_headers[0]["seaweed-color"] == "red"
        assert seen_headers[0]["seaweed-my-tag"] == "v"
        assert seen_urls[0].endswith("?tagging=")

        tags = await filer.get_tags("/docs/report.txt")
        assert tags == {"Color": "red"}

        assert await filer.delete_tags("/docs/report.txt", ["color"])
        assert "tagging=Color" in seen_urls[-1]
        assert await filer.delete_tags("/docs/report.txt", ["color", "size"])
        assert "tagging=Color%2CSize" in seen_urls[-1]
        assert await filer.delete_tags("/docs/report.txt")
        assert seen_urls[-1].endswith("?tagging=")

    async def test_get_tags_missing_and_plain(self) -> None:
        filer = make_filer(lambda request: httpx.Response(404))
        assert await filer.get_tags("/x") is None
        filer = make_filer(lambda request: json_resp({"FullPath": "/x", "Extended": None}))
        assert await filer.get_tags("/x") == {}
        filer = make_filer(lambda request: json_resp({"Extended": {"Seaweed-Weird": "not base64!!!", "Other": "aGk="}}))
        tags = await filer.get_tags("/x")
        assert tags is not None
        assert tags["Weird"] == "not base64!!!"
        assert "Other" not in tags


def test_lazy_init_export() -> None:
    from pyseaweed import AsyncFiler as LazyAsyncFiler

    assert LazyAsyncFiler is AsyncFiler


class TestAsyncFilerNegativePaths:
    async def test_delete_tags_empty_names_is_noop(self) -> None:
        called: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            called.append(str(request.url))
            return httpx.Response(202)

        filer = make_filer(handler)
        assert await filer.delete_tags("/x", [])
        assert await filer.delete_tags("/x", ())
        assert await filer.delete_tags("/x", iter([]))
        assert called == []

    async def test_set_tags_coerces_values(self) -> None:
        seen: list[Any] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(dict(request.headers))
            return httpx.Response(202)

        filer = make_filer(handler)
        assert await filer.set_tags("/x", {"count": 5, "ok": True})
        assert seen[0]["seaweed-count"] == "5"
        assert seen[0]["seaweed-ok"] == "True"
        assert await filer.set_tags("/x", {})
        assert not any(k.startswith("seaweed-") for k in seen[1])

    async def test_stat_shape_negatives(self) -> None:
        for data in (5, "x", [], None):
            filer = make_filer(lambda request: json_resp(data))
            assert await filer.stat("/x") is None

    async def test_list_dir_shape_negatives(self) -> None:
        for data in (5, "x", []):
            filer = make_filer(lambda request: json_resp(data))
            assert await filer.list_dir("/x") is None
        filer = make_filer(lambda request: json_resp({"Entries": None}))
        assert await filer.list_dir("/x") == {"Entries": None}

    async def test_upload_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            await make_filer().upload_file("/docs/x", "/nonexistent-path-xyz.txt")

    async def test_empty_remote_path(self) -> None:
        filer = make_filer()
        assert filer._url("") == "http://localhost:8888/"
        await filer.close()
