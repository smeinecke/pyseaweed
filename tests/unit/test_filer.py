import json
from io import BytesIO
from typing import Any, cast

import pytest
import requests
from httmock import HTTMock, all_requests

from pyseaweed.filer import Filer
from pyseaweed.utils import Connection


def json_resp(data: Any, status: int = 200) -> dict[str, Any]:
    return {"status_code": status, "content": json.dumps(data).encode()}


def dispatch(routes: list[tuple[str, Any]]) -> Any:
    @all_requests
    def handler(url: Any, request: Any) -> dict[str, Any]:
        for prefix, resp in routes:
            if url.path.startswith(prefix):
                resp = resp(url, request) if callable(resp) else resp
                return cast(dict[str, Any], resp)
        return {"status_code": 404, "content": b"NOK"}

    return handler


ENTRY = {"FullPath": "/docs/report.txt", "FileSize": 12, "Extended": {"Seaweed-Color": "cmVk"}}
LISTING = {"Path": "/docs", "Entries": [ENTRY], "LastFileName": "report.txt", "ShouldDisplayLoadMore": False}


def file_handler(url: Any, request: Any) -> dict[str, Any]:
    if url.path != "/docs/report.txt":
        return {"status_code": 404, "content": b"NOK"}
    if request.method == "HEAD":
        return {"status_code": 200, "headers": {"content-length": "12"}, "content": b""}
    if request.method == "GET":
        return {"status_code": 200, "content": b"file-content"}
    if request.method == "DELETE":
        return {"status_code": 204, "content": b""}
    return {"status_code": 404, "content": b"NOK"}


FULL = dispatch([
    ("/docs/report.txt", file_handler),
    ("/docs/missing.txt", {"status_code": 404, "content": b"NOK"}),
    ("/docs/", lambda url, request: json_resp(LISTING)),
    ("/meta/", lambda url, request: json_resp(ENTRY)),
    ("/mkdir/", lambda url, request: {"status_code": 201, "content": b""}),
    ("/moved.txt", lambda url, request: {"status_code": 204, "content": b""}),
])


