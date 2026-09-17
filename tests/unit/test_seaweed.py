import json
from io import BytesIO
from typing import Any, cast
from unittest import mock

import pytest
import requests
from httmock import HTTMock, all_requests
from requests.adapters import HTTPAdapter

from pyseaweed.exceptions import BadFidFormat
from pyseaweed.seaweed import SeaweedFS
from pyseaweed.utils import Connection


def response_content(url: Any, request: Any) -> dict[str, Any]:
    return {"status_code": 200, "content": b"OK"}


def response_content_201(url: Any, request: Any) -> dict[str, Any]:
    return {"status_code": 201, "content": b"OK"}


def response_content_202(url: Any, request: Any) -> dict[str, Any]:
    return {"status_code": 202, "content": b"OK"}


def response_content_404(url: Any, request: Any) -> dict[str, Any]:
    return {"status_code": 404, "content": b"NOK"}


def assign_response(url: Any, request: Any) -> dict[str, Any]:
    return {
        "status_code": 200,
        "content": b'{"fid": "3,01637037d6", "url": "localhost:8080", "publicUrl": "localhost:8080", "count": 1}',
    }


VOLUME_RESP = {"url": "vol.local:8080", "publicUrl": "pub.local:8080"}
ASSIGN_RESP = {"fid": "3,01637037d6", "url": "vol.local:8080", "publicUrl": "pub.local:8080", "count": 1}
FID = "3,01637037d6"


def json_resp(data: Any, status: int = 200) -> dict[str, Any]:
    return {"status_code": status, "content": json.dumps(data).encode()}


def volume_file(url: Any, request: Any) -> dict[str, Any]:
    if url.path != "/" + FID:
        return {"status_code": 404, "content": b"NOK"}
    if request.method == "HEAD":
        return {"status_code": 200, "headers": {"content-length": "123"}, "content": b""}
    if request.method == "GET":
        return {"status_code": 200, "content": b"file-content"}
    if request.method == "DELETE":
        return {"status_code": 202, "content": b"{}"}
    if request.method == "POST":
        return json_resp({"size": 123}, status=201)
    return {"status_code": 404, "content": b"NOK"}


def dispatch(routes: list[tuple[str, Any]]) -> Any:
    @all_requests
    def handler(url: Any, request: Any) -> dict[str, Any]:
        for prefix, resp in routes:
            if url.path.startswith(prefix):
                resp = resp(url, request) if callable(resp) else resp
                return cast(dict[str, Any], resp)
        return {"status_code": 404, "content": b"NOK"}

    return handler


FULL = dispatch([
    ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
    ("/dir/assign", json_resp(ASSIGN_RESP)),
    ("/dir/status", json_resp({"Version": "30GB 4.00"})),
    ("/vol/vacuum", {"status_code": 200, "content": b"{}"}),
    ("/" + FID.split(",")[0] + ",", volume_file),
])


