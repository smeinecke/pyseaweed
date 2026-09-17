import json
from collections.abc import Callable, Sequence
from io import BytesIO
from typing import Any

import httpx
import pytest

from pyseaweed.async_client import AsyncConnection, AsyncSeaweedFS
from pyseaweed.exceptions import BadFidFormat

VOLUME_RESP = {"url": "vol.local:8080", "publicUrl": "pub.local:8080"}
ASSIGN_RESP = {"fid": "3,01637037d6", "url": "vol.local:8080", "publicUrl": "pub.local:8080", "count": 1}
FID = "3,01637037d6"

Handler = Callable[[httpx.Request], httpx.Response]


def json_resp(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(data).encode())


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="OK")


def created(request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, text="OK")


def not_found(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, text="NOK")


def volume_file(request: httpx.Request) -> httpx.Response:
    if request.url.path != "/" + FID:
        return httpx.Response(404, text="NOK")
    if request.method == "HEAD":
        return httpx.Response(200, headers={"content-length": "123"})
    if request.method == "GET":
        return httpx.Response(200, content=b"file-content")
    if request.method == "DELETE":
        return httpx.Response(202, content=b"{}")
    if request.method == "POST":
        return json_resp({"size": 123}, status=201)
    return httpx.Response(404, text="NOK")


