"""Async client for the SeaweedFS Filer HTTP API.

Async variant of :class:`pyseaweed.filer.Filer` based on httpx.
Requires the ``async`` extra::

    pip install pyseaweed[async]

"""

import base64
import json
from collections.abc import AsyncIterator, Iterable
from typing import Any, BinaryIO, Self
from urllib.parse import urlencode

import httpx

from pyseaweed._common import TAG_PREFIX, canonical_tag_name, prepare_stream, range_headers
from pyseaweed.async_client import AsyncConnection


class AsyncFiler:
    """Async client for the SeaweedFS Filer HTTP API (path-based access)."""

    def __init__(
        self,
        filer_addr: str = "localhost",
        filer_port: int = 8888,
        timeout: float | None = None,
        retries: int = 0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Create an AsyncFiler instance.

        Args:
            filer_addr: Address of the SeaweedFS filer server
                (default: localhost).
            filer_port: SeaweedFS filer port (default: 8888).
            timeout: Default request timeout in seconds (default: None,
                i.e. no timeout).
            retries: Number of retries for transient server errors
                (default: 0).
            client: Optional pre-configured ``httpx.AsyncClient`` to use
                instead of creating one.

        Returns:
            AsyncFiler instance.

        """
        self.filer_addr = filer_addr
        self.filer_port = filer_port
        self.conn = AsyncConnection(timeout=timeout, retries=retries, client=client)

    async def close(self) -> None:
        """Close the underlying http client."""
        await self.conn.close()

    async def __aenter__(self) -> Self:
        """Return self for async context manager usage."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Close the http client on context manager exit."""
        await self.close()

    def __repr__(self) -> str:
        """Return string representation of the instance."""
        return f"<{self.__class__.__name__} {self.filer_addr}:{self.filer_port}>"

    def _url(self, path: str, params: dict[str, str] | None = None) -> str:
        """Build a filer url for the given remote path."""
        if not path.startswith("/"):
            path = "/" + path
        url = f"http://{self.filer_addr}:{self.filer_port}{path}"
        if params:
            url += f"?{urlencode(params)}"
        return url

    async def upload_file(
        self,
        remote_path: str,
        path: str | None = None,
        stream: BinaryIO | None = None,
        name: str | None = None,
        additional_headers: dict[str, str] | None = None,
        content_type: str | None = None,
        **kwargs: str,
    ) -> dict[str, Any] | None:
        """Upload a file to the filer under ``remote_path``.

        Args:
            remote_path: Destination path on the filer, e.g.
                ``/docs/report.pdf``. Intermediate directories are
                created automatically.
            path: Path to the local file to upload.
            stream: File-like object to upload.
            name: Name of the uploaded file in the multipart request.
            additional_headers: Additional headers for the upload request.
            content_type: Content type of the uploaded file.
            **kwargs: Extra parameters forwarded to the filer
                (e.g. ``collection``, ``replication``, ``ttl``, ``mode``).

        Returns:
            The filer response dict (``name``, ``size``, ``eTag``, ...)
            or None if the upload request failed.

        Raises:
            ValueError: If ``path`` is None and not both ``stream`` and
                ``name`` are provided.
            RuntimeError: If the filer rejects the upload.

        """
        filename, file_stream, close_stream = prepare_stream(path, stream, name)
        try:
            res = await self.conn.post_file(
                self._url(remote_path, kwargs or None), filename, file_stream, additional_headers=additional_headers, content_type=content_type
            )
        finally:
            if close_stream:
                file_stream.close()

        if res is None:
            return None
        try:
            data = json.loads(res)
        except ValueError:
            data = {}
        if isinstance(data, dict) and "size" in data:
            return data
        raise RuntimeError(f"Upload failed: {data}")

    async def download_file(
        self,
        remote_path: str,
        byte_range: tuple[int | None, int | None] | None = None,
        params: dict[str, str] | None = None,
    ) -> bytes | None:
        """Download a file from the filer.

        Args:
            remote_path: Path of the file on the filer.
            byte_range: Optional ``(start, end)`` tuple for a HTTP range
                request. Either bound may be None to leave it open.
            params: Optional query parameters for the request.

        Returns:
            File content as bytes or None if the file doesn't exist.

        """
        return await self.conn.get_raw_data(self._url(remote_path, params), additional_headers=range_headers(byte_range))

    async def get_file_stream(
        self,
        remote_path: str,
        byte_range: tuple[int | None, int | None] | None = None,
        params: dict[str, str] | None = None,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes]:
        """Download a file from the filer as an async stream of chunks.

        Args:
            remote_path: Path of the file on the filer.
            byte_range: Optional ``(start, end)`` tuple for a HTTP range
                request. Either bound may be None to leave it open.
            params: Optional query parameters for the request.
            chunk_size: Size of the chunks yielded by the iterator.

        Returns:
            Async iterator of file chunks. The iterator is empty if the
            file doesn't exist or the request fails.

        """
        return self.conn.get_stream(self._url(remote_path, params), additional_headers=range_headers(byte_range), chunk_size=chunk_size)

    async def exists(self, remote_path: str) -> bool:
        """Check whether a file or directory exists on the filer.

        Args:
            remote_path: Path to check.

        Returns:
            True if the path exists. False otherwise.

        """
        return await self.conn.head(self._url(remote_path)) is not None

    async def stat(self, remote_path: str) -> dict[str, Any] | None:
        """Get metadata for a file or directory.

        Args:
            remote_path: Path of the file or directory.

        Returns:
            Entry metadata dict (``FullPath``, ``Mtime``, ``FileSize``,
            ``chunks``, ``Extended``, ...) or None if the path doesn't
            exist.

        """
        res = await self.conn.get_data(self._url(remote_path, {"metadata": "true"}))
        try:
            data = json.loads(res) if res else None
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def list_dir(
        self,
        dir_path: str,
        limit: int | None = None,
        last_file_name: str | None = None,
    ) -> dict[str, Any] | None:
        """List the entries of a directory.

        Args:
            dir_path: Path of the directory to list.
            limit: Maximum number of entries to return.
            last_file_name: Name of the last entry from the previous page,
                for pagination. Repeat with the returned ``LastFileName``
                while ``ShouldDisplayLoadMore`` is true.

        Returns:
            Listing dict (``Path``, ``Entries``, ``LastFileName``,
            ``ShouldDisplayLoadMore``, ...) or None if the directory
            can't be listed.

        """
        params: dict[str, str] = {}
        if limit is not None:
            params["limit"] = str(limit)
        if last_file_name is not None:
            params["lastFileName"] = last_file_name
        path = dir_path.rstrip("/") + "/"
        res = await self.conn.get_data(self._url(path, params or None), additional_headers={"Accept": "application/json"})
        try:
            data = json.loads(res) if res else None
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def mkdir(self, dir_path: str) -> bool:
        """Create a directory, including missing parents.

        Args:
            dir_path: Path of the directory to create.

        Returns:
            True if the directory was created. False otherwise.

        """
        return await self.conn.post(self._url(dir_path.rstrip("/") + "/", {"mode": "mkdir"}))

    async def move(self, src_path: str, dst_path: str) -> bool:
        """Move or rename a file or directory.

        Args:
            src_path: Current path of the file or directory.
            dst_path: New path.

        Returns:
            True if the entry was moved. False otherwise.

        """
        return await self.conn.post(self._url(dst_path, {"mv.from": src_path}))

    async def delete(
        self,
        remote_path: str,
        recursive: bool = False,
        ignore_recursive_error: bool = False,
    ) -> bool:
        """Delete a file or directory.

        Args:
            remote_path: Path to delete.
            recursive: Also delete the contents of a directory.
            ignore_recursive_error: Don't fail the recursive delete on
                individual entry errors.

        Returns:
            True if the entry was deleted. False otherwise. Deleting a
            non-existent path also returns True (the filer answers 204).

        """
        params: dict[str, str] = {}
        if recursive:
            params["recursive"] = "true"
        if ignore_recursive_error:
            params["ignoreRecursiveError"] = "true"
        return await self.conn.delete_data(self._url(remote_path, params or None))

    async def set_tags(self, remote_path: str, tags: dict[str, str]) -> bool:
        """Set or replace extended attributes (tags) on a file.

        Tag names are stored in canonical header form, e.g. ``color``
        is stored as ``Color``. Tag values may be arbitrary strings.

        Args:
            remote_path: Path of the file.
            tags: Mapping of tag names to tag values.

        Returns:
            True if the tags were stored. False otherwise.

        """
        headers = {f"{TAG_PREFIX}{name}": str(value) for name, value in tags.items()}
        return await self.conn.put(self._url(remote_path, {"tagging": ""}), additional_headers=headers)

    async def get_tags(self, remote_path: str) -> dict[str, str] | None:
        """Get the extended attributes (tags) of a file.

        Tag names are returned in canonical header form (e.g.
        ``Color``, ``My-Tag``).

        Args:
            remote_path: Path of the file.

        Returns:
            Mapping of tag names to decoded tag values or None if the
            path doesn't exist.

        """
        meta = await self.stat(remote_path)
        if meta is None:
            return None
        extended = meta.get("Extended")
        if not isinstance(extended, dict):
            return {}
        tags = {}
        for key, value in extended.items():
            if key.startswith(TAG_PREFIX):
                try:
                    tags[key[len(TAG_PREFIX) :]] = base64.b64decode(value).decode()
                except ValueError:
                    tags[key[len(TAG_PREFIX) :]] = value
        return tags

    async def delete_tags(self, remote_path: str, names: Iterable[str] | None = None) -> bool:
        """Delete extended attributes (tags) from a file.

        Args:
            remote_path: Path of the file.
            names: Tag names to delete. Names are canonicalized like the
                server does, so ``color`` matches the stored ``Color``
                tag. If None, all tags are deleted. An empty iterable
                deletes nothing and is a no-op.

        Returns:
            True if the tags were deleted. False otherwise.

        """
        if names is not None:
            names = list(names)
            if not names:
                return True
        tagging = "" if names is None else ",".join(canonical_tag_name(name) for name in names)
        return await self.conn.delete_data(self._url(remote_path, {"tagging": tagging}))