class TestConnection:
    conn: Connection

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.conn = Connection()

    def test_post_file(self) -> None:
        with HTTMock(response_content):
            with open(__file__, "rb") as f:
                r = self.conn.post_file("http://utek.pl", "tests.py", f)
            assert r == "OK"
        with HTTMock(response_content_201):
            with open(__file__, "rb") as f:
                r = self.conn.post_file("http://utek.pl", "tests.py", f)
            assert r == "OK"
        with HTTMock(response_content_404):
            with open(__file__, "rb") as f:
                r = self.conn.post_file("http://utek.pl", "tests.py", f)
            assert r is None

    def test_post_file_content_type(self) -> None:
        with HTTMock(response_content):
            with open(__file__, "rb") as f:
                r = self.conn.post_file("http://utek.pl", "tests.py", f, content_type="text/x-python")
            assert r == "OK"

    def test_get_data(self) -> None:
        with HTTMock(response_content):
            r = self.conn.get_data("http://utek.pl")
            assert r == "OK"
        with HTTMock(response_content_404):
            r = self.conn.get_data("http://utek.pl")
            assert r is None

    def test_get_raw_data(self) -> None:
        with HTTMock(response_content):
            r = self.conn.get_raw_data("http://utek.pl")
            assert r == b"OK"
        with HTTMock(response_content_404):
            r = self.conn.get_raw_data("http://utek.pl")
            assert r is None

    def test_head(self) -> None:
        with HTTMock(response_content):
            r = self.conn.head("http://utek.pl")
            assert r is not None
            assert r.status_code == 200
        with HTTMock(response_content_404):
            r = self.conn.head("http://utek.pl")
            assert r is None

    def test_delete_data(self) -> None:
        with HTTMock(response_content):
            r = self.conn.delete_data("http://localhost")
            assert r
        with HTTMock(response_content_202):
            r = self.conn.delete_data("http://localhost")
            assert r
        with HTTMock(lambda url, request: {"status_code": 204, "content": b""}):
            r = self.conn.delete_data("http://localhost")
            assert r
        with HTTMock(response_content_404):
            r = self.conn.delete_data("http://localhost")
            assert not r

    def test_close(self) -> None:
        conn = Connection(use_session=True)
        with mock.patch.object(conn._conn, "close") as close_mock:
            conn.close()
            close_mock.assert_called_once_with()
        self.conn.close()

    def test_context_manager(self) -> None:
        with Connection(use_session=True) as conn:
            assert isinstance(conn, Connection)

    def test_prepare_headers(self) -> None:
        headers = self.conn._prepare_headers()
        assert isinstance(headers, dict)
        for k, v in headers.items():
            assert isinstance(k, str)
            assert isinstance(v, str)

    def test_additional_headers(self) -> None:
        additional_headers = {"X-Test": "123"}
        headers = self.conn._prepare_headers(additional_headers)
        assert isinstance(headers, dict)
        assert headers.get("X-Test") is not None
        with HTTMock(response_content):
            with open(__file__, "rb") as f:
                r = self.conn.post_file(
                    "http://utek.pl",
                    "tests.py",
                    f,
                    additional_headers=additional_headers,
                )
            assert r == "OK"
            r = self.conn.get_data("http://utek.pl", additional_headers=additional_headers)
            assert r == "OK"
            r = self.conn.get_raw_data("http://utek.pl", additional_headers=additional_headers)
            assert r == b"OK"
            r = self.conn.delete_data("http://localhost", additional_headers=additional_headers)
            assert r

    def test_use_session(self) -> None:
        conn = Connection(use_session=True)
        with HTTMock(response_content):
            assert conn.get_data("http://utek.pl") == "OK"

    def test_get_stream(self) -> None:
        with HTTMock(response_content):
            stream = self.conn.get_stream("http://utek.pl")
            assert stream is not None
            assert b"".join(stream) == b"OK"
        with HTTMock(response_content_404):
            assert self.conn.get_stream("http://utek.pl") is None

    def test_transport_errors(self) -> None:
        with mock.patch.object(requests, "get", side_effect=requests.ConnectionError):
            assert self.conn.get_data("http://utek.pl") is None
            assert self.conn.get_raw_data("http://utek.pl") is None
            assert self.conn.get_stream("http://utek.pl") is None
        with mock.patch.object(requests, "head", side_effect=requests.Timeout):
            assert self.conn.head("http://utek.pl") is None
        with mock.patch.object(requests, "post", side_effect=requests.ConnectionError):
            with open(__file__, "rb") as f:
                assert self.conn.post_file("http://utek.pl", "tests.py", f) is None
        with mock.patch.object(requests, "delete", side_effect=requests.ConnectionError):
            assert not self.conn.delete_data("http://utek.pl")

    def test_retries(self) -> None:
        conn = Connection(retries=2)
        assert isinstance(conn._conn, requests.Session)
        adapter = conn._conn.get_adapter("http://x")
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == 2
        conn.close()
        # retries=0 without session stays on the plain module
        assert not isinstance(Connection()._conn, requests.Session)

    def test_default_timeout(self) -> None:
        conn = Connection(timeout=7.5)
        with mock.patch.object(requests, "get", return_value=mock.Mock(status_code=200, text="OK")) as get_mock:
            conn.get_data("http://utek.pl")
            assert get_mock.call_args.kwargs["timeout"] == 7.5
        with mock.patch.object(requests, "get", return_value=mock.Mock(status_code=200, text="OK")) as get_mock:
            conn.get_data("http://utek.pl", timeout=1.0)
            assert get_mock.call_args.kwargs["timeout"] == 1.0
        assert self.conn.timeout is None


