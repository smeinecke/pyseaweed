# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4


import unittest
from typing import Any, Dict

from httmock import HTTMock

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


class ReqTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = Connection()
        pass

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

    def test_delete_data(self) -> None:
        with HTTMock(response_content):
            r = self.conn.delete_data("http://localhost")
            self.assertTrue(r)
        with HTTMock(response_content_202):
            r = self.conn.delete_data("http://localhost")
            self.assertTrue(r)
        with HTTMock(response_content_404):
            r = self.conn.delete_data("http://localhost")
            self.assertFalse(r)

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


class SeaweedFSTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seaweed = SeaweedFS()
        pass

    def test_repr(self) -> None:
        self.assertEqual(str(self.seaweed), "<SeaweedFS localhost:9333>")

    def test_exception(self) -> None:
        with HTTMock(assign_response):
            with self.assertRaises(ValueError):
                self.seaweed.upload_file(stream=None, name="test.py")
            with open(__file__, "rb") as f, self.assertRaises(ValueError):
                self.seaweed.upload_file(stream=f)