class TestFiler:
    filer: Filer

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.filer = Filer()

    def test_default_conn_uses_plain_requests(self) -> None:
        filer = Filer()
        assert filer.conn._conn is requests
        filer.close()

    def test_repr_and_context_manager(self) -> None:
        assert repr(self.filer) == "<Filer localhost:8888>"
        with self.filer as f:
            assert f is self.filer
        with self.filer:
            pass

    def test_url_normalization(self) -> None:
        assert self.filer._url("docs/a.txt") == "http://localhost:8888/docs/a.txt"
        assert self.filer._url("/docs/a.txt") == "http://localhost:8888/docs/a.txt"
        assert self.filer._url("/d", {"a": "b"}) == "http://localhost:8888/d?a=b"

    def test_upload_file(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return json_resp({"name": "tests.py", "size": 42})

        with HTTMock(all_requests(handler)):
            assert self.filer.upload_file("/docs/report.txt", __file__) == {"name": "tests.py", "size": 42}
            assert seen[0] == "http://localhost:8888/docs/report.txt"

    def test_upload_file_stream_and_params(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return json_resp({"name": "d.bin", "size": 4})

        with HTTMock(all_requests(handler)):
            data = self.filer.upload_file("/docs/d.bin", stream=BytesIO(b"data"), name="d.bin", collection="c", ttl="3d")
            assert data is not None
            assert "collection=c" in seen[0]
            assert "ttl=3d" in seen[0]

    def test_upload_file_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            captured["body"] = request.body
            captured["headers"] = request.headers
            return json_resp({"name": "d.bin", "size": 4})

        with HTTMock(all_requests(handler)):
            self.filer.upload_file(
                "/docs/d.bin", stream=BytesIO(b"data"), name="d.bin", additional_headers={"X-Extra": "1"}, content_type="text/x"
            )
        body = captured["body"]
        if isinstance(body, str):
            body = body.encode()
        assert b'name="file"; filename="d.bin"' in body
        assert b"Content-Type: text/x" in body
        assert b"\r\ndata\r\n" in body
        assert captured["headers"]["X-Extra"] == "1"

    def test_upload_file_default_filename_is_basename(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            captured["body"] = request.body
            return json_resp({"name": "x", "size": 1})

        with HTTMock(all_requests(handler)):
            self.filer.upload_file("/docs/x", __file__)
        body = captured["body"]
        if isinstance(body, str):
            body = body.encode()
        assert f'filename="{__file__.rsplit("/", 1)[-1]}"'.encode() in body

    def test_upload_file_failures(self) -> None:
        with HTTMock(all_requests(lambda url, request: {"status_code": 500, "content": b"err"})):
            assert self.filer.upload_file("/docs/x", __file__) is None
        with HTTMock(all_requests(lambda url, request: {"status_code": 200, "content": b"not json"})):
            with pytest.raises(RuntimeError, match="Upload failed"):
                self.filer.upload_file("/docs/x", __file__)
        with HTTMock(all_requests(lambda url, request: json_resp({"error": "bad"}))):
            with pytest.raises(RuntimeError, match="Upload failed"):
                self.filer.upload_file("/docs/x", __file__)
        with pytest.raises(ValueError):
            self.filer.upload_file("/docs/x")

    def test_download_file(self) -> None:
        with HTTMock(FULL):
            assert self.filer.download_file("/docs/report.txt") == b"file-content"
            assert self.filer.download_file("/docs/missing.txt") is None

    def test_download_file_forwards_params(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return {"status_code": 200, "content": b"data"}

        with HTTMock(all_requests(handler)):
            assert self.filer.download_file("/docs/report.txt", params={"x": "9"}) == b"data"
            assert "x=9" in seen[0]
            assert self.filer.download_file("/docs/report.txt") == b"data"
            assert "?" not in seen[1]

    def test_download_file_byte_range(self) -> None:
        seen: list[Any] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(request.headers.get("Range"))
            return {"status_code": 200, "content": b"part"}

        with HTTMock(all_requests(handler)):
            assert self.filer.download_file("/docs/report.txt", byte_range=(0, 3)) == b"part"
            assert seen[0] == "bytes=0-3"

    def test_get_file_stream(self) -> None:
        with HTTMock(FULL):
            stream = self.filer.get_file_stream("/docs/report.txt", chunk_size=4)
            assert stream is not None
            assert b"".join(stream) == b"file-content"

    def test_exists(self) -> None:
        with HTTMock(FULL):
            assert self.filer.exists("/docs/report.txt")
            assert not self.filer.exists("/docs/missing.txt")

    def test_stat(self) -> None:
        with HTTMock(FULL):
            meta = self.filer.stat("/meta/report.txt")
            assert meta is not None
            assert meta["FullPath"] == "/docs/report.txt"
            assert self.filer.stat("/missing") is None

    def test_stat_bad_json(self) -> None:
        with HTTMock(all_requests(lambda url, request: {"status_code": 200, "content": b"not json"})):
            assert self.filer.stat("/x") is None
        with HTTMock(all_requests(lambda url, request: json_resp([1]))):
            assert self.filer.stat("/x") is None

    def test_stat_requests_metadata_param(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return json_resp(ENTRY)

        with HTTMock(all_requests(handler)):
            self.filer.stat("/docs/report.txt")
            assert seen[0] == "http://localhost:8888/docs/report.txt?metadata=true"

    def test_list_dir_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            captured["url"] = url.geturl()
            captured["accept"] = request.headers.get("Accept")
            return json_resp(LISTING)

        with HTTMock(all_requests(handler)):
            self.filer.list_dir("/docs/")
            assert captured["url"] == "http://localhost:8888/docs/"
            assert captured["accept"] == "application/json"

    def test_get_file_stream_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            captured["url"] = url.geturl()
            captured["range"] = request.headers.get("Range")
            return {"status_code": 206, "content": b"abc"}

        with HTTMock(all_requests(handler)):
            stream = self.filer.get_file_stream("/docs/report.txt", byte_range=(10, 20), chunk_size=2)
            assert stream is not None
            assert list(stream) == [b"ab", b"c"]
            assert captured["url"] == "http://localhost:8888/docs/report.txt"
            assert captured["range"] == "bytes=10-20"

    def test_get_file_stream_forwards_params(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            captured["url"] = url.geturl()
            captured["range"] = request.headers.get("Range")
            return {"status_code": 200, "content": b"abc"}

        with HTTMock(all_requests(handler)):
            stream = self.filer.get_file_stream("/docs/report.txt", params={"x": "1"})
            assert stream is not None
            assert list(stream) == [b"abc"]
            assert "x=1" in captured["url"]
            assert captured["range"] is None

    def test_get_file_stream_default_chunk_size(self) -> None:
        body = b"z" * 20000
        with HTTMock(all_requests(lambda url, request: {"status_code": 200, "content": body})):
            stream = self.filer.get_file_stream("/docs/report.txt")
            assert stream is not None
            sizes = [len(c) for c in stream]
        assert sizes == [8192, 8192, 3616]

    def test_list_dir(self) -> None:
        with HTTMock(FULL):
            listing = self.filer.list_dir("/docs")
            assert listing is not None
            assert listing["Entries"][0]["FullPath"] == "/docs/report.txt"
            assert listing["ShouldDisplayLoadMore"] is False

    def test_list_dir_pagination_params(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return json_resp(LISTING)

        with HTTMock(all_requests(handler)):
            self.filer.list_dir("/docs", limit=50, last_file_name="prev.txt")
            assert "limit=50" in seen[0]
            assert "lastFileName=prev.txt" in seen[0]

    def test_list_dir_failures(self) -> None:
        with HTTMock(all_requests(lambda url, request: {"status_code": 404, "content": b"NOK"})):
            assert self.filer.list_dir("/missing") is None
        with HTTMock(all_requests(lambda url, request: {"status_code": 200, "content": b"not json"})):
            assert self.filer.list_dir("/x") is None

    def test_mkdir(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl() + " " + request.method)
            return {"status_code": 201, "content": b""}

        with HTTMock(all_requests(handler)):
            assert self.filer.mkdir("/new/dir")
            assert seen[0] == "http://localhost:8888/new/dir/?mode=mkdir POST"

    def test_move(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl() + " " + request.method)
            return {"status_code": 204, "content": b""}

        with HTTMock(all_requests(handler)):
            assert self.filer.move("/a.txt", "/b.txt")
            assert seen[0] == "http://localhost:8888/b.txt?mv.from=%2Fa.txt POST"

    def test_delete(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return {"status_code": 204, "content": b""}

        with HTTMock(all_requests(handler)):
            assert self.filer.delete("/docs/report.txt")
            assert "?" not in seen[0]
            assert self.filer.delete("/docs", recursive=True)
            assert "recursive=true" in seen[1]
            assert self.filer.delete("/docs", recursive=True, ignore_recursive_error=True)
            assert "ignoreRecursiveError=true" in seen[2]

    def test_tags(self) -> None:
        seen_headers: list[Any] = []
        seen_urls: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen_headers.append(dict(request.headers))
            seen_urls.append(url.geturl())
            if request.method == "GET":
                return json_resp(ENTRY)
            return {"status_code": 202, "content": b""}

        with HTTMock(all_requests(handler)):
            assert self.filer.set_tags("/docs/report.txt", {"color": "red", "my-tag": "v"})
            assert seen_headers[0]["Seaweed-color"] == "red"
            assert seen_headers[0]["Seaweed-my-tag"] == "v"
            assert seen_urls[0].endswith("?tagging=")

            tags = self.filer.get_tags("/docs/report.txt")
            assert tags == {"Color": "red"}

            assert self.filer.delete_tags("/docs/report.txt", ["color"])
            assert "tagging=Color" in seen_urls[-1]
            assert self.filer.delete_tags("/docs/report.txt", ["color", "size"])
            assert "tagging=Color%2CSize" in seen_urls[-1]
            assert self.filer.delete_tags("/docs/report.txt")
            assert seen_urls[-1].endswith("?tagging=")

    def test_get_tags_missing_and_plain(self) -> None:
        with HTTMock(all_requests(lambda url, request: {"status_code": 404, "content": b"NOK"})):
            assert self.filer.get_tags("/x") is None
        with HTTMock(all_requests(lambda url, request: json_resp({"FullPath": "/x", "Extended": None}))):
            assert self.filer.get_tags("/x") == {}
        with HTTMock(all_requests(lambda url, request: json_resp({"Extended": {"Seaweed-Weird": "not base64!!!", "Other": "aGk="}}))):
            tags = self.filer.get_tags("/x")
            assert tags is not None
            assert tags["Weird"] == "not base64!!!"
            assert "Other" not in tags


class TestConnectionPostPut:
    conn: Connection

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.conn = Connection()

    def test_post(self) -> None:
        with HTTMock(all_requests(lambda url, request: {"status_code": 201, "content": b""})):
            assert self.conn.post("http://utek.pl")
        with HTTMock(all_requests(lambda url, request: {"status_code": 404, "content": b""})):
            assert not self.conn.post("http://utek.pl")
        with HTTMock(all_requests(lambda url, request: {"status_code": 200, "content": b""})):
            with pytest.MonkeyPatch.context() as m:
                m.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
                assert not self.conn.post("http://utek.pl")

    def test_put(self) -> None:
        with HTTMock(all_requests(lambda url, request: {"status_code": 202, "content": b""})):
            assert self.conn.put("http://utek.pl")
        with HTTMock(all_requests(lambda url, request: {"status_code": 404, "content": b""})):
            assert not self.conn.put("http://utek.pl")
        with HTTMock(all_requests(lambda url, request: {"status_code": 200, "content": b""})):
            with pytest.MonkeyPatch.context() as m:
                m.setattr(requests, "put", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
                assert not self.conn.put("http://utek.pl")


class TestFilerNegativePaths:
    """Negative-path and malformed-input coverage for Filer."""

    filer: Filer

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.filer = Filer()

    def test_delete_tags_empty_names_is_noop(self) -> None:
        called: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            called.append(url.geturl())
            return {"status_code": 202, "content": b""}

        with HTTMock(all_requests(handler)):
            assert self.filer.delete_tags("/x", [])
            assert self.filer.delete_tags("/x", ())
            assert self.filer.delete_tags("/x", iter([]))
            assert called == []

    def test_set_tags_coerces_values(self) -> None:
        seen: list[Any] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(dict(request.headers))
            return {"status_code": 202, "content": b""}

        with HTTMock(all_requests(handler)):
            assert self.filer.set_tags("/x", cast(dict[str, str], {"count": 5, "ok": True}))
            assert seen[0]["Seaweed-count"] == "5"
            assert seen[0]["Seaweed-ok"] == "True"
            assert self.filer.set_tags("/x", {})
            assert not any(k.startswith("Seaweed-") for k in seen[1])

    def test_stat_shape_negatives(self) -> None:
        for data in (5, "x", [], None):
            with HTTMock(all_requests(lambda url, request: json_resp(data))):
                assert self.filer.stat("/x") is None

    def test_list_dir_shape_negatives(self) -> None:
        for data in (5, "x", []):
            with HTTMock(all_requests(lambda url, request: json_resp(data))):
                assert self.filer.list_dir("/x") is None
        with HTTMock(all_requests(lambda url, request: json_resp({"Entries": None}))):
            assert self.filer.list_dir("/x") == {"Entries": None}

    def test_upload_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            self.filer.upload_file("/docs/x", "/nonexistent-path-xyz.txt")

    def test_empty_remote_path(self) -> None:
        assert self.filer._url("") == "http://localhost:8888/"
