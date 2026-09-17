# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4


from __future__ import print_function

import io
import os
import unittest

import pytest

from pyseaweed.exceptions import BadFidFormat
from pyseaweed.seaweed import SeaweedFS

pytestmark = pytest.mark.integration


class FunctionalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seaweed = SeaweedFS()

    def test_head_file(self) -> None:
        _file = __file__
        fid = self.seaweed.upload_file(_file)
        assert fid is not None
        res = self.seaweed.get_file_size(fid)
        assert res is not None
        # Size is same or lower than file on disk
        self.assertTrue(res <= os.path.getsize(_file))
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)
        res = self.seaweed.get_file_size("3,123456790")
        self.assertIsNone(res)

    def test_upload_delete(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_version(self) -> None:
        ver = self.seaweed.version
        self.assertIsNotNone(ver)

    def test_exists(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        self.assertTrue(self.seaweed.file_exists(fid))
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)
        self.assertFalse(self.seaweed.file_exists(fid))

    def test_upload_stream(self) -> None:
        with open(__file__, "rb") as stream:
            fid = self.seaweed.upload_file(stream=stream, name="test.py")
            assert fid is not None
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_vacuum(self) -> None:
        res = self.seaweed.vacuum()
        self.assertTrue(res)

    def test_get_file_url_variants(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        url_public = self.seaweed.get_file_url(fid)
        url_internal = self.seaweed.get_file_url(fid, public=False)
        assert url_public is not None
        assert url_internal is not None
        self.assertTrue(url_public.endswith(fid))
        self.assertTrue(url_internal.endswith(fid))
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_get_file_location(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        loc = self.seaweed.get_file_location(fid.split(",")[0])
        assert loc is not None
        self.assertTrue(loc.url)
        self.assertTrue(loc.public_url)
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_upload_with_options(self) -> None:
        fid = self.seaweed.upload_file(
            __file__,
            name="custom_name.py",
            content_type="text/x-python",
            additional_headers={"X-Test-Header": "1"},
            count="2",
        )
        assert fid is not None
        self.assertTrue(self.seaweed.file_exists(fid))
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_internal_url_client(self) -> None:
        seaweed = SeaweedFS(use_public_url=False)
        fid = seaweed.upload_file(__file__)
        assert fid is not None
        self.assertTrue(seaweed.file_exists(fid))
        self.assertTrue(seaweed.delete_file(fid))

    def test_bad_fid(self) -> None:
        self.assertRaises(BadFidFormat, self.seaweed.get_file_url, "a")

    def test_get_file(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        file_content = self.seaweed.get_file(fid)
        self.assertIsNotNone(file_content)
        with open(__file__, "rb") as f:
            content = f.read()
        self.assertEqual(content, file_content)
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_get_file_byte_range(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="range.bin")
        assert fid is not None
        self.assertEqual(self.seaweed.get_file(fid, byte_range=(0, 4)), b"01234")
        self.assertEqual(self.seaweed.get_file(fid, byte_range=(5, None)), b"56789")
        self.assertTrue(self.seaweed.delete_file(fid))

    def test_get_file_stream(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="stream.bin")
        assert fid is not None
        stream = self.seaweed.get_file_stream(fid, chunk_size=4)
        assert stream is not None
        self.assertEqual(b"".join(stream), b"0123456789")
        self.assertTrue(self.seaweed.delete_file(fid))

    def test_get_file_location_collection(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"data"), name="col.bin")
        assert fid is not None
        loc = self.seaweed.get_file_location(fid.split(",")[0], collection="")
        self.assertIsNotNone(loc)
        self.assertIsNone(self.seaweed.get_file_location(fid.split(",")[0], collection="no-such-collection"))
        self.assertTrue(self.seaweed.delete_file(fid))

    def test_submit_file(self) -> None:
        fid = self.seaweed.submit_file(stream=io.BytesIO(b"submit-data"), name="submit.bin")
        assert fid is not None
        self.assertEqual(self.seaweed.get_file(fid), b"submit-data")
        self.assertTrue(self.seaweed.delete_file(fid))

    def test_get_wrong_file(self) -> None:
        file_content = self.seaweed.get_file("3,123456790")
        self.assertIsNone(file_content)


class FunctionalTestsSession(unittest.TestCase):
    def setUp(self) -> None:
        self.seaweed = SeaweedFS(use_session=True)

    def test_head_file(self) -> None:
        _file = __file__
        fid = self.seaweed.upload_file(_file)
        assert fid is not None
        res = self.seaweed.get_file_size(fid)
        assert res is not None
        # Size is same or lower than file on disk
        self.assertTrue(res <= os.path.getsize(_file))
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)
        res = self.seaweed.get_file_size("3,123456790")
        self.assertIsNone(res)

    def test_upload_delete(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_version(self) -> None:
        ver = self.seaweed.version
        self.assertIsNotNone(ver)

    def test_exists(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        self.assertTrue(self.seaweed.file_exists(fid))
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)
        self.assertFalse(self.seaweed.file_exists(fid))

    def test_upload_stream(self) -> None:
        with open(__file__, "rb") as stream:
            fid = self.seaweed.upload_file(stream=stream, name="test.py")
            assert fid is not None
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_vacuum(self) -> None:
        res = self.seaweed.vacuum()
        self.assertTrue(res)

    def test_get_file_url_variants(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        url_public = self.seaweed.get_file_url(fid)
        url_internal = self.seaweed.get_file_url(fid, public=False)
        assert url_public is not None
        assert url_internal is not None
        self.assertTrue(url_public.endswith(fid))
        self.assertTrue(url_internal.endswith(fid))
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_get_file_location(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        loc = self.seaweed.get_file_location(fid.split(",")[0])
        assert loc is not None
        self.assertTrue(loc.url)
        self.assertTrue(loc.public_url)
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_upload_with_options(self) -> None:
        fid = self.seaweed.upload_file(
            __file__,
            name="custom_name.py",
            content_type="text/x-python",
            additional_headers={"X-Test-Header": "1"},
            count="2",
        )
        assert fid is not None
        self.assertTrue(self.seaweed.file_exists(fid))
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_internal_url_client(self) -> None:
        seaweed = SeaweedFS(use_public_url=False)
        fid = seaweed.upload_file(__file__)
        assert fid is not None
        self.assertTrue(seaweed.file_exists(fid))
        self.assertTrue(seaweed.delete_file(fid))

    def test_bad_fid(self) -> None:
        self.assertRaises(BadFidFormat, self.seaweed.get_file_url, "a")

    def test_get_file(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        file_content = self.seaweed.get_file(fid)
        self.assertIsNotNone(file_content)
        with open(__file__, "rb") as f:
            content = f.read()
        self.assertEqual(content, file_content)
        res = self.seaweed.delete_file(fid)
        self.assertTrue(res)

    def test_get_file_byte_range(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="range.bin")
        assert fid is not None
        self.assertEqual(self.seaweed.get_file(fid, byte_range=(0, 4)), b"01234")
        self.assertEqual(self.seaweed.get_file(fid, byte_range=(5, None)), b"56789")
        self.assertTrue(self.seaweed.delete_file(fid))

    def test_get_file_stream(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="stream.bin")
        assert fid is not None
        stream = self.seaweed.get_file_stream(fid, chunk_size=4)
        assert stream is not None
        self.assertEqual(b"".join(stream), b"0123456789")
        self.assertTrue(self.seaweed.delete_file(fid))

    def test_get_file_location_collection(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"data"), name="col.bin")
        assert fid is not None
        loc = self.seaweed.get_file_location(fid.split(",")[0], collection="")
        self.assertIsNotNone(loc)
        self.assertIsNone(self.seaweed.get_file_location(fid.split(",")[0], collection="no-such-collection"))
        self.assertTrue(self.seaweed.delete_file(fid))

    def test_submit_file(self) -> None:
        fid = self.seaweed.submit_file(stream=io.BytesIO(b"submit-data"), name="submit.bin")
        assert fid is not None
        self.assertEqual(self.seaweed.get_file(fid), b"submit-data")
        self.assertTrue(self.seaweed.delete_file(fid))

    def test_get_wrong_file(self) -> None:
        file_content = self.seaweed.get_file("3,123456790")
        self.assertIsNone(file_content)