class TestSeaweedFS:
    seaweed: SeaweedFS

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.seaweed = SeaweedFS()

    def test_repr(self) -> None:
        assert str(self.seaweed) == "<SeaweedFS localhost:9333>"

    def test_timeout_forwarded(self) -> None:
        w = SeaweedFS(timeout=3.0)
        assert w.conn.timeout == 3.0

    def test_default_conn_uses_plain_requests(self) -> None:
        w = SeaweedFS()
        assert w.conn._conn is requests
        w.close()

    def test_close_and_context_manager(self) -> None:
        with mock.patch.object(self.seaweed.conn, "close") as close_mock:
            self.seaweed.close()
            close_mock.assert_called_once_with()
        with SeaweedFS(use_session=True) as w:
            assert isinstance(w, SeaweedFS)
            assert isinstance(w.conn._conn, requests.Session)

    def test_exception(self) -> None:
        with HTTMock(assign_response):
            with pytest.raises(ValueError):
                self.seaweed.upload_file(stream=None, name="test.py")
            with open(__file__, "rb") as f, pytest.raises(ValueError):
                self.seaweed.upload_file(stream=f)

    def test_get_file_url(self) -> None:
        with HTTMock(FULL):
            assert self.seaweed.get_file_url(FID) == f"http://pub.local:8080/{FID}"
            assert self.seaweed.get_file_url(FID, public=False) == f"http://vol.local:8080/{FID}"

    def test_get_file_url_bad_fid(self) -> None:
        for bad_fid in ("badfid", "1,2,3", "3,", ",abc", "", "  ", "x,abc", "3,xyz"):
            with pytest.raises(BadFidFormat, match="fid must be in format"):
                self.seaweed.get_file_url(bad_fid)

    def test_get_file_url_sends_volume_id(self) -> None:
        captured: dict[str, Any] = {}

        def lookup(url: Any, request: Any) -> dict[str, Any]:
            captured["query"] = url.query
            return json_resp({"locations": [VOLUME_RESP]})

        with HTTMock(dispatch([("/dir/lookup", lookup)])):
            self.seaweed.get_file_url(FID)
            assert "volumeId=3" in captured["query"]

    def test_get_file_location_request_fails(self) -> None:
        mock = dispatch([("/dir/lookup", {"status_code": 500, "content": b"err"})])
        with HTTMock(mock):
            assert self.seaweed.get_file_location("3") is None

    def test_get_file_location_non_dict_response(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp([1, 2]))])
        with HTTMock(mock):
            assert self.seaweed.get_file_location("3") is None

    def test_get_file_url_fid_with_extension(self) -> None:
        with HTTMock(FULL):
            url = self.seaweed.get_file_url("3,01637037d6.png")
            assert url == "http://pub.local:8080/3,01637037d6.png"

    def test_get_file_url_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            assert self.seaweed.get_file_url(FID) is None

    def test_get_file_location(self) -> None:
        with HTTMock(FULL):
            loc = self.seaweed.get_file_location("3")
            assert loc is not None
            assert loc.public_url == "pub.local:8080"
            assert loc.url == "vol.local:8080"

    def test_get_file_location_bad_json(self) -> None:
        mock = dispatch([("/dir/lookup", {"status_code": 200, "content": b"not json"})])
        with HTTMock(mock):
            assert self.seaweed.get_file_location("3") is None

    def test_get_file_location_public_fallback(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": [{"url": "vol.local:8080"}]}))])
        with HTTMock(mock):
            loc = self.seaweed.get_file_location("3")
            assert loc is not None
            assert loc.public_url == "vol.local:8080"

    def test_get_file_location_locations_not_list(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": "nope"}))])
        with HTTMock(mock):
            assert self.seaweed.get_file_location("3") is None

    def test_get_file_location_filters_invalid(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": ["garbage", {"nop": 1}, VOLUME_RESP]}))])
        with HTTMock(mock):
            loc = self.seaweed.get_file_location("3")
            assert loc is not None
            assert loc.url == "vol.local:8080"

    def test_get_file_location_encodes_volume_id(self) -> None:
        captured: dict[str, Any] = {}

        def lookup(url: Any, request: Any) -> dict[str, Any]:
            captured["query"] = url.query
            return json_resp({"locations": []})

        with HTTMock(dispatch([("/dir/lookup", lookup)])):
            assert self.seaweed.get_file_location("3&x=1") is None
        assert "volumeId=3%26x%3D1" in captured["query"]

    def test_get_file(self) -> None:
        with HTTMock(FULL):
            assert self.seaweed.get_file(FID) == b"file-content"
            assert self.seaweed.get_file("3,deadbeef") is None

    def test_get_file_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            assert self.seaweed.get_file(FID) is None

    def test_get_file_byte_range(self) -> None:
        captured: dict[str, Any] = {}

        def ranged_file(url: Any, request: Any) -> dict[str, Any]:
            captured["range"] = request.headers.get("Range")
            return {"status_code": 206, "content": b"file-"}

        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/" + FID.split(",")[0] + ",", ranged_file),
        ])
        with HTTMock(mock):
            assert self.seaweed.get_file(FID, byte_range=(0, 4)) == b"file-"
            assert captured["range"] == "bytes=0-4"
            self.seaweed.get_file(FID, byte_range=(None, 100))
            assert captured["range"] == "bytes=-100"
            self.seaweed.get_file(FID, byte_range=(100, None))
            assert captured["range"] == "bytes=100-"
            self.seaweed.get_file(FID, byte_range=(None, None))
            assert captured["range"] is None

    def test_get_file_params(self) -> None:
        with HTTMock(FULL):
            url = self.seaweed.get_file_url(FID, params={"width": "10", "mode": "fit"})
            assert url is not None and url.endswith(f"/{FID}?width=10&mode=fit")
            assert self.seaweed.get_file(FID, params={"width": "10"}) == b"file-content"

    def test_get_file_stream(self) -> None:
        with HTTMock(FULL):
            stream = self.seaweed.get_file_stream(FID)
            assert stream is not None
            assert b"".join(stream) == b"file-content"
            stream = self.seaweed.get_file_stream(FID, byte_range=(0, 4), chunk_size=2)
            assert stream is not None
            assert b"".join(stream) == b"file-content"

    def test_get_file_stream_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            assert self.seaweed.get_file_stream(FID) is None

    def test_get_file_location_collection(self) -> None:
        captured: dict[str, Any] = {}

        def lookup(url: Any, request: Any) -> dict[str, Any]:
            captured["query"] = url.query
            return json_resp({"locations": [VOLUME_RESP]})

        with HTTMock(dispatch([("/dir/lookup", lookup)])):
            loc = self.seaweed.get_file_location("3", collection="pytest")
            assert loc is not None
        assert "collection=pytest" in captured["query"]
        assert "volumeId=3" in captured["query"]

    def test_get_file_url_collection(self) -> None:
        captured: dict[str, Any] = {}

        def lookup(url: Any, request: Any) -> dict[str, Any]:
            captured["query"] = url.query
            return json_resp({"locations": [VOLUME_RESP]})

        with HTTMock(dispatch([("/dir/lookup", lookup)])):
            url = self.seaweed.get_file_url(FID, collection="pytest")
            assert url == f"http://pub.local:8080/{FID}"
        assert "collection=pytest" in captured["query"]

    def test_get_file_size(self) -> None:
        with HTTMock(FULL):
            assert self.seaweed.get_file_size(FID) == 123
            assert self.seaweed.get_file_size("3,deadbeef") is None

    def test_get_file_forwards_params_collection_and_range(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            if url.path == "/dir/lookup":
                captured["lookup"] = url.query
                return json_resp({"locations": [VOLUME_RESP]})
            captured["file_url"] = url.geturl()
            captured["range"] = request.headers.get("Range")
            return {"status_code": 206, "content": b"data"}

        with HTTMock(all_requests(handler)):
            assert self.seaweed.get_file(FID, params={"width": "10"}, collection="mycol", byte_range=(0, 5)) == b"data"
        assert "collection=mycol" in captured["lookup"]
        assert "width=10" in captured["file_url"]
        assert captured["range"] == "bytes=0-5"

        captured.clear()
        with HTTMock(all_requests(handler)):
            assert self.seaweed.get_file(FID) == b"data"
        assert captured["range"] is None

    def test_get_file_stream_forwards_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            if url.path == "/dir/lookup":
                captured["lookup"] = url.query
                return json_resp({"locations": [VOLUME_RESP]})
            captured["file_url"] = url.geturl()
            captured["range"] = request.headers.get("Range")
            return {"status_code": 206, "content": b"abcde"}

        with HTTMock(all_requests(handler)):
            stream = self.seaweed.get_file_stream(FID, params={"x": "y"}, collection="c", byte_range=(1, 3), chunk_size=2)
            assert stream is not None
            assert list(stream) == [b"ab", b"cd", b"e"]
        assert "collection=c" in captured["lookup"]
        assert "x=y" in captured["file_url"]
        assert captured["range"] == "bytes=1-3"

    def test_get_file_stream_default_chunk_size(self) -> None:
        body = b"z" * 20000

        def handler(url: Any, request: Any) -> dict[str, Any]:
            if url.path == "/dir/lookup":
                return json_resp({"locations": [VOLUME_RESP]})
            return {"status_code": 200, "content": body}

        with HTTMock(all_requests(handler)):
            stream = self.seaweed.get_file_stream(FID)
            assert stream is not None
            sizes = [len(c) for c in stream]
        assert sizes == [8192, 8192, 3616]

    def test_submit_file_wire_details(self) -> None:
        captured: dict[str, Any] = {}
        resp = {"fid": FID, "fileName": "s.bin", "fileUrl": f"vol.local:8080/{FID}", "size": 5}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            captured["url"] = url.geturl()
            captured["body"] = request.body
            captured["headers"] = request.headers
            return json_resp(resp, status=201)

        with HTTMock(all_requests(handler)):
            assert self.seaweed.submit_file(
                stream=BytesIO(b"data"), name="s.bin", additional_headers={"X-Sub": "1"}, content_type="text/x-s"
            ) == FID
        assert captured["url"] == "http://localhost:9333/submit"
        body = captured["body"]
        if isinstance(body, str):
            body = body.encode()
        assert b'name="file"; filename="s.bin"' in body
        assert b"Content-Type: text/x-s" in body
        assert captured["headers"]["X-Sub"] == "1"

    def test_file_exists(self) -> None:
        with HTTMock(FULL):
            assert self.seaweed.file_exists(FID)
            assert not self.seaweed.file_exists("3,deadbeef")

    def test_collection_forwarded_to_lookup(self) -> None:
        captured: list[str] = []

        def lookup(url: Any, request: Any) -> dict[str, Any]:
            captured.append(url.query)
            return json_resp({"locations": [VOLUME_RESP]})

        mock = dispatch([("/dir/lookup", lookup), ("/" + FID, volume_file)])
        with HTTMock(mock):
            assert self.seaweed.file_exists(FID, collection="col")
            assert self.seaweed.get_file_size(FID, collection="col")
            assert self.seaweed.delete_file(FID, collection="col")
        assert all("collection=col" in q for q in captured)

    def test_delete_file(self) -> None:
        with HTTMock(FULL):
            assert self.seaweed.delete_file(FID)

    def test_delete_file_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            assert not self.seaweed.delete_file(FID)

    def test_upload_file_path(self) -> None:
        with HTTMock(FULL):
            assert self.seaweed.upload_file(__file__) == FID

    def test_upload_file_path_with_name(self) -> None:
        with HTTMock(FULL):
            assert self.seaweed.upload_file(__file__, name="custom.py") == FID

    def test_upload_file_stream(self) -> None:
        with HTTMock(FULL):
            with open(__file__, "rb") as f:
                assert self.seaweed.upload_file(stream=f, name="test.py") == FID

    def test_upload_file_assign_error(self) -> None:
        mock = dispatch([("/dir/assign", json_resp({"error": "no free volumes"}))])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__) is None

    def test_upload_file_assign_error_with_fid(self) -> None:
        resp = {"error": "quota", "fid": FID, "url": "vol.local:8080"}
        mock = dispatch([
            ("/dir/assign", json_resp(resp)),
            ("/" + FID.split(",")[0] + ",", volume_file),
        ])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__) is None

    def test_upload_file_assign_request_fails(self) -> None:
        mock = dispatch([("/dir/assign", {"status_code": 500, "content": b"err"})])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__) is None

    def test_upload_file_non_string_fid(self) -> None:
        resp = {"fid": 123, "url": "vol.local:8080", "count": 1}
        mock = dispatch([
            ("/dir/assign", json_resp(resp)),
            ("/123", json_resp({"size": 5}, status=201)),
        ])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__) is None

    def test_upload_file_uses_public_url(self) -> None:
        seen: list[str] = []
        resp = {"fid": FID, "url": "vol.local:8080", "publicUrl": "pub.example.com"}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            if url.path == "/dir/assign":
                return json_resp(resp)
            return json_resp({"size": 123}, status=201)

        w = SeaweedFS(use_public_url=True)
        with HTTMock(all_requests(handler)):
            assert w.upload_file(__file__) == FID
        assert seen[1] == f"http://pub.example.com/{FID}"

        seen.clear()
        w2 = SeaweedFS(use_public_url=False)
        with HTTMock(all_requests(handler)):
            assert w2.upload_file(__file__) == FID
        assert seen[1] == f"http://vol.local:8080/{FID}"

    def test_upload_file_volume_post_wire_details(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            if url.path == "/dir/assign":
                return json_resp(ASSIGN_RESP)
            captured["body"] = request.body
            captured["headers"] = request.headers
            return json_resp({"size": 123}, status=201)

        with HTTMock(all_requests(handler)):
            assert self.seaweed.upload_file(
                __file__, name="up.bin", additional_headers={"X-Up": "yes"}, content_type="text/x-up"
            ) == FID
        body = captured["body"]
        if isinstance(body, str):
            body = body.encode()
        assert b'name="file"; filename="up.bin"' in body
        assert b"Content-Type: text/x-up" in body
        assert captured["headers"]["X-Up"] == "yes"

    def test_upload_file_assign_url(self) -> None:
        seen: list[str] = []

        def handler(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            if url.path == "/dir/assign":
                return json_resp(ASSIGN_RESP)
            return volume_file(url, request)

        with HTTMock(all_requests(handler)):
            assert self.seaweed.upload_file(__file__) == FID
            assert seen[0] == "http://localhost:9333/dir/assign"
            seen.clear()
            assert self.seaweed.upload_file(__file__, collection="c", ttl="3d") == FID
            assert "collection=c" in seen[0]
            assert "ttl=3d" in seen[0]

    def test_upload_file_does_not_close_caller_stream(self) -> None:
        stream = BytesIO(b"data")
        with HTTMock(FULL):
            assert self.seaweed.upload_file(stream=stream, name="x.bin") == FID
        assert not stream.closed

    def test_upload_file_needs_name_or_path(self) -> None:
        with pytest.raises(ValueError, match="both.*stream.*and.*name"):
            self.seaweed.upload_file()
        with pytest.raises(ValueError, match="both.*stream.*and.*name"):
            self.seaweed.upload_file(stream=BytesIO(b"x"))

    def test_upload_file_assign_bad_json(self) -> None:
        mock = dispatch([("/dir/assign", {"status_code": 200, "content": b"not json"})])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__) is None

    def test_upload_file_post_fails(self) -> None:
        mock = dispatch([
            ("/dir/assign", json_resp(ASSIGN_RESP)),
            ("/" + FID.split(",")[0] + ",", {"status_code": 500, "content": b"err"}),
        ])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__) is None

    def test_upload_file_bad_volume_response(self) -> None:
        mock = dispatch([
            ("/dir/assign", json_resp(ASSIGN_RESP)),
            ("/" + FID.split(",")[0] + ",", {"status_code": 201, "content": b"not json"}),
        ])
        with HTTMock(mock):
            with pytest.raises(RuntimeError, match="Upload failed"):
                self.seaweed.upload_file(__file__)

    def test_upload_file_volume_error_response(self) -> None:
        mock = dispatch([
            ("/dir/assign", json_resp(ASSIGN_RESP)),
            ("/" + FID.split(",")[0] + ",", json_resp({"error": "too big"}, status=201)),
        ])
        with HTTMock(mock):
            with pytest.raises(RuntimeError, match="Upload failed"):
                self.seaweed.upload_file(__file__)

    def test_upload_file_public_url_fallback(self) -> None:
        mock = dispatch([
            ("/dir/assign", json_resp({"fid": FID, "url": "vol.local:8080"})),
            ("/" + FID.split(",")[0] + ",", volume_file),
        ])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__) == FID

    def test_upload_file_no_volume_url(self) -> None:
        mock = dispatch([("/dir/assign", json_resp({"fid": FID, "count": 1}))])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__) is None

    def test_submit_file(self) -> None:
        resp = {"fid": FID, "fileName": "test.py", "fileUrl": f"vol.local:8080/{FID}", "size": 123}
        mock = dispatch([("/submit", json_resp(resp, status=201))])
        with HTTMock(mock):
            assert self.seaweed.submit_file(__file__) == FID
            with open(__file__, "rb") as f:
                assert self.seaweed.submit_file(stream=f, name="test.py") == FID

    def test_submit_file_errors(self) -> None:
        with HTTMock(dispatch([("/submit", {"status_code": 500, "content": b"err"})])):
            assert self.seaweed.submit_file(__file__) is None
        with HTTMock(dispatch([("/submit", {"status_code": 201, "content": b"not json"})])):
            assert self.seaweed.submit_file(__file__) is None
        with HTTMock(dispatch([("/submit", json_resp([1, 2], status=201))])):
            assert self.seaweed.submit_file(__file__) is None
        with HTTMock(dispatch([("/submit", json_resp({"size": 1}, status=201))])):
            assert self.seaweed.submit_file(__file__) is None
        with pytest.raises(ValueError):
            self.seaweed.submit_file()

    def test_vacuum(self) -> None:
        seen: list[str] = []

        def vacuum(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return {"status_code": 200, "content": b"{}"}

        with HTTMock(dispatch([("/vol/vacuum", vacuum)])):
            assert self.seaweed.vacuum()
            assert "garbageThreshold=0.3" in seen[0]
            assert self.seaweed.vacuum(threshold=0.5)
            assert "garbageThreshold=0.5" in seen[1]

    def test_grow_volumes(self) -> None:
        seen: list[str] = []

        def grow(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return json_resp({"count": 1})

        with HTTMock(dispatch([("/vol/grow", grow)])):
            assert self.seaweed.grow_volumes(3, collection="x")
            assert "count=3" in seen[0]
            assert "collection=x" in seen[0]
        with HTTMock(dispatch([("/vol/grow", json_resp({"error": "only 0 volumes left"}))])):
            assert not self.seaweed.grow_volumes(1)
        with HTTMock(dispatch([("/vol/grow", {"status_code": 500, "content": b"err"})])):
            assert not self.seaweed.grow_volumes(1)

    def test_delete_collection(self) -> None:
        seen: list[str] = []

        def delete(url: Any, request: Any) -> dict[str, Any]:
            seen.append(url.geturl())
            return json_resp({})

        with HTTMock(dispatch([("/col/delete", delete)])):
            assert self.seaweed.delete_collection("c")
            assert "collection=c" in seen[0]
        with HTTMock(dispatch([("/col/delete", json_resp({"error": "collection c does not exist"}))])):
            assert not self.seaweed.delete_collection("c")

    def test_cluster_status(self) -> None:
        with HTTMock(dispatch([("/cluster/status", json_resp({"IsLeader": True}))])):
            assert self.seaweed.cluster_status() == {"IsLeader": True}
        with HTTMock(dispatch([("/cluster/status", {"status_code": 200, "content": b"bad"})])):
            assert self.seaweed.cluster_status() is None
        with HTTMock(dispatch([("/cluster/status", json_resp([1, 2]))])):
            assert self.seaweed.cluster_status() is None

    def test_volume_status(self) -> None:
        with HTTMock(dispatch([("/vol/status", json_resp({"Volumes": {}}))])):
            assert self.seaweed.volume_status() == {"Volumes": {}}

    def test_volume_server_status(self) -> None:
        captured: dict[str, Any] = {}

        def handler(url: Any, request: Any) -> dict[str, Any]:
            if url.path == "/dir/lookup":
                captured["lookup"] = url.query
                return json_resp({"locations": [VOLUME_RESP]})
            captured["status_url"] = url.geturl()
            return json_resp({"Version": "4.47"})

        with HTTMock(all_requests(handler)):
            assert self.seaweed.volume_server_status(FID, collection="c") == {"Version": "4.47"}
        assert "collection=c" in captured["lookup"]
        assert captured["status_url"] == "http://vol.local:8080/status"
        with HTTMock(dispatch([("/dir/lookup", json_resp({"locations": []}))])):
            assert self.seaweed.volume_server_status(FID) is None

    def test_is_healthy(self) -> None:
        with HTTMock(dispatch([("/cluster/healthz", {"status_code": 200, "content": b""})])):
            assert self.seaweed.is_healthy()
        with HTTMock(dispatch([("/cluster/healthz", {"status_code": 503, "content": b""})])):
            assert not self.seaweed.is_healthy()

    def test_version(self) -> None:
        with HTTMock(FULL):
            assert self.seaweed.version == "30GB 4.00"

    def test_version_bad_json(self) -> None:
        mock = dispatch([("/dir/status", {"status_code": 200, "content": b"not json"})])
        with HTTMock(mock):
            assert self.seaweed.version is None

    def test_get_file_location_missing_url(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": [{"publicUrl": "pub.local:8080"}]}))])
        with HTTMock(mock):
            assert self.seaweed.get_file_location("3") is None

    def test_get_file_size_no_content_length(self) -> None:
        def no_length(url: Any, request: Any) -> dict[str, Any]:
            return {"status_code": 200, "content": b""}

        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/" + FID.split(",")[0] + ",", no_length),
        ])
        with HTTMock(mock):
            assert self.seaweed.get_file_size(FID) is None

    def test_get_file_size_bad_content_length(self) -> None:
        def bad_length(url: Any, request: Any) -> dict[str, Any]:
            return {"status_code": 200, "headers": {"content-length": "abc"}, "content": b""}

        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/" + FID.split(",")[0] + ",", bad_length),
        ])
        with HTTMock(mock):
            assert self.seaweed.get_file_size(FID) is None

    def test_get_file_size_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            assert self.seaweed.get_file_size(FID) is None

    def test_file_exists_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            assert not self.seaweed.file_exists(FID)

    def test_version_non_dict_response(self) -> None:
        mock = dispatch([("/dir/status", json_resp([1, 2, 3]))])
        with HTTMock(mock):
            assert self.seaweed.version is None

    def test_version_non_str_value(self) -> None:
        mock = dispatch([("/dir/status", json_resp({"Version": 5}))])
        with HTTMock(mock):
            assert self.seaweed.version is None

    def test_upload_file_post_url_has_no_assign_query(self) -> None:
        captured: dict[str, Any] = {}

        def volume_post(url: Any, request: Any) -> dict[str, Any]:
            captured["post_path"] = url.path
            captured["post_query"] = url.query
            return json_resp({"size": 1}, status=201)

        mock = dispatch([
            ("/dir/assign", json_resp(ASSIGN_RESP)),
            ("/" + FID.split(",")[0] + ",", volume_post),
        ])
        with HTTMock(mock):
            assert self.seaweed.upload_file(__file__, collection="x") == FID
        assert captured["post_query"] == ""

    def test_volume_server_status_uses_internal_url(self) -> None:
        captured: dict[str, Any] = {}

        def status(url: Any, request: Any) -> dict[str, Any]:
            captured["netloc"] = url.netloc
            return json_resp({"Version": "4.47"})

        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/status", status),
        ])
        with HTTMock(mock):
            assert self.seaweed.volume_server_status(FID) == {"Version": "4.47"}
        assert captured["netloc"] == "vol.local:8080"


