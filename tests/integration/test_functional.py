import io
import os

import pytest

from pyseaweed.exceptions import BadFidFormat
from pyseaweed.seaweed import SeaweedFS

pytestmark = pytest.mark.integration


class TestFunctional:
    seaweed: SeaweedFS

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.seaweed = SeaweedFS()

    def test_head_file(self) -> None:
        _file = __file__
        fid = self.seaweed.upload_file(_file)
        assert fid is not None
        res = self.seaweed.get_file_size(fid)
        assert res is not None
        # Size is same or lower than file on disk
        assert res <= os.path.getsize(_file)
        res = self.seaweed.delete_file(fid)
        assert res
        res = self.seaweed.get_file_size("3,123456790")
        assert res is None

    def test_upload_delete(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        res = self.seaweed.delete_file(fid)
        assert res

    def test_version(self) -> None:
        ver = self.seaweed.version
        assert ver is not None

    def test_exists(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        assert self.seaweed.file_exists(fid)
        res = self.seaweed.delete_file(fid)
        assert res
        assert not self.seaweed.file_exists(fid)

    def test_upload_stream(self) -> None:
        with open(__file__, "rb") as stream:
            fid = self.seaweed.upload_file(stream=stream, name="test.py")
            assert fid is not None
        res = self.seaweed.delete_file(fid)
        assert res

    def test_vacuum(self) -> None:
        res = self.seaweed.vacuum()
        assert res

    def test_get_file_url_variants(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        url_public = self.seaweed.get_file_url(fid)
        url_internal = self.seaweed.get_file_url(fid, public=False)
        assert url_public is not None
        assert url_internal is not None
        assert url_public.endswith(fid)
        assert url_internal.endswith(fid)
        res = self.seaweed.delete_file(fid)
        assert res

    def test_get_file_location(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        loc = self.seaweed.get_file_location(fid.split(",")[0])
        assert loc is not None
        assert loc.url
        assert loc.public_url
        res = self.seaweed.delete_file(fid)
        assert res

    def test_upload_with_options(self) -> None:
        fid = self.seaweed.upload_file(
            __file__,
            name="custom_name.py",
            content_type="text/x-python",
            additional_headers={"X-Test-Header": "1"},
            count="2",
        )
        assert fid is not None
        assert self.seaweed.file_exists(fid)
        res = self.seaweed.delete_file(fid)
        assert res

    def test_internal_url_client(self) -> None:
        seaweed = SeaweedFS(use_public_url=False)
        fid = seaweed.upload_file(__file__)
        assert fid is not None
        assert seaweed.file_exists(fid)
        assert seaweed.delete_file(fid)

    def test_bad_fid(self) -> None:
        pytest.raises(BadFidFormat, self.seaweed.get_file_url, "a")

    def test_get_file(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        file_content = self.seaweed.get_file(fid)
        assert file_content is not None
        with open(__file__, "rb") as f:
            content = f.read()
        assert content == file_content
        res = self.seaweed.delete_file(fid)
        assert res

    def test_get_file_byte_range(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="range.bin")
        assert fid is not None
        assert self.seaweed.get_file(fid, byte_range=(0, 4)) == b"01234"
        assert self.seaweed.get_file(fid, byte_range=(5, None)) == b"56789"
        assert self.seaweed.delete_file(fid)

    def test_get_file_stream(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="stream.bin")
        assert fid is not None
        stream = self.seaweed.get_file_stream(fid, chunk_size=4)
        assert stream is not None
        assert b"".join(stream) == b"0123456789"
        assert self.seaweed.delete_file(fid)

    def test_get_file_location_collection(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"data"), name="col.bin")
        assert fid is not None
        loc = self.seaweed.get_file_location(fid.split(",")[0], collection="")
        assert loc is not None
        assert self.seaweed.get_file_location(fid.split(",")[0], collection="no-such-collection") is None
        assert self.seaweed.delete_file(fid)

    def test_submit_file(self) -> None:
        fid = self.seaweed.submit_file(stream=io.BytesIO(b"submit-data"), name="submit.bin")
        assert fid is not None
        assert self.seaweed.get_file(fid) == b"submit-data"
        assert self.seaweed.delete_file(fid)

    def test_admin_endpoints(self) -> None:
        assert self.seaweed.is_healthy()
        cluster = self.seaweed.cluster_status()
        assert cluster is not None
        assert "IsLeader" in cluster
        vol_status = self.seaweed.volume_status()
        assert vol_status is not None
        assert "Volumes" in vol_status
        assert not self.seaweed.delete_collection("no-such-collection")
        assert not self.seaweed.grow_volumes(1)

    def test_volume_server_status(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        status = self.seaweed.volume_server_status(fid)
        assert status is not None
        assert "Version" in status
        assert self.seaweed.delete_file(fid)

    def test_get_wrong_file(self) -> None:
        file_content = self.seaweed.get_file("3,123456790")
        assert file_content is None


class TestFunctionalSession:
    seaweed: SeaweedFS

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.seaweed = SeaweedFS(use_session=True)

    def test_head_file(self) -> None:
        _file = __file__
        fid = self.seaweed.upload_file(_file)
        assert fid is not None
        res = self.seaweed.get_file_size(fid)
        assert res is not None
        # Size is same or lower than file on disk
        assert res <= os.path.getsize(_file)
        res = self.seaweed.delete_file(fid)
        assert res
        res = self.seaweed.get_file_size("3,123456790")
        assert res is None

    def test_upload_delete(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        res = self.seaweed.delete_file(fid)
        assert res

    def test_version(self) -> None:
        ver = self.seaweed.version
        assert ver is not None

    def test_exists(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        assert self.seaweed.file_exists(fid)
        res = self.seaweed.delete_file(fid)
        assert res
        assert not self.seaweed.file_exists(fid)

    def test_upload_stream(self) -> None:
        with open(__file__, "rb") as stream:
            fid = self.seaweed.upload_file(stream=stream, name="test.py")
            assert fid is not None
        res = self.seaweed.delete_file(fid)
        assert res

    def test_vacuum(self) -> None:
        res = self.seaweed.vacuum()
        assert res

    def test_get_file_url_variants(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        url_public = self.seaweed.get_file_url(fid)
        url_internal = self.seaweed.get_file_url(fid, public=False)
        assert url_public is not None
        assert url_internal is not None
        assert url_public.endswith(fid)
        assert url_internal.endswith(fid)
        res = self.seaweed.delete_file(fid)
        assert res

    def test_get_file_location(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        loc = self.seaweed.get_file_location(fid.split(",")[0])
        assert loc is not None
        assert loc.url
        assert loc.public_url
        res = self.seaweed.delete_file(fid)
        assert res

    def test_upload_with_options(self) -> None:
        fid = self.seaweed.upload_file(
            __file__,
            name="custom_name.py",
            content_type="text/x-python",
            additional_headers={"X-Test-Header": "1"},
            count="2",
        )
        assert fid is not None
        assert self.seaweed.file_exists(fid)
        res = self.seaweed.delete_file(fid)
        assert res

    def test_internal_url_client(self) -> None:
        seaweed = SeaweedFS(use_public_url=False)
        fid = seaweed.upload_file(__file__)
        assert fid is not None
        assert seaweed.file_exists(fid)
        assert seaweed.delete_file(fid)

    def test_bad_fid(self) -> None:
        pytest.raises(BadFidFormat, self.seaweed.get_file_url, "a")

    def test_get_file(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        file_content = self.seaweed.get_file(fid)
        assert file_content is not None
        with open(__file__, "rb") as f:
            content = f.read()
        assert content == file_content
        res = self.seaweed.delete_file(fid)
        assert res

    def test_get_file_byte_range(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="range.bin")
        assert fid is not None
        assert self.seaweed.get_file(fid, byte_range=(0, 4)) == b"01234"
        assert self.seaweed.get_file(fid, byte_range=(5, None)) == b"56789"
        assert self.seaweed.delete_file(fid)

    def test_get_file_stream(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="stream.bin")
        assert fid is not None
        stream = self.seaweed.get_file_stream(fid, chunk_size=4)
        assert stream is not None
        assert b"".join(stream) == b"0123456789"
        assert self.seaweed.delete_file(fid)

    def test_get_file_location_collection(self) -> None:
        fid = self.seaweed.upload_file(stream=io.BytesIO(b"data"), name="col.bin")
        assert fid is not None
        loc = self.seaweed.get_file_location(fid.split(",")[0], collection="")
        assert loc is not None
        assert self.seaweed.get_file_location(fid.split(",")[0], collection="no-such-collection") is None
        assert self.seaweed.delete_file(fid)

    def test_submit_file(self) -> None:
        fid = self.seaweed.submit_file(stream=io.BytesIO(b"submit-data"), name="submit.bin")
        assert fid is not None
        assert self.seaweed.get_file(fid) == b"submit-data"
        assert self.seaweed.delete_file(fid)

    def test_admin_endpoints(self) -> None:
        assert self.seaweed.is_healthy()
        cluster = self.seaweed.cluster_status()
        assert cluster is not None
        assert "IsLeader" in cluster
        vol_status = self.seaweed.volume_status()
        assert vol_status is not None
        assert "Volumes" in vol_status
        assert not self.seaweed.delete_collection("no-such-collection")
        assert not self.seaweed.grow_volumes(1)

    def test_volume_server_status(self) -> None:
        fid = self.seaweed.upload_file(__file__)
        assert fid is not None
        status = self.seaweed.volume_server_status(fid)
        assert status is not None
        assert "Version" in status
        assert self.seaweed.delete_file(fid)

    def test_get_wrong_file(self) -> None:
        file_content = self.seaweed.get_file("3,123456790")
        assert file_content is None
