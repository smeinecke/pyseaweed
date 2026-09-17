# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4


from __future__ import print_function

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

    # Test vacuum generated problems with Weed-FS on windows.
    # TODO: Investigate
    # def test_vacuum(self):
    #     res = self.seaweed.vacuum()
    #     self.assertTrue(res)
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

    # Test vacuum generated problems with Weed-FS on windows.
    # TODO: Investigate
    # def test_vacuum(self):
    #     res = self.seaweed.vacuum()
    #     self.assertTrue(res)
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

    def test_get_wrong_file(self) -> None:
        file_content = self.seaweed.get_file("3,123456790")
        self.assertIsNone(file_content)