class TestExceptions:
    def test_bad_fid_format_str(self) -> None:
        exc = BadFidFormat("bad fid")
        assert str(exc) == "bad fid"
        assert exc.value == "bad fid"
        assert exc.args == ("bad fid",)


class TestNegativePaths:
    """Negative-path and malformed-input coverage."""

    weed: SeaweedFS

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.weed = SeaweedFS()

    def test_fid_format_edges(self) -> None:
        for fid in ("3,ABCD", "03,ab", "3,01637037d6.png", "3,ab.-_", " 3,ab ", "3,ab\n"):
            with HTTMock(dispatch([("/dir/lookup", json_resp({"locations": [VOLUME_RESP]}))])):
                assert self.weed.get_file_url(fid) is not None
        for bad_fid in ("3,ab.txt.png", "3, ab", "3,ab,cd", "3,g", "3,0f-2_4"):
            with pytest.raises(BadFidFormat):
                self.weed.get_file_url(bad_fid)

    def test_lookup_malformed_responses(self) -> None:
        for data in (5, "x", [], {}, {"locations": None}, {"locations": "x"}, {"locations": [5]}, {"locations": [{"url": ""}]}):
            with HTTMock(dispatch([("/dir/lookup", json_resp(data))])):
                assert self.weed.get_file_location("3") is None

    def test_upload_assign_malformed(self) -> None:
        for data in (5, [], {"fid": ""}, {"fid": 123}, {"fid": FID}, {"fid": FID, "url": None}, {"fid": FID, "url": ""}, {"error": "no volumes"}):
            with HTTMock(dispatch([("/dir/assign", json_resp(data))])):
                assert self.weed.upload_file(__file__) is None

    def test_upload_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            self.weed.upload_file("/nonexistent-path-xyz.txt")

    def test_submit_malformed_responses(self) -> None:
        for data in (5, "x", [], {"fid": None}, {"fid": 123}, {}):
            with HTTMock(dispatch([("/submit", json_resp(data))])):
                assert self.weed.submit_file(__file__) is None

    def test_get_file_size_bad_header(self) -> None:
        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/" + FID.split(",")[0] + ",", {"status_code": 200, "headers": {"content-length": "not-a-number"}}),
        ])
        with HTTMock(mock):
            assert self.weed.get_file_size(FID) is None

    def test_get_file_size_missing_header(self) -> None:
        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/" + FID.split(",")[0] + ",", {"status_code": 200, "content": b""}),
        ])
        with HTTMock(mock):
            assert self.weed.get_file_size(FID) is None