def dispatch(routes: Sequence[tuple[str, Handler | httpx.Response]]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, resp in routes:
            if request.url.path.startswith(prefix):
                return resp(request) if callable(resp) else resp
        return httpx.Response(404, text="NOK")

    return handler


FULL = dispatch([
    ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
    ("/dir/assign", json_resp(ASSIGN_RESP)),
    ("/dir/status", json_resp({"Version": "30GB 4.00"})),
    ("/vol/vacuum", httpx.Response(200, content=b"{}")),
    ("/" + FID.split(",")[0] + ",", volume_file),
])


def make_conn(handler: Handler = ok, retries: int = 0) -> AsyncConnection:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AsyncConnection(retries=retries, client=client)


def make_fs(handler: Handler = FULL, **kwargs: Any) -> AsyncSeaweedFS:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AsyncSeaweedFS(client=client, **kwargs)


class TestAsyncConnection:
    async def test_close_and_context_manager(self) -> None:
        conn = make_conn()
        async with conn:
            pass
        assert conn._client.is_closed

    async def test_default_client_created(self) -> None:
        conn = AsyncConnection(timeout=5.0)
        assert isinstance(conn._client, httpx.AsyncClient)
        await conn.close()

    async def test_get_data(self) -> None:
        conn = make_conn()
        assert await conn.get_data("http://utek.pl") == "OK"
        conn = make_conn(not_found)
        assert await conn.get_data("http://utek.pl") is None

    async def test_get_raw_data(self) -> None:
        conn = make_conn()
        assert await conn.get_raw_data("http://utek.pl") == b"OK"
        conn = make_conn(not_found)
        assert await conn.get_raw_data("http://utek.pl") is None

    async def test_head(self) -> None:
        conn = make_conn()
        res = await conn.head("http://utek.pl")
        assert res is not None
        assert res.status_code == 200
        conn = make_conn(not_found)
        assert await conn.head("http://utek.pl") is None

    async def test_delete_data(self) -> None:
        assert await make_conn().delete_data("http://utek.pl")
        assert await make_conn(created).delete_data("http://utek.pl")
        assert await make_conn(lambda r: httpx.Response(204)).delete_data("http://utek.pl")
        assert not await make_conn(not_found).delete_data("http://utek.pl")

    async def test_post_file(self) -> None:
        with open(__file__, "rb") as f:
            assert await make_conn().post_file("http://utek.pl", "tests.py", f) == "OK"
        with open(__file__, "rb") as f:
            assert await make_conn(created).post_file("http://utek.pl", "tests.py", f) == "OK"
        with open(__file__, "rb") as f:
            assert await make_conn(not_found).post_file("http://utek.pl", "tests.py", f) is None

    async def test_post_and_put(self) -> None:
        assert await make_conn(created).post("http://utek.pl")
        assert await make_conn().put("http://utek.pl")
        assert not await make_conn(not_found).post("http://utek.pl")
        assert not await make_conn(not_found).put("http://utek.pl")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        conn = make_conn(handler)
        assert not await conn.post("http://utek.pl")
        assert not await conn.put("http://utek.pl")

    async def test_post_file_content_type(self) -> None:
        with open(__file__, "rb") as f:
            assert await make_conn().post_file("http://utek.pl", "tests.py", f, content_type="text/x-python") == "OK"

    async def test_get_stream(self) -> None:
        chunks = [c async for c in make_conn().get_stream("http://utek.pl")]
        assert b"".join(chunks) == b"OK"
        chunks = [c async for c in make_conn(not_found).get_stream("http://utek.pl")]
        assert chunks == []

    async def test_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        conn = make_conn(handler)
        assert await conn.get_data("http://utek.pl") is None
        assert await conn.head("http://utek.pl") is None
        assert await conn.get_raw_data("http://utek.pl") is None
        assert not await conn.delete_data("http://utek.pl")
        with open(__file__, "rb") as f:
            assert await conn.post_file("http://utek.pl", "tests.py", f) is None
        chunks = [c async for c in conn.get_stream("http://utek.pl")]
        assert chunks == []

    async def test_retries_on_5xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503)
            return httpx.Response(200, text="OK")

        async def no_sleep(_: float) -> None:
            pass

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", no_sleep)
        conn = make_conn(handler, retries=3)
        assert await conn.get_data("http://utek.pl") == "OK"
        assert calls["n"] == 3

    async def test_retries_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503)

        async def no_sleep(_: float) -> None:
            pass

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", no_sleep)
        conn = make_conn(handler, retries=2)
        assert await conn.get_data("http://utek.pl") is None
        assert calls["n"] == 3

    async def test_post_not_retried(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503)

        conn = make_conn(handler, retries=3)
        with open(__file__, "rb") as f:
            assert await conn.post_file("http://utek.pl", "tests.py", f) is None
        assert calls["n"] == 1

    async def test_stream_retries_on_5xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 2:
                return httpx.Response(502)
            return httpx.Response(200, content=b"data")

        async def no_sleep(_: float) -> None:
            pass

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", no_sleep)
        conn = make_conn(handler, retries=2)
        chunks = [c async for c in conn.get_stream("http://utek.pl")]
        assert b"".join(chunks) == b"data"
        assert calls["n"] == 2

    async def test_timeout_override(self) -> None:
        seen: list[object] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.extensions.get("timeout"))
            return httpx.Response(200, text="OK")

        conn = make_conn(handler)
        await conn.get_data("http://utek.pl", timeout=3.5)
        assert seen == [{"connect": 3.5, "read": 3.5, "write": 3.5, "pool": 3.5}]


