# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4


import json
import unittest
from typing import Any, Dict, List, Tuple, cast
from unittest import mock

import requests
from httmock import HTTMock, all_requests

from pyseaweed.exceptions import BadFidFormat
from pyseaweed.seaweed import SeaweedFS
from pyseaweed.utils import Connection


def response_content(url: Any, request: Any) -> Dict[str, Any]:
    return {"status_code": 200, "content": b"OK"}


def response_content_201(url: Any, request: Any) -> Dict[str, Any]:
    return {"status_code": 201, "content": b"OK"}


def response_content_202(url: Any, request: Any) -> Dict[str, Any]:
    return {"status_code": 202, "content": b"OK"}


def response_content_404(url: Any, request: Any) -> Dict[str, Any]:
    return {"status_code": 404, "content": b"NOK"}


def assign_response(url: Any, request: Any) -> Dict[str, Any]:
    return {
        "status_code": 200,
        "content": b'{"fid": "3,01637037d6", "url": "localhost:8080", "publicUrl": "localhost:8080", "count": 1}',
    }


VOLUME_RESP = {"url": "vol.local:8080", "publicUrl": "pub.local:8080"}
ASSIGN_RESP = {"fid": "3,01637037d6", "url": "vol.local:8080", "publicUrl": "pub.local:8080", "count": 1}
FID = "3,01637037d6"


def json_resp(data: Any, status: int = 200) -> Dict[str, Any]:
    return {"status_code": status, "content": json.dumps(data).encode()}


def volume_file(url: Any, request: Any) -> Dict[str, Any]:
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


def dispatch(routes: List[Tuple[str, Any]]) -> Any:
    @all_requests
    def handler(url: Any, request: Any) -> Dict[str, Any]:
        for prefix, resp in routes:
            if url.path.startswith(prefix):
                resp = resp(url, request) if callable(resp) else resp
                return cast(Dict[str, Any], resp)
        return {"status_code": 404, "content": b"NOK"}

    return handler


FULL = dispatch([
    ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
    ("/dir/assign", json_resp(ASSIGN_RESP)),
    ("/dir/status", json_resp({"Version": "30GB 4.00"})),
    ("/vol/vacuum", {"status_code": 200, "content": b"{}"}),
    ("/" + FID.split(",")[0] + ",", volume_file),
])


class ReqTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = Connection()

    def test_post_file(self) -> None:
        with HTTMock(response_content):
            with open(__file__, "rb") as f:
                r = self.conn.post_file("http://utek.pl", "tests.py", f)
            self.assertEqual(r, "OK")
        with HTTMock(response_content_201):
            with open(__file__, "rb") as f:
                r = self.conn.post_file("http://utek.pl", "tests.py", f)
            self.assertEqual(r, "OK")
        with HTTMock(response_content_404):
            with open(__file__, "rb") as f:
                r = self.conn.post_file("http://utek.pl", "tests.py", f)
            self.assertIsNone(r)

    def test_post_file_content_type(self) -> None:
        with HTTMock(response_content):
            with open(__file__, "rb") as f:
                r = self.conn.post_file("http://utek.pl", "tests.py", f, content_type="text/x-python")
            self.assertEqual(r, "OK")

    def test_get_data(self) -> None:
        with HTTMock(response_content):
            r = self.conn.get_data("http://utek.pl")
            self.assertEqual(r, "OK")
        with HTTMock(response_content_404):
            r = self.conn.get_data("http://utek.pl")
            self.assertIsNone(r)

    def test_get_raw_data(self) -> None:
        with HTTMock(response_content):
            r = self.conn.get_raw_data("http://utek.pl")
            self.assertEqual(r, b"OK")
        with HTTMock(response_content_404):
            r = self.conn.get_raw_data("http://utek.pl")
            self.assertIsNone(r)

    def test_head(self) -> None:
        with HTTMock(response_content):
            r = self.conn.head("http://utek.pl")
            assert r is not None
            self.assertEqual(r.status_code, 200)
        with HTTMock(response_content_404):
            r = self.conn.head("http://utek.pl")
            self.assertIsNone(r)

    def test_delete_data(self) -> None:
        with HTTMock(response_content):
            r = self.conn.delete_data("http://localhost")
            self.assertTrue(r)
        with HTTMock(response_content_202):
            r = self.conn.delete_data("http://localhost")
            self.assertTrue(r)
        with HTTMock(lambda url, request: {"status_code": 204, "content": b""}):
            r = self.conn.delete_data("http://localhost")
            self.assertTrue(r)
        with HTTMock(response_content_404):
            r = self.conn.delete_data("http://localhost")
            self.assertFalse(r)

    def test_close(self) -> None:
        conn = Connection(use_session=True)
        with mock.patch.object(conn._conn, "close") as close_mock:
            conn.close()
            close_mock.assert_called_once_with()
        self.conn.close()

    def test_context_manager(self) -> None:
        with Connection(use_session=True) as conn:
            self.assertIsInstance(conn, Connection)

    def test_prepare_headers(self) -> None:
        headers = self.conn._prepare_headers()
        self.assertIsInstance(headers, dict)
        for k, v in headers.items():
            self.assertIsInstance(k, str)
            self.assertIsInstance(v, str)

    def test_additional_headers(self) -> None:
        additional_headers = {"X-Test": "123"}
        headers = self.conn._prepare_headers(additional_headers)
        self.assertIsInstance(headers, dict)
        self.assertIsNotNone(headers.get("X-Test"))
        with HTTMock(response_content):
            with open(__file__, "rb") as f:
                r = self.conn.post_file(
                    "http://utek.pl",
                    "tests.py",
                    f,
                    additional_headers=additional_headers,
                )
            self.assertEqual(r, "OK")
            r = self.conn.get_data("http://utek.pl", additional_headers=additional_headers)
            self.assertEqual(r, "OK")
            r = self.conn.get_raw_data("http://utek.pl", additional_headers=additional_headers)
            self.assertEqual(r, b"OK")
            r = self.conn.delete_data("http://localhost", additional_headers=additional_headers)
            self.assertTrue(r)

    def test_use_session(self) -> None:
        conn = Connection(use_session=True)
        with HTTMock(response_content):
            self.assertEqual(conn.get_data("http://utek.pl"), "OK")

    def test_get_stream(self) -> None:
        with HTTMock(response_content):
            stream = self.conn.get_stream("http://utek.pl")
            assert stream is not None
            self.assertEqual(b"".join(stream), b"OK")
        with HTTMock(response_content_404):
            self.assertIsNone(self.conn.get_stream("http://utek.pl"))

    def test_transport_errors(self) -> None:
        with mock.patch.object(requests, "get", side_effect=requests.ConnectionError):
            self.assertIsNone(self.conn.get_data("http://utek.pl"))
            self.assertIsNone(self.conn.get_raw_data("http://utek.pl"))
            self.assertIsNone(self.conn.get_stream("http://utek.pl"))
        with mock.patch.object(requests, "head", side_effect=requests.Timeout):
            self.assertIsNone(self.conn.head("http://utek.pl"))
        with mock.patch.object(requests, "post", side_effect=requests.ConnectionError):
            with open(__file__, "rb") as f:
                self.assertIsNone(self.conn.post_file("http://utek.pl", "tests.py", f))
        with mock.patch.object(requests, "delete", side_effect=requests.ConnectionError):
            self.assertFalse(self.conn.delete_data("http://utek.pl"))


class SeaweedFSTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seaweed = SeaweedFS()

    def test_repr(self) -> None:
        self.assertEqual(str(self.seaweed), "<SeaweedFS localhost:9333>")

    def test_exception(self) -> None:
        with HTTMock(assign_response):
            with self.assertRaises(ValueError):
                self.seaweed.upload_file(stream=None, name="test.py")
            with open(__file__, "rb") as f, self.assertRaises(ValueError):
                self.seaweed.upload_file(stream=f)

    def test_get_file_url(self) -> None:
        with HTTMock(FULL):
            self.assertEqual(self.seaweed.get_file_url(FID), f"http://pub.local:8080/{FID}")
            self.assertEqual(self.seaweed.get_file_url(FID, public=False), f"http://vol.local:8080/{FID}")

    def test_get_file_url_bad_fid(self) -> None:
        with self.assertRaises(BadFidFormat):
            self.seaweed.get_file_url("badfid")
        with self.assertRaises(BadFidFormat):
            self.seaweed.get_file_url("1,2,3")

    def test_get_file_url_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file_url(FID))

    def test_get_file_location(self) -> None:
        with HTTMock(FULL):
            loc = self.seaweed.get_file_location("3")
            assert loc is not None
            self.assertEqual(loc.public_url, "pub.local:8080")
            self.assertEqual(loc.url, "vol.local:8080")

    def test_get_file_location_bad_json(self) -> None:
        mock = dispatch([("/dir/lookup", {"status_code": 200, "content": b"not json"})])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file_location("3"))

    def test_get_file_location_public_fallback(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": [{"url": "vol.local:8080"}]}))])
        with HTTMock(mock):
            loc = self.seaweed.get_file_location("3")
            assert loc is not None
            self.assertEqual(loc.public_url, "vol.local:8080")

    def test_get_file_location_locations_not_list(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": "nope"}))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file_location("3"))

    def test_get_file_location_filters_invalid(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": ["garbage", {"nop": 1}, VOLUME_RESP]}))])
        with HTTMock(mock):
            loc = self.seaweed.get_file_location("3")
            assert loc is not None
            self.assertEqual(loc.url, "vol.local:8080")

    def test_get_file_location_encodes_volume_id(self) -> None:
        captured: Dict[str, Any] = {}

        def lookup(url: Any, request: Any) -> Dict[str, Any]:
            captured["query"] = url.query
            return json_resp({"locations": []})

        with HTTMock(dispatch([("/dir/lookup", lookup)])):
            self.assertIsNone(self.seaweed.get_file_location("3&x=1"))
        self.assertIn("volumeId=3%26x%3D1", captured["query"])

    def test_get_file(self) -> None:
        with HTTMock(FULL):
            self.assertEqual(self.seaweed.get_file(FID), b"file-content")
            self.assertIsNone(self.seaweed.get_file("3,deadbeef"))

    def test_get_file_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file(FID))

    def test_get_file_byte_range(self) -> None:
        captured: Dict[str, Any] = {}

        def ranged_file(url: Any, request: Any) -> Dict[str, Any]:
            captured["range"] = request.headers.get("Range")
            return {"status_code": 206, "content": b"file-"}

        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/" + FID.split(",")[0] + ",", ranged_file),
        ])
        with HTTMock(mock):
            self.assertEqual(self.seaweed.get_file(FID, byte_range=(0, 4)), b"file-")
            self.assertEqual(captured["range"], "bytes=0-4")
            self.seaweed.get_file(FID, byte_range=(None, 100))
            self.assertEqual(captured["range"], "bytes=-100")
            self.seaweed.get_file(FID, byte_range=(100, None))
            self.assertEqual(captured["range"], "bytes=100-")

    def test_get_file_params(self) -> None:
        with HTTMock(FULL):
            url = self.seaweed.get_file_url(FID, params={"width": "10", "mode": "fit"})
            self.assertTrue(url is not None and url.endswith(f"/{FID}?width=10&mode=fit"))
            self.assertEqual(self.seaweed.get_file(FID, params={"width": "10"}), b"file-content")

    def test_get_file_stream(self) -> None:
        with HTTMock(FULL):
            stream = self.seaweed.get_file_stream(FID)
            assert stream is not None
            self.assertEqual(b"".join(stream), b"file-content")
            stream = self.seaweed.get_file_stream(FID, byte_range=(0, 4), chunk_size=2)
            assert stream is not None
            self.assertEqual(b"".join(stream), b"file-content")

    def test_get_file_stream_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file_stream(FID))

    def test_get_file_location_collection(self) -> None:
        captured: Dict[str, Any] = {}

        def lookup(url: Any, request: Any) -> Dict[str, Any]:
            captured["query"] = url.query
            return json_resp({"locations": [VOLUME_RESP]})

        with HTTMock(dispatch([("/dir/lookup", lookup)])):
            loc = self.seaweed.get_file_location("3", collection="pytest")
            assert loc is not None
        self.assertIn("collection=pytest", captured["query"])
        self.assertIn("volumeId=3", captured["query"])

    def test_get_file_size(self) -> None:
        with HTTMock(FULL):
            self.assertEqual(self.seaweed.get_file_size(FID), 123)
            self.assertIsNone(self.seaweed.get_file_size("3,deadbeef"))

    def test_file_exists(self) -> None:
        with HTTMock(FULL):
            self.assertTrue(self.seaweed.file_exists(FID))
            self.assertFalse(self.seaweed.file_exists("3,deadbeef"))

    def test_delete_file(self) -> None:
        with HTTMock(FULL):
            self.assertTrue(self.seaweed.delete_file(FID))

    def test_delete_file_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            self.assertFalse(self.seaweed.delete_file(FID))

    def test_upload_file_path(self) -> None:
        with HTTMock(FULL):
            self.assertEqual(self.seaweed.upload_file(__file__), FID)

    def test_upload_file_path_with_name(self) -> None:
        with HTTMock(FULL):
            self.assertEqual(self.seaweed.upload_file(__file__, name="custom.py"), FID)

    def test_upload_file_stream(self) -> None:
        with HTTMock(FULL):
            with open(__file__, "rb") as f:
                self.assertEqual(self.seaweed.upload_file(stream=f, name="test.py"), FID)

    def test_upload_file_assign_error(self) -> None:
        mock = dispatch([("/dir/assign", json_resp({"error": "no free volumes"}))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.upload_file(__file__))

    def test_upload_file_assign_bad_json(self) -> None:
        mock = dispatch([("/dir/assign", {"status_code": 200, "content": b"not json"})])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.upload_file(__file__))

    def test_upload_file_post_fails(self) -> None:
        mock = dispatch([
            ("/dir/assign", json_resp(ASSIGN_RESP)),
            ("/" + FID.split(",")[0] + ",", {"status_code": 500, "content": b"err"}),
        ])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.upload_file(__file__))

    def test_upload_file_bad_volume_response(self) -> None:
        mock = dispatch([
            ("/dir/assign", json_resp(ASSIGN_RESP)),
            ("/" + FID.split(",")[0] + ",", {"status_code": 201, "content": b"not json"}),
        ])
        with HTTMock(mock):
            with self.assertRaises(RuntimeError):
                self.seaweed.upload_file(__file__)

    def test_upload_file_volume_error_response(self) -> None:
        mock = dispatch([
            ("/dir/assign", json_resp(ASSIGN_RESP)),
            ("/" + FID.split(",")[0] + ",", json_resp({"error": "too big"}, status=201)),
        ])
        with HTTMock(mock):
            with self.assertRaises(RuntimeError):
                self.seaweed.upload_file(__file__)

    def test_upload_file_public_url_fallback(self) -> None:
        mock = dispatch([
            ("/dir/assign", json_resp({"fid": FID, "url": "vol.local:8080"})),
            ("/" + FID.split(",")[0] + ",", volume_file),
        ])
        with HTTMock(mock):
            self.assertEqual(self.seaweed.upload_file(__file__), FID)

    def test_upload_file_no_volume_url(self) -> None:
        mock = dispatch([("/dir/assign", json_resp({"fid": FID, "count": 1}))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.upload_file(__file__))

    def test_vacuum(self) -> None:
        with HTTMock(FULL):
            self.assertTrue(self.seaweed.vacuum())

    def test_version(self) -> None:
        with HTTMock(FULL):
            self.assertEqual(self.seaweed.version, "30GB 4.00")

    def test_version_bad_json(self) -> None:
        mock = dispatch([("/dir/status", {"status_code": 200, "content": b"not json"})])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.version)

    def test_get_file_location_missing_url(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": [{"publicUrl": "pub.local:8080"}]}))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file_location("3"))

    def test_get_file_size_no_content_length(self) -> None:
        def no_length(url: Any, request: Any) -> Dict[str, Any]:
            return {"status_code": 200, "content": b""}

        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/" + FID.split(",")[0] + ",", no_length),
        ])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file_size(FID))

    def test_get_file_size_bad_content_length(self) -> None:
        def bad_length(url: Any, request: Any) -> Dict[str, Any]:
            return {"status_code": 200, "headers": {"content-length": "abc"}, "content": b""}

        mock = dispatch([
            ("/dir/lookup", json_resp({"locations": [VOLUME_RESP]})),
            ("/" + FID.split(",")[0] + ",", bad_length),
        ])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file_size(FID))

    def test_get_file_size_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.get_file_size(FID))

    def test_file_exists_no_volume(self) -> None:
        mock = dispatch([("/dir/lookup", json_resp({"locations": []}))])
        with HTTMock(mock):
            self.assertFalse(self.seaweed.file_exists(FID))

    def test_version_non_dict_response(self) -> None:
        mock = dispatch([("/dir/status", json_resp([1, 2, 3]))])
        with HTTMock(mock):
            self.assertIsNone(self.seaweed.version)


class ExceptionTests(unittest.TestCase):
    def test_bad_fid_format_str(self) -> None:
        exc = BadFidFormat("bad fid")
        self.assertEqual(str(exc), "bad fid")
        self.assertEqual(exc.value, "bad fid")