class TestCommonHelpers:
    """Direct coverage of shared helpers in pyseaweed._common."""

    def test_range_headers_edges(self) -> None:
        from pyseaweed._common import range_headers

        assert range_headers(None) is None
        assert range_headers((None, None)) is None
        assert range_headers((0, 0)) == {"Range": "bytes=0-0"}
        assert range_headers((None, 500)) == {"Range": "bytes=-500"}
        assert range_headers((5, 3)) == {"Range": "bytes=5-3"}
        assert range_headers((-1, None)) == {"Range": "bytes=-1-"}

    def test_canonical_tag_name_edges(self) -> None:
        from pyseaweed._common import canonical_tag_name

        assert canonical_tag_name("color") == "Color"
        assert canonical_tag_name("my-tag") == "My-Tag"
        assert canonical_tag_name("COLOR") == "Color"
        assert canonical_tag_name("") == ""
        assert canonical_tag_name("-a") == "-A"
        assert canonical_tag_name("a--b") == "A--B"

    def test_prepare_stream_path_wins_over_stream(self) -> None:
        import io

        from pyseaweed._common import prepare_stream

        filename, stream, close_stream = prepare_stream(__file__, io.BytesIO(b"stream-data"), "override.bin")
        try:
            assert filename == "override.bin"
            assert stream.read() != b"stream-data"
            assert close_stream is True
        finally:
            stream.close()

    def test_prepare_stream_missing_name(self) -> None:
        import io

        from pyseaweed._common import prepare_stream

        with pytest.raises(ValueError):
            prepare_stream(None, io.BytesIO(b"x"), None)
        with pytest.raises(ValueError):
            prepare_stream(None, None, "n.bin")