class TestAsyncSeaweedFS:
    async def test_repr_and_context_manager(self) -> None:
        seaweed = make_fs()
        assert repr(seaweed) == "<AsyncSeaweedFS localhost:9333>"
        async with seaweed as fs:
            assert fs is seaweed
        assert seaweed.conn._client.is_closed

    async def test_get_file_url(self) -> None:
        seaweed = make_fs()
        assert await seaweed.get_file_url(FID) == f"http://pub.local:8080/{FID}"
        assert await seaweed.get_file_url(FID, public=False) == f"http://vol.local:8080/{FID}"
        assert await seaweed.get_file_url(FID, params={"width": "100"}) == f"http://pub.local:8080/{FID}?width=100"

    async def test_get_file_url_bad_fid(self) -> None:
        seaweed = make_fs()
        for bad_fid in ("badfid", "1,2,3", "3,", ",abc", "", "  ", "x,abc", "3,xyz"):
            with pytest.raises(BadFidFormat, match="fid must be in format"):
                await seaweed.get_file_url(bad_fid)

    async def test_get_file_url_no_volume(self) -> None:
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": []}))]))
        assert await seaweed.get_file_url(FID) is None

    async def test_get_file_location_collection(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return json_resp({"locations": [VOLUME_RESP]})

        seaweed = make_fs(handler)
        loc = await seaweed.get_file_location("3", collection="mycollection")
        assert loc is not None
        assert "collection=mycollection" in seen[0]

    async def test_get_file_location_variants(self) -> None:
        seaweed = make_fs(dispatch([("/dir/lookup", httpx.Response(200, content=b"not json"))]))
        assert await seaweed.get_file_location("3") is None
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": "nope"}))]))
        assert await seaweed.get_file_location("3") is None
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": [{"url": ""}]}))]))
        assert await seaweed.get_file_location("3") is None
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": [{"url": "vol.local:8080"}]}))]))
        loc = await seaweed.get_file_location("3")
        assert loc is not None
        assert loc.url == "vol.local:8080"
        assert loc.public_url == "vol.local:8080"

    async def test_get_file(self) -> None:
        seaweed = make_fs()
        assert await seaweed.get_file(FID) == b"file-content"
        assert await seaweed.get_file("4,01637037d6") is None

    async def test_get_file_no_volume(self) -> None:
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": []}))]))
        assert await seaweed.get_file(FID) is None

    async def test_get_file_stream(self) -> None:
        seaweed = make_fs()
        stream = await seaweed.get_file_stream(FID, chunk_size=4)
        assert stream is not None
        chunks = [c async for c in stream]
        assert b"".join(chunks) == b"file-content"

    async def test_get_file_stream_no_volume(self) -> None:
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": []}))]))
        assert await seaweed.get_file_stream(FID) is None

    async def test_get_file_forwards_params_collection_and_range(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/lookup":
                captured["lookup"] = str(request.url)
                return json_resp({"locations": [VOLUME_RESP]})
            captured["file_url"] = str(request.url)
            captured["range"] = request.headers.get("range")
            return httpx.Response(206, content=b"data")

        seaweed = make_fs(handler)
        assert await seaweed.get_file(FID, params={"width": "10"}, collection="mycol", byte_range=(0, 5)) == b"data"
        assert "collection=mycol" in captured["lookup"]
        assert "width=10" in captured["file_url"]
        assert captured["range"] == "bytes=0-5"

        captured.clear()
        assert await seaweed.get_file(FID) == b"data"
        assert captured["range"] is None

    async def test_get_file_stream_forwards_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/lookup":
                captured["lookup"] = str(request.url)
                return json_resp({"locations": [VOLUME_RESP]})
            captured["file_url"] = str(request.url)
            captured["range"] = request.headers.get("range")
            return httpx.Response(206, content=b"abcde")

        seaweed = make_fs(handler)
        stream = await seaweed.get_file_stream(FID, params={"x": "y"}, collection="c", byte_range=(1, 3), chunk_size=2)
        assert stream is not None
        assert [c async for c in stream] == [b"ab", b"cd", b"e"]
        assert "collection=c" in captured["lookup"]
        assert "x=y" in captured["file_url"]
        assert captured["range"] == "bytes=1-3"

    async def test_get_file_stream_default_chunk_size(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/lookup":
                return json_resp({"locations": [VOLUME_RESP]})
            return httpx.Response(200, content=b"z" * 20000)

        seaweed = make_fs(handler)
        stream = await seaweed.get_file_stream(FID)
        assert stream is not None
        sizes = [len(c) async for c in stream]
        assert sizes == [8192, 8192, 3616]

    async def test_get_file_location_request_fails(self) -> None:
        seaweed = make_fs(dispatch([("/dir/lookup", httpx.Response(500))]))
        assert await seaweed.get_file_location("3") is None

    async def test_get_file_location_non_dict_response(self) -> None:
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp([1, 2]))]))
        assert await seaweed.get_file_location("3") is None

    async def test_get_json_non_dict_responses(self) -> None:
        seaweed = make_fs(dispatch([("/dir/status", json_resp([1]))]))
        assert await seaweed.version() is None
        seaweed = make_fs(dispatch([("/cluster/status", json_resp("str"))]))
        assert await seaweed.cluster_status() is None

    async def test_vacuum_sends_threshold(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=b"{}")

        seaweed = make_fs(dispatch([("/vol/vacuum", handler)]))
        assert await seaweed.vacuum()
        assert "garbageThreshold=0.3" in seen[0]
        assert await seaweed.vacuum(threshold=0.5)
        assert "garbageThreshold=0.5" in seen[1]

    async def test_get_file_url_sends_volume_id(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = str(request.url)
            return json_resp({"locations": [VOLUME_RESP]})

        seaweed = make_fs(dispatch([("/dir/lookup", handler)]))
        await seaweed.get_file_url(FID)
        assert "volumeId=3" in captured["query"]

    async def test_collection_forwarded_to_lookup(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/lookup":
                captured.append(str(request.url))
                return json_resp({"locations": [VOLUME_RESP]})
            if request.method == "HEAD":
                return httpx.Response(200, headers={"content-length": "12"})
            if request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(404)

        seaweed = make_fs(handler)
        assert await seaweed.file_exists(FID, collection="col")
        assert await seaweed.get_file_size(FID, collection="col") == 12
        assert await seaweed.delete_file(FID, collection="col")
        assert all("collection=col" in q for q in captured)

    async def test_volume_server_status_wire(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/lookup":
                captured["lookup"] = str(request.url)
                return json_resp({"locations": [VOLUME_RESP]})
            captured["status_url"] = str(request.url)
            return json_resp({"Version": "4.47"})

        seaweed = make_fs(handler)
        assert await seaweed.volume_server_status(FID, collection="c") == {"Version": "4.47"}
        assert "collection=c" in captured["lookup"]
        assert captured["status_url"] == "http://vol.local:8080/status"

    async def test_get_file_size(self) -> None:
        seaweed = make_fs()
        assert await seaweed.get_file_size(FID) == 123
        assert await seaweed.get_file_size("4,01637037d6") is None

    async def test_get_file_size_bad_content_length(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/" + FID and request.method == "HEAD":
                return httpx.Response(200, headers={"content-length": "NaN"})
            if request.url.path.startswith("/dir/lookup"):
                return json_resp({"locations": [VOLUME_RESP]})
            return httpx.Response(404)

        seaweed = make_fs(handler)
        assert await seaweed.get_file_size(FID) is None

    async def test_file_exists(self) -> None:
        seaweed = make_fs()
        assert await seaweed.file_exists(FID)
        assert not await seaweed.file_exists("4,01637037d6")
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": []}))]))
        assert not await seaweed.file_exists(FID)

    async def test_get_file_size_no_volume(self) -> None:
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": []}))]))
        assert await seaweed.get_file_size(FID) is None

    async def test_delete_file(self) -> None:
        seaweed = make_fs()
        assert await seaweed.delete_file(FID)
        assert not await seaweed.delete_file("4,01637037d6")
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": []}))]))
        assert not await seaweed.delete_file(FID)

    async def test_upload_file(self) -> None:
        seaweed = make_fs()
        fid = await seaweed.upload_file(__file__)
        assert fid == FID

    async def test_upload_file_stream(self) -> None:
        seaweed = make_fs()
        fid = await seaweed.upload_file(stream=BytesIO(b"data"), name="data.bin")
        assert fid == FID

    async def test_upload_file_no_args(self) -> None:
        seaweed = make_fs()
        with pytest.raises(ValueError):
            await seaweed.upload_file()
        with pytest.raises(ValueError):
            await seaweed.upload_file(stream=BytesIO(b"x"))

    async def test_upload_file_assign_kwargs(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path == "/dir/assign":
                return json_resp(ASSIGN_RESP)
            if request.method == "POST":
                return json_resp({"size": 1}, status=201)
            return httpx.Response(404)

        seaweed = make_fs(handler)
        fid = await seaweed.upload_file(__file__, collection="mycollection", ttl="3d")
        assert fid == FID
        assert "collection=mycollection" in seen[0]
        assert "ttl=3d" in seen[0]
        assert seen[1] == f"http://pub.local:8080/{FID}"

    async def test_upload_file_internal_url(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path == "/dir/assign":
                return json_resp(ASSIGN_RESP)
            if request.method == "POST":
                return json_resp({"size": 1}, status=201)
            return httpx.Response(404)

        seaweed = make_fs(handler, use_public_url=False)
        fid = await seaweed.upload_file(__file__)
        assert fid == FID
        assert seen[1] == f"http://vol.local:8080/{FID}"

    async def test_upload_file_failures(self) -> None:
        seaweed = make_fs(dispatch([("/dir/assign", json_resp({"error": "no free volumes"}))]))
        assert await seaweed.upload_file(__file__) is None
        seaweed = make_fs(dispatch([("/dir/assign", httpx.Response(200, content=b"not json"))]))
        assert await seaweed.upload_file(__file__) is None
        seaweed = make_fs(dispatch([("/dir/assign", json_resp({"count": 1}))]))
        assert await seaweed.upload_file(__file__) is None
        seaweed = make_fs(dispatch([("/dir/assign", json_resp({"fid": FID, "count": 1}))]))
        assert await seaweed.upload_file(__file__) is None
        seaweed = make_fs(dispatch([("/dir/assign", httpx.Response(500))]))
        assert await seaweed.upload_file(__file__) is None
        seaweed = make_fs(dispatch([
            ("/dir/assign", json_resp({"fid": 123, "url": "vol.local:8080"})),
            ("/123", json_resp({"size": 5}, status=201)),
        ]))
        assert await seaweed.upload_file(__file__) is None

    async def test_upload_file_assign_error_with_fid(self) -> None:
        resp = {"error": "quota", "fid": FID, "url": "vol.local:8080"}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/assign":
                return json_resp(resp)
            return json_resp({"size": 1}, status=201)

        seaweed = make_fs(handler)
        assert await seaweed.upload_file(__file__) is None

    async def test_upload_file_assign_url_exact(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path == "/dir/assign":
                return json_resp(ASSIGN_RESP)
            return json_resp({"size": 1}, status=201)

        seaweed = make_fs(handler)
        assert await seaweed.upload_file(__file__) == FID
        assert seen[0] == "http://localhost:9333/dir/assign"

    async def test_upload_file_volume_post_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/assign":
                return json_resp(ASSIGN_RESP)
            captured["body"] = request.read()
            captured["headers"] = request.headers
            return json_resp({"size": 1}, status=201)

        seaweed = make_fs(handler)
        fid = await seaweed.upload_file(
            __file__, name="up.bin", additional_headers={"X-Up": "yes"}, content_type="text/x-up"
        )
        assert fid == FID
        body = captured["body"]
        assert b'name="file"; filename="up.bin"' in body
        assert b"Content-Type: text/x-up" in body
        assert captured["headers"]["x-up"] == "yes"

    async def test_upload_file_does_not_close_caller_stream(self) -> None:
        stream = BytesIO(b"data")
        seaweed = make_fs()
        assert await seaweed.upload_file(stream=stream, name="x.bin") == FID
        assert not stream.closed

    async def test_upload_file_post_fails(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/assign":
                return json_resp(ASSIGN_RESP)
            return httpx.Response(503)

        seaweed = make_fs(handler)
        assert await seaweed.upload_file(__file__) is None

    async def test_upload_file_bad_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/dir/assign":
                return json_resp(ASSIGN_RESP)
            if request.method == "POST":
                return httpx.Response(200, content=b"not json")
            return httpx.Response(404)

        seaweed = make_fs(handler)
        with pytest.raises(RuntimeError, match="Upload failed"):
            await seaweed.upload_file(__file__)

    async def test_submit_file(self) -> None:
        seaweed = make_fs(dispatch([("/submit", json_resp({"fid": FID, "size": 5}))]))
        fid = await seaweed.submit_file(__file__)
        assert fid == FID
        seaweed = make_fs(dispatch([("/submit", httpx.Response(200, content=b"{}"))]))
        assert await seaweed.submit_file(__file__) is None
        seaweed = make_fs(dispatch([("/submit", httpx.Response(200, content=b"not json"))]))
        assert await seaweed.submit_file(__file__) is None
        seaweed = make_fs(dispatch([("/submit", json_resp([1, 2]))]))
        assert await seaweed.submit_file(__file__) is None
        seaweed = make_fs(not_found)
        assert await seaweed.submit_file(__file__) is None

    async def test_submit_file_no_args(self) -> None:
        seaweed = make_fs()
        with pytest.raises(ValueError):
            await seaweed.submit_file()

    async def test_submit_file_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.read()
            captured["headers"] = request.headers
            return json_resp({"fid": FID, "size": 5}, status=201)

        seaweed = make_fs(handler)
        fid = await seaweed.submit_file(
            stream=BytesIO(b"data"), name="s.bin", additional_headers={"X-Sub": "1"}, content_type="text/x-s"
        )
        assert fid == FID
        assert captured["url"] == "http://localhost:9333/submit"
        body = captured["body"]
        assert b'name="file"; filename="s.bin"' in body
        assert b"Content-Type: text/x-s" in body
        assert captured["headers"]["x-sub"] == "1"

    async def test_connection_defaults(self) -> None:
        conn = AsyncConnection()
        assert conn.retries == 0
        assert conn.timeout is None
        await conn.close()
        conn = AsyncConnection(timeout=3.3)
        assert conn._client.timeout.read == 3.3
        await conn.close()

    async def test_post_put_methods_on_wire(self) -> None:
        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods.append(request.method)
            return httpx.Response(201)

        conn = AsyncConnection(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        await conn.post("http://x")
        await conn.put("http://x")
        assert methods == ["POST", "PUT"]
        await conn.close()

    async def test_stream_backoff_delays(self, monkeypatch: pytest.MonkeyPatch) -> None:
        delays: list[float] = []

        async def record_sleep(d: float) -> None:
            delays.append(d)

        monkeypatch.setattr("pyseaweed.async_client.asyncio.sleep", record_sleep)
        transport = httpx.MockTransport(lambda req: httpx.Response(503, content=b"err"))
        conn = AsyncConnection(retries=2, client=httpx.AsyncClient(transport=transport))
        chunks = [c async for c in conn.get_stream("http://x")]
        assert chunks == []
        assert delays == [0.3, 0.6]
        await conn.close()

    async def test_admin_queries_on_wire(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path == "/vol/grow":
                return json_resp({"count": 1})
            return httpx.Response(200, content=b"{}")

        seaweed = make_fs(handler)
        assert await seaweed.grow_volumes(3, collection="x")
        assert "count=3" in seen[0]
        assert "collection=x" in seen[0]
        assert await seaweed.delete_collection("foo")
        assert "collection=foo" in seen[1]

    async def test_vacuum(self) -> None:
        seaweed = make_fs()
        assert await seaweed.vacuum()
        seaweed = make_fs(not_found)
        assert not await seaweed.vacuum()

    async def test_admin_endpoints(self) -> None:
        routes = [
            ("/vol/grow", json_resp({"count": 1})),
            ("/col/delete", httpx.Response(200, content=b"{}")),
            ("/cluster/status", json_resp({"IsLeader": True})),
            ("/vol/status", json_resp({"Volumes": {}})),
            ("/cluster/healthz", httpx.Response(200)),
        ]
        seaweed = make_fs(dispatch(routes))
        assert await seaweed.grow_volumes(3)
        assert await seaweed.delete_collection("foo")
        assert await seaweed.cluster_status() == {"IsLeader": True}
        assert await seaweed.volume_status() == {"Volumes": {}}
        assert await seaweed.is_healthy()

    async def test_admin_error_responses(self) -> None:
        routes = [
            ("/vol/grow", json_resp({"error": "0 volumes left"})),
            ("/col/delete", json_resp({"error": "collection not found"})),
            ("/cluster/status", httpx.Response(200, content=b"not json")),
            ("/vol/status", httpx.Response(503)),
            ("/cluster/healthz", httpx.Response(500)),
        ]
        seaweed = make_fs(dispatch(routes))
        assert not await seaweed.grow_volumes(1)
        assert not await seaweed.delete_collection("foo")
        assert await seaweed.cluster_status() is None
        assert await seaweed.volume_status() is None
        assert not await seaweed.is_healthy()

    async def test_volume_server_status(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/status":
                return json_resp({"Version": "4.00"})
            if request.url.path == "/dir/lookup":
                return json_resp({"locations": [VOLUME_RESP]})
            return httpx.Response(404)

        seaweed = make_fs(handler)
        assert await seaweed.volume_server_status(FID) == {"Version": "4.00"}
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": []}))]))
        assert await seaweed.volume_server_status(FID) is None

    async def test_version(self) -> None:
        seaweed = make_fs()
        assert await seaweed.version() == "30GB 4.00"
        seaweed = make_fs(dispatch([("/dir/status", httpx.Response(200, content=b"not json"))]))
        assert await seaweed.version() is None
        seaweed = make_fs(dispatch([("/dir/status", json_resp([1, 2]))]))
        assert await seaweed.version() is None
        seaweed = make_fs(dispatch([("/dir/status", json_resp({"Version": 5}))]))
        assert await seaweed.version() is None
        seaweed = make_fs(not_found)
        assert await seaweed.version() is None


def test_lazy_init_export() -> None:
    from pyseaweed import AsyncSeaweedFS as LazyAsync

    assert LazyAsync is AsyncSeaweedFS


def test_lazy_init_export_missing_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    import pyseaweed

    monkeypatch.delitem(sys.modules, "pyseaweed.async_client", raising=False)
    monkeypatch.setitem(sys.modules, "httpx", None)
    with pytest.raises(ImportError, match="pyseaweed\\[async\\]"):
        pyseaweed.AsyncSeaweedFS  # noqa: B018


def test_lazy_init_export_unknown_attr() -> None:
    import pyseaweed

    with pytest.raises(AttributeError):
        pyseaweed.NonExistent  # noqa: B018


class TestAsyncNegativePaths:
    async def test_fid_format_edges(self) -> None:
        seaweed = make_fs(dispatch([("/dir/lookup", json_resp({"locations": [VOLUME_RESP]}))]))
        for fid in ("3,ABCD", "03,ab", "3,01637037d6.png", "3,ab.-_", " 3,ab "):
            assert await seaweed.get_file_url(fid) is not None
        for bad_fid in ("3,ab.txt.png", "3, ab", "3,ab,cd", "3,g", "3,0f-2_4"):
            with pytest.raises(BadFidFormat):
                await seaweed.get_file_url(bad_fid)
        await seaweed.close()

    async def test_upload_assign_malformed(self) -> None:
        for data in (5, [], {"fid": ""}, {"fid": 123}, {"fid": FID}, {"fid": FID, "url": None}, {"fid": FID, "url": ""}, {"error": "no volumes"}):
            seaweed = make_fs(dispatch([("/dir/assign", json_resp(data))]))
            assert await seaweed.upload_file(__file__) is None

    async def test_upload_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            await make_fs().upload_file("/nonexistent-path-xyz.txt")

    async def test_submit_malformed_responses(self) -> None:
        for data in (5, "x", [], {"fid": None}, {"fid": 123}, {}):
            seaweed = make_fs(dispatch([("/submit", json_resp(data))]))
            assert await seaweed.submit_file(__file__) is None
