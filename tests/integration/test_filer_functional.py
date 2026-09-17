import io
import uuid
from collections.abc import Iterator

import pytest

from pyseaweed.filer import Filer

pytestmark = pytest.mark.integration


@pytest.fixture()
def base() -> str:
    """Unique test directory per test."""
    return f"/test-{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def filer() -> Iterator[Filer]:
    f = Filer()
    yield f
    f.close()


class TestFilerFunctional:
    def test_upload_download_delete(self, filer: Filer, base: str) -> None:
        res = filer.upload_file(f"{base}/report.txt", __file__)
        assert res is not None
        assert res["size"] > 0

        content = filer.download_file(f"{base}/report.txt")
        assert content is not None
        with open(__file__, "rb") as f:
            assert content == f.read()

        assert filer.delete(f"{base}/report.txt")
        assert not filer.exists(f"{base}/report.txt")
        assert filer.delete(base, recursive=True)

    def test_upload_stream(self, filer: Filer, base: str) -> None:
        res = filer.upload_file(f"{base}/data.bin", stream=io.BytesIO(b"filer-data"), name="data.bin")
        assert res is not None
        assert filer.download_file(f"{base}/data.bin") == b"filer-data"
        assert filer.delete(base, recursive=True)

    def test_byte_range(self, filer: Filer, base: str) -> None:
        filer.upload_file(f"{base}/range.bin", stream=io.BytesIO(b"0123456789"), name="range.bin")
        assert filer.download_file(f"{base}/range.bin", byte_range=(0, 4)) == b"01234"
        assert filer.download_file(f"{base}/range.bin", byte_range=(5, None)) == b"56789"
        assert filer.delete(base, recursive=True)

    def test_get_file_stream(self, filer: Filer, base: str) -> None:
        filer.upload_file(f"{base}/stream.bin", stream=io.BytesIO(b"0123456789"), name="stream.bin")
        stream = filer.get_file_stream(f"{base}/stream.bin", chunk_size=4)
        assert stream is not None
        assert b"".join(stream) == b"0123456789"
        assert filer.delete(base, recursive=True)

    def test_exists(self, filer: Filer, base: str) -> None:
        assert not filer.exists(f"{base}/nope.txt")
        filer.upload_file(f"{base}/exists.txt", stream=io.BytesIO(b"x"), name="exists.txt")
        assert filer.exists(f"{base}/exists.txt")
        assert filer.delete(base, recursive=True)

    def test_mkdir_and_list(self, filer: Filer, base: str) -> None:
        assert filer.mkdir(f"{base}/sub/dir")
        assert filer.exists(f"{base}/sub")

        filer.upload_file(f"{base}/sub/dir/a.txt", stream=io.BytesIO(b"a"), name="a.txt")
        filer.upload_file(f"{base}/sub/dir/b.txt", stream=io.BytesIO(b"b"), name="b.txt")

        listing = filer.list_dir(f"{base}/sub/dir")
        assert listing is not None
        names = {e["FullPath"].rsplit("/", 1)[-1] for e in listing["Entries"]}
        assert names == {"a.txt", "b.txt"}

        paged = filer.list_dir(f"{base}/sub/dir", limit=1)
        assert paged is not None
        assert len(paged["Entries"]) == 1
        assert paged["ShouldDisplayLoadMore"] is True
        page2 = filer.list_dir(f"{base}/sub/dir", limit=1, last_file_name=paged["LastFileName"])
        assert page2 is not None
        assert len(page2["Entries"]) == 1
        assert page2["Entries"][0]["FullPath"] != paged["Entries"][0]["FullPath"]

        assert filer.list_dir(f"{base}/no-such-dir") is None
        assert filer.delete(base, recursive=True)

    def test_stat(self, filer: Filer, base: str) -> None:
        filer.upload_file(f"{base}/meta.txt", stream=io.BytesIO(b"meta"), name="meta.txt")
        meta = filer.stat(f"{base}/meta.txt")
        assert meta is not None
        assert meta["FullPath"].endswith("meta.txt")
        assert filer.stat(f"{base}/missing.txt") is None
        assert filer.delete(base, recursive=True)

    def test_move(self, filer: Filer, base: str) -> None:
        filer.upload_file(f"{base}/old.txt", stream=io.BytesIO(b"move me"), name="old.txt")
        assert filer.move(f"{base}/old.txt", f"{base}/new.txt")
        assert not filer.exists(f"{base}/old.txt")
        assert filer.download_file(f"{base}/new.txt") == b"move me"
        assert filer.delete(base, recursive=True)

    def test_tags(self, filer: Filer, base: str) -> None:
        filer.upload_file(f"{base}/tagged.txt", stream=io.BytesIO(b"tagged"), name="tagged.txt")

        assert filer.set_tags(f"{base}/tagged.txt", {"color": "red", "size": "large"})
        tags = filer.get_tags(f"{base}/tagged.txt")
        assert tags == {"Color": "red", "Size": "large"}

        assert filer.delete_tags(f"{base}/tagged.txt", ["color"])
        tags = filer.get_tags(f"{base}/tagged.txt")
        assert tags == {"Size": "large"}

        assert filer.delete_tags(f"{base}/tagged.txt")
        assert filer.get_tags(f"{base}/tagged.txt") == {}

        assert filer.get_tags(f"{base}/missing.txt") is None
        assert filer.delete(base, recursive=True)

    def test_delete_nonempty_dir_requires_recursive(self, filer: Filer, base: str) -> None:
        filer.upload_file(f"{base}/inner.txt", stream=io.BytesIO(b"x"), name="inner.txt")
        assert not filer.delete(base)
        assert filer.delete(base, recursive=True)
        assert not filer.exists(f"{base}/inner.txt")

    def test_context_manager(self) -> None:
        with Filer() as filer:
            assert filer.exists("/")
