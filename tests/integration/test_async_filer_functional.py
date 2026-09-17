import io
import uuid
from collections.abc import AsyncGenerator

import pytest

from pyseaweed.async_filer import AsyncFiler

pytestmark = pytest.mark.integration


@pytest.fixture()
def base() -> str:
    """Unique test directory per test."""
    return f"/test-async-{uuid.uuid4().hex[:12]}"


@pytest.fixture()
async def filer() -> AsyncGenerator[AsyncFiler]:
    f = AsyncFiler()
    yield f
    await f.close()


class TestAsyncFilerFunctional:
    async def test_upload_download_delete(self, filer: AsyncFiler, base: str) -> None:
        res = await filer.upload_file(f"{base}/report.txt", __file__)
        assert res is not None
        assert res["size"] > 0

        content = await filer.download_file(f"{base}/report.txt")
        assert content is not None
        with open(__file__, "rb") as f:
            assert content == f.read()

        assert await filer.delete(f"{base}/report.txt")
        assert not await filer.exists(f"{base}/report.txt")
        assert await filer.delete(base, recursive=True)

    async def test_upload_stream(self, filer: AsyncFiler, base: str) -> None:
        res = await filer.upload_file(f"{base}/data.bin", stream=io.BytesIO(b"async-filer-data"), name="data.bin")
        assert res is not None
        assert await filer.download_file(f"{base}/data.bin") == b"async-filer-data"
        assert await filer.delete(base, recursive=True)

    async def test_byte_range(self, filer: AsyncFiler, base: str) -> None:
        await filer.upload_file(f"{base}/range.bin", stream=io.BytesIO(b"0123456789"), name="range.bin")
        assert await filer.download_file(f"{base}/range.bin", byte_range=(0, 4)) == b"01234"
        assert await filer.download_file(f"{base}/range.bin", byte_range=(5, None)) == b"56789"
        assert await filer.delete(base, recursive=True)

    async def test_get_file_stream(self, filer: AsyncFiler, base: str) -> None:
        await filer.upload_file(f"{base}/stream.bin", stream=io.BytesIO(b"0123456789"), name="stream.bin")
        stream = await filer.get_file_stream(f"{base}/stream.bin", chunk_size=4)
        chunks = [c async for c in stream]
        assert b"".join(chunks) == b"0123456789"
        assert await filer.delete(base, recursive=True)

    async def test_exists(self, filer: AsyncFiler, base: str) -> None:
        assert not await filer.exists(f"{base}/nope.txt")
        await filer.upload_file(f"{base}/exists.txt", stream=io.BytesIO(b"x"), name="exists.txt")
        assert await filer.exists(f"{base}/exists.txt")
        assert await filer.delete(base, recursive=True)

    async def test_mkdir_and_list(self, filer: AsyncFiler, base: str) -> None:
        assert await filer.mkdir(f"{base}/sub/dir")
        assert await filer.exists(f"{base}/sub")

        await filer.upload_file(f"{base}/sub/dir/a.txt", stream=io.BytesIO(b"a"), name="a.txt")
        await filer.upload_file(f"{base}/sub/dir/b.txt", stream=io.BytesIO(b"b"), name="b.txt")

        listing = await filer.list_dir(f"{base}/sub/dir")
        assert listing is not None
        names = {e["FullPath"].rsplit("/", 1)[-1] for e in listing["Entries"]}
        assert names == {"a.txt", "b.txt"}

        paged = await filer.list_dir(f"{base}/sub/dir", limit=1)
        assert paged is not None
        assert len(paged["Entries"]) == 1
        assert paged["ShouldDisplayLoadMore"] is True
        page2 = await filer.list_dir(f"{base}/sub/dir", limit=1, last_file_name=paged["LastFileName"])
        assert page2 is not None
        assert len(page2["Entries"]) == 1

        assert await filer.list_dir(f"{base}/no-such-dir") is None
        assert await filer.delete(base, recursive=True)

    async def test_stat(self, filer: AsyncFiler, base: str) -> None:
        await filer.upload_file(f"{base}/meta.txt", stream=io.BytesIO(b"meta"), name="meta.txt")
        meta = await filer.stat(f"{base}/meta.txt")
        assert meta is not None
        assert meta["FullPath"].endswith("meta.txt")
        assert await filer.stat(f"{base}/missing.txt") is None
        assert await filer.delete(base, recursive=True)

    async def test_move(self, filer: AsyncFiler, base: str) -> None:
        await filer.upload_file(f"{base}/old.txt", stream=io.BytesIO(b"move me"), name="old.txt")
        assert await filer.move(f"{base}/old.txt", f"{base}/new.txt")
        assert not await filer.exists(f"{base}/old.txt")
        assert await filer.download_file(f"{base}/new.txt") == b"move me"
        assert await filer.delete(base, recursive=True)

    async def test_tags(self, filer: AsyncFiler, base: str) -> None:
        await filer.upload_file(f"{base}/tagged.txt", stream=io.BytesIO(b"tagged"), name="tagged.txt")

        assert await filer.set_tags(f"{base}/tagged.txt", {"color": "red", "size": "large"})
        tags = await filer.get_tags(f"{base}/tagged.txt")
        assert tags == {"Color": "red", "Size": "large"}

        assert await filer.delete_tags(f"{base}/tagged.txt", ["color"])
        tags = await filer.get_tags(f"{base}/tagged.txt")
        assert tags == {"Size": "large"}

        assert await filer.delete_tags(f"{base}/tagged.txt")
        assert await filer.get_tags(f"{base}/tagged.txt") == {}

        assert await filer.get_tags(f"{base}/missing.txt") is None
        assert await filer.delete(base, recursive=True)

    async def test_delete_nonempty_dir_requires_recursive(self, filer: AsyncFiler, base: str) -> None:
        await filer.upload_file(f"{base}/inner.txt", stream=io.BytesIO(b"x"), name="inner.txt")
        assert not await filer.delete(base)
        assert await filer.delete(base, recursive=True)
        assert not await filer.exists(f"{base}/inner.txt")

    async def test_context_manager(self) -> None:
        async with AsyncFiler() as filer:
            assert await filer.exists("/")
