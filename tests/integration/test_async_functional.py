import io
import os
from collections.abc import AsyncGenerator

import pytest

from pyseaweed.async_client import AsyncSeaweedFS
from pyseaweed.exceptions import BadFidFormat

pytestmark = pytest.mark.integration


class TestAsyncFunctional:
    seaweed: AsyncSeaweedFS

    @pytest.fixture(autouse=True)
    async def _setup(self) -> AsyncGenerator[None]:
        self.seaweed = AsyncSeaweedFS()
        yield
        await self.seaweed.close()

    async def test_upload_get_delete(self) -> None:
        fid = await self.seaweed.upload_file(__file__)
        assert fid is not None
        file_content = await self.seaweed.get_file(fid)
        assert file_content is not None
        with open(__file__, "rb") as f:
            assert f.read() == file_content
        assert await self.seaweed.delete_file(fid)

    async def test_upload_stream(self) -> None:
        fid = await self.seaweed.upload_file(stream=io.BytesIO(b"async-data"), name="test.bin")
        assert fid is not None
        assert await self.seaweed.get_file(fid) == b"async-data"
        assert await self.seaweed.delete_file(fid)

    async def test_submit_file(self) -> None:
        fid = await self.seaweed.submit_file(stream=io.BytesIO(b"submit-data"), name="submit.bin")
        assert fid is not None
        assert await self.seaweed.get_file(fid) == b"submit-data"
        assert await self.seaweed.delete_file(fid)

    async def test_head_and_exists(self) -> None:
        fid = await self.seaweed.upload_file(__file__)
        assert fid is not None
        size = await self.seaweed.get_file_size(fid)
        assert size is not None
        assert size <= os.path.getsize(__file__)
        assert await self.seaweed.file_exists(fid)
        assert await self.seaweed.delete_file(fid)
        assert not await self.seaweed.file_exists(fid)
        assert await self.seaweed.get_file_size("3,123456790") is None

    async def test_get_file_byte_range(self) -> None:
        fid = await self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="range.bin")
        assert fid is not None
        assert await self.seaweed.get_file(fid, byte_range=(0, 4)) == b"01234"
        assert await self.seaweed.get_file(fid, byte_range=(5, None)) == b"56789"
        assert await self.seaweed.delete_file(fid)

    async def test_get_file_stream(self) -> None:
        fid = await self.seaweed.upload_file(stream=io.BytesIO(b"0123456789"), name="stream.bin")
        assert fid is not None
        stream = await self.seaweed.get_file_stream(fid, chunk_size=4)
        assert stream is not None
        chunks = [c async for c in stream]
        assert b"".join(chunks) == b"0123456789"
        assert await self.seaweed.delete_file(fid)

    async def test_get_file_url_variants(self) -> None:
        fid = await self.seaweed.upload_file(__file__)
        assert fid is not None
        url_public = await self.seaweed.get_file_url(fid)
        url_internal = await self.seaweed.get_file_url(fid, public=False)
        assert url_public is not None and url_public.endswith(fid)
        assert url_internal is not None and url_internal.endswith(fid)
        assert await self.seaweed.delete_file(fid)

    async def test_get_file_location(self) -> None:
        fid = await self.seaweed.upload_file(__file__)
        assert fid is not None
        loc = await self.seaweed.get_file_location(fid.split(",")[0])
        assert loc is not None
        assert loc.url and loc.public_url
        assert await self.seaweed.delete_file(fid)

    async def test_version(self) -> None:
        assert await self.seaweed.version() is not None

    async def test_vacuum(self) -> None:
        assert await self.seaweed.vacuum()

    async def test_bad_fid(self) -> None:
        with pytest.raises(BadFidFormat):
            await self.seaweed.get_file_url("a")

    async def test_admin_endpoints(self) -> None:
        assert await self.seaweed.is_healthy()
        cluster = await self.seaweed.cluster_status()
        assert cluster is not None and "IsLeader" in cluster
        vol_status = await self.seaweed.volume_status()
        assert vol_status is not None and "Volumes" in vol_status
        assert not await self.seaweed.delete_collection("no-such-collection")
        assert not await self.seaweed.grow_volumes(1)

    async def test_volume_server_status(self) -> None:
        fid = await self.seaweed.upload_file(__file__)
        assert fid is not None
        status = await self.seaweed.volume_server_status(fid)
        assert status is not None and "Version" in status
        assert await self.seaweed.delete_file(fid)

    async def test_get_wrong_file(self) -> None:
        assert await self.seaweed.get_file("3,123456790") is None

    async def test_context_manager(self) -> None:
        async with AsyncSeaweedFS() as seaweed:
            fid = await seaweed.upload_file(stream=io.BytesIO(b"ctx"), name="ctx.bin")
            assert fid is not None
            assert await seaweed.delete_file(fid)

    async def test_internal_url_client(self) -> None:
        async with AsyncSeaweedFS(use_public_url=False) as seaweed:
            fid = await seaweed.upload_file(__file__)
            assert fid is not None
            assert await seaweed.file_exists(fid)
            assert await seaweed.delete_file(fid)
