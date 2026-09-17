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

    def test_upload_file_failures(self) -> None:
        with HTTMock(all_requests(lambda url, request: {"status_code": 500, "content": b"err"})):
            assert self.filer.upload_file("/docs/x", __file__) is None
        with HTTMock(all_requests(lambda url, request: {"status_code": 200, "content": b"not json"})):
            with pytest.raises(RuntimeError):
                self.filer.upload_file("/docs/x", __file__)
        with HTTMock(all_requests(lambda url, request: json_resp({"error": "bad"}))):
            with pytest.raises(RuntimeError):
                self.filer.upload_file("/docs/x", __file__)
        with pytest.raises(ValueError):
            self.filer.upload_file("/docs/x")

    def test_download_file(self) -> None:
        with HTTMock(FULL):
            assert self.filer.download_file("/docs/report.txt") == b"file-content"
            assert self.filer.download_file("/docs/missing.txt") is None

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

            tags = self.filer.get_tags("/docs/report.txt")
            assert tags == {"Color": "red"}

            assert self.filer.delete_tags("/docs/report.txt", ["color"])
            assert "tagging=Color" in seen_urls[-1]
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
