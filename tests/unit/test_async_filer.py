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

    async def test_upload_file_failures(self) -> None:
        filer = make_filer(lambda request: httpx.Response(500))
        assert await filer.upload_file("/docs/x", __file__) is None
        filer = make_filer(lambda request: httpx.Response(200, content=b"not json"))
        with pytest.raises(RuntimeError):
            await filer.upload_file("/docs/x", __file__)
        filer = make_filer(lambda request: json_resp({"error": "bad"}))
        with pytest.raises(RuntimeError):
            await filer.upload_file("/docs/x", __file__)
        with pytest.raises(ValueError):
            await make_filer().upload_file("/docs/x")

    async def test_download_file(self) -> None:
        filer = make_filer()
        assert await filer.download_file("/docs/report.txt") == b"file-content"
        assert await filer.download_file("/docs/missing.txt") is None

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

        tags = await filer.get_tags("/docs/report.txt")
        assert tags == {"Color": "red"}

        assert await filer.delete_tags("/docs/report.txt", ["color"])
        assert "tagging=Color" in seen_urls[-1]
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
