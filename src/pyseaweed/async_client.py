"""Async client for SeaweedFS based on httpx.

Requires the ``async`` extra::

    pip install pyseaweed[async]

"""

import asyncio
import json
import random
from collections.abc import AsyncIterator
from typing import Any, BinaryIO, Self
from urllib.parse import urlencode

import httpx

from pyseaweed._common import FID_PATTERN, prepare_headers, prepare_stream, range_headers
from pyseaweed.exceptions import BadFidFormat
from pyseaweed.seaweed import FileLocation

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "DELETE", "OPTIONS", "PUT", "TRACE"})
_BACKOFF_FACTOR = 0.3


class AsyncConnection:
    """Handle async http communication with SeaweedFS."""

    def __init__(
        self,
        timeout: float | None = None,
        retries: int = 0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Create an AsyncConnection instance.

        Args:
            timeout: Default request timeout in seconds. Applied to every
                request unless overridden per call (default: None, i.e. no
                timeout).
            retries: Number of retries for failed requests with transient
                server errors (500, 502, 503, 504). Only idempotent HTTP
                methods are retried (default: 0, i.e. no retries).
            client: Optional pre-configured ``httpx.AsyncClient`` to use
                instead of creating one.

        """
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout)
        self.timeout = timeout
        self.retries = retries

    async def close(self) -> None:
        """Close the underlying http client."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Return self for async context manager usage."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Close the http client on context manager exit."""
        await self.close()

    def _timeout(self, timeout: float | None) -> float | None:
        """Return the effective request timeout."""
        return timeout if timeout is not None else self.timeout

    async def _request(
        self,
        method: str,
        url: str,
        timeout: float | None = None,
        additional_headers: dict[str, str] | None = None,
        files: dict[str, tuple[str, BinaryIO] | tuple[str, BinaryIO, str]] | None = None,
    ) -> httpx.Response | None:
        """Send a request, retrying idempotent methods on transient errors.

        Returns:
            Response object or None if the request failed.

        """
        attempts = self.retries + 1 if method in _IDEMPOTENT_METHODS else 1
        res: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                res = await self._client.request(
                    method,
                    url,
                    headers=prepare_headers(additional_headers),
                    timeout=self._timeout(timeout),
                    files=files,
                )
            except httpx.HTTPError:
                res = None
            else:
                if res.status_code not in _RETRYABLE_STATUS:
                    return res
            if attempt + 1 < attempts:
                await asyncio.sleep(_BACKOFF_FACTOR * (2**attempt))
        return res

    async def head(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> httpx.Response | None:
        """Return response to http HEAD on provided url.

        Args:
            url: Address of the wanted data.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Response object or None if the request failed.

        """
        res = await self._request("HEAD", url, timeout=timeout, additional_headers=additional_headers)
        if res is not None and 200 <= res.status_code < 300:
            return res
        return None

    async def get_data(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> str | None:
        """Get data from url as text.

        Return content under the provided url as text.

        Args:
            url: Address of the wanted data.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Response body as string or None if the request failed.

        """
        res = await self._request("GET", url, timeout=timeout, additional_headers=additional_headers)
        if res is not None and 200 <= res.status_code < 300:
            return res.text
        return None

    async def get_raw_data(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> bytes | None:
        """Get data from url as bytes.

        Return content under the provided url as bytes
        ie. for binary data.

        Args:
            url: Address of the wanted data.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Response body as bytes or None if the request failed.

        """
        res = await self._request("GET", url, timeout=timeout, additional_headers=additional_headers)
        if res is not None and 200 <= res.status_code < 300:
            return res.content
        return None

    def get_stream(
        self,
        url: str,
        timeout: float | None = None,
        additional_headers: dict[str, str] | None = None,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes]:
        """Get data from url as an async iterator of byte chunks.

        Return a chunk iterator over the content of the provided url
        without loading the whole response body into memory.

        Args:
            url: Address of the wanted data.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.
            chunk_size: Size of the chunks yielded by the iterator.

        Returns:
            Async iterator of response chunks. The iterator is empty if
            the request fails or the response status is not 2xx.

        """
        return self._aiter_stream(url, timeout=timeout, additional_headers=additional_headers, chunk_size=chunk_size)

    async def _aiter_stream(
        self,
        url: str,
        timeout: float | None = None,
        additional_headers: dict[str, str] | None = None,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes]:
        """Yield response chunks, retrying the request on transient errors."""
        attempts = self.retries + 1
        yielded = False
        for attempt in range(attempts):
            try:
                async with self._client.stream(
                    "GET",
                    url,
                    headers=prepare_headers(additional_headers),
                    timeout=self._timeout(timeout),
                ) as res:
                    if 200 <= res.status_code < 300:
                        async for chunk in res.aiter_bytes(chunk_size):
                            yielded = True
                            yield chunk
                        return
                    if res.status_code not in _RETRYABLE_STATUS:
                        return
            except httpx.HTTPError:
                # Once bytes reached the consumer a retry would replay the
                # body from byte 0 and corrupt the output — propagate instead.
                if yielded:
                    raise
            if attempt + 1 < attempts:
                await asyncio.sleep(_BACKOFF_FACTOR * (2**attempt))

    async def post_file(
        self,
        url: str,
        filename: str,
        file_stream: BinaryIO,
        content_type: str | None = None,
        timeout: float | None = None,
        additional_headers: dict[str, str] | None = None,
    ) -> str | None:
        """Upload file to provided url.

        Args:
            url: Address where to upload file.
            filename: Name of the uploaded file.
            file_stream: File like object to upload.
            content_type: Content type of the file.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Response body as string or None if the request failed.

        """
        res = await self._request(
            "POST",
            url,
            files={"file": (filename, file_stream) if content_type is None else (filename, file_stream, content_type)},
            timeout=timeout,
            additional_headers=additional_headers,
        )

        if res is not None and 200 <= res.status_code < 300:
            return res.text
        return None

    async def post(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> bool:
        """Send an empty POST request to the provided url.

        Args:
            url: Address to post to.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Boolean. True if request was successful. False if not.

        """
        res = await self._request("POST", url, timeout=timeout, additional_headers=additional_headers)
        return res is not None and 200 <= res.status_code < 300

    async def put(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> bool:
        """Send an empty PUT request to the provided url.

        Args:
            url: Address to put to.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Boolean. True if request was successful. False if not.

        """
        res = await self._request("PUT", url, timeout=timeout, additional_headers=additional_headers)
        return res is not None and 200 <= res.status_code < 300

    async def delete_data(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> bool:
        """Delete data under provided url.

        Args:
            url: Address of file to be deleted.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Boolean. True if request was successful. False if not.

        """
        res = await self._request("DELETE", url, timeout=timeout, additional_headers=additional_headers)
        return res is not None and 200 <= res.status_code < 300


class AsyncSeaweedFS:
    """Async client for the SeaweedFS HTTP API."""

    def __init__(
        self,
        master_addr: str = "localhost",
        master_port: int = 9333,
        use_public_url: bool = True,
        timeout: float | None = None,
        retries: int = 0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Create an AsyncSeaweedFS instance.

        Args:
            master_addr: Address of SeaweedFS master server
                (default: localhost).
            master_port: SeaweedFS master server port (default: 9333).
            use_public_url: If ``True``, all the requests will use
                ``publicUrl`` link instead of ``url``.
            timeout: Default request timeout in seconds (default: None,
                i.e. no timeout).
            retries: Number of retries for transient server errors
                (default: 0).
            client: Optional pre-configured ``httpx.AsyncClient`` to use
                instead of creating one.

        Returns:
            AsyncSeaweedFS instance.

        """
        self.master_addr = master_addr
        self.master_port = master_port
        self.conn = AsyncConnection(timeout=timeout, retries=retries, client=client)
        self.use_public_url = use_public_url

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
        return f"<{self.__class__.__name__} {self.master_addr}:{self.master_port}>"

    async def get_file(
        self,
        fid: str,
        byte_range: tuple[int | None, int | None] | None = None,
        params: dict[str, str] | None = None,
        collection: str | None = None,
    ) -> bytes | None:
        """Get file from SeaweedFS.

        Return file content. May be problematic for large files as content is
        stored in memory. Use ``get_file_stream`` for large files or
        ``byte_range`` for partial reads.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            byte_range: Optional ``(start, end)`` tuple for a HTTP range
                request. Either bound may be None to leave it open.
            params: Optional query parameters for the volume request
                (e.g. ``width``/``height``/``mode`` for image resizing or
                ``readDeleted`` to read deleted files).
            collection: Optional collection name to speed up the volume
                lookup on the master.

        Returns:
            Content of the file with provided fid or None if file doesn't
            exist on the server.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = await self.get_file_url(fid, params=params, collection=collection)
        if url is None:
            return None
        return await self.conn.get_raw_data(url, additional_headers=range_headers(byte_range))

    async def get_file_stream(
        self,
        fid: str,
        byte_range: tuple[int | None, int | None] | None = None,
        params: dict[str, str] | None = None,
        collection: str | None = None,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes] | None:
        """Get file from SeaweedFS as an async stream of chunks.

        Unlike ``get_file`` this does not load the whole file into memory.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            byte_range: Optional ``(start, end)`` tuple for a HTTP range
                request. Either bound may be None to leave it open.
            params: Optional query parameters for the volume request.
            collection: Optional collection name to speed up the volume
                lookup on the master.
            chunk_size: Size of the chunks yielded by the iterator.

        Returns:
            Async iterator of file chunks or None if the volume can't be
            located. A failed request yields an empty iterator.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = await self.get_file_url(fid, params=params, collection=collection)
        if url is None:
            return None
        return self.conn.get_stream(url, additional_headers=range_headers(byte_range), chunk_size=chunk_size)

    async def get_file_url(
        self,
        fid: str,
        public: bool | None = None,
        params: dict[str, str] | None = None,
        collection: str | None = None,
    ) -> str | None:
        """Get url for the file.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            public: Use the public or the internal url. Defaults to the
                ``use_public_url`` setting of this instance.
            params: Optional query parameters appended to the file url
                (e.g. ``width``/``height``/``mode``/crop parameters for
                server-side image resizing or ``readDeleted``).
            collection: Optional collection name to speed up the volume
                lookup on the master.

        Returns:
            File url as string or None if the volume can't be located.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        fid = fid.strip()
        match = FID_PATTERN.match(fid)
        if match is None:
            raise BadFidFormat("fid must be in format: <volume_id>,<file_name_hash>")
        volume_id = match.group(1)
        file_location = await self.get_file_location(volume_id, collection=collection)
        if file_location is None:
            return None
        if public is None:
            public = self.use_public_url
        volume_url = file_location.public_url if public else file_location.url
        url = f"http://{volume_url}/{fid}"
        if params:
            url += f"?{urlencode(params)}"
        return url

    async def get_file_location(self, volume_id: str, collection: str | None = None) -> FileLocation | None:
        """Get location for the file.

        SeaweedFS volume is chosen randomly.

        Args:
            volume_id: Volume id.
            collection: Optional collection name. Providing it speeds
                up the lookup on the master.

        Returns:
            ``FileLocation`` namedtuple or None if the volume
            can't be located.

        """
        query: dict[str, str] = {"volumeId": volume_id}
        if collection is not None:
            query["collection"] = collection
        url = f"http://{self.master_addr}:{self.master_port}/dir/lookup?{urlencode(query)}"
        res = await self.conn.get_data(url)
        try:
            data = json.loads(res) if res else {}
        except ValueError:
            return None
        locations = data.get("locations") if isinstance(data, dict) else None
        if not isinstance(locations, list):
            return None
        valid = [loc for loc in locations if isinstance(loc, dict) and loc.get("url")]
        if not valid:
            return None
        location = random.choice(valid)
        return FileLocation(location.get("publicUrl") or location["url"], location["url"])

    async def get_file_size(self, fid: str, collection: str | None = None) -> int | None:
        """Get size of uploaded file on SeaweedFS volume.

        For some type of files Gzip Compression might be applied.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            collection: Optional collection name to speed up the volume
                lookup on the master.

        Returns:
            Size in bytes or None if file doesn't exist.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = await self.get_file_url(fid, collection=collection)
        if url is None:
            return None
        res = await self.conn.head(url)
        if res is not None:
            size = res.headers.get("content-length", None)
            if size is not None:
                try:
                    return int(size)
                except ValueError:
                    return None
        return None

    async def file_exists(self, fid: str, collection: str | None = None) -> bool:
        """Check if file with provided fid exists.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            collection: Optional collection name to speed up the volume
                lookup on the master.

        Returns:
            True if file exists. False if not.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = await self.get_file_url(fid, collection=collection)
        if url is None:
            return False
        return await self.conn.head(url) is not None

    async def delete_file(self, fid: str, collection: str | None = None) -> bool:
        """Delete file from SeaweedFS.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            collection: Optional collection name to speed up the volume
                lookup on the master.

        Returns:
            True if file was deleted. False otherwise.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = await self.get_file_url(fid, collection=collection)
        if url is None:
            return False
        return await self.conn.delete_data(url)

    async def upload_file(
        self,
        path: str | None = None,
        stream: BinaryIO | None = None,
        name: str | None = None,
        additional_headers: dict[str, str] | None = None,
        content_type: str | None = None,
        **kwargs: str,
    ) -> str | None:
        """Upload file to SeaweedFS.

        It takes either path or stream and name and uploads it
        to SeaweedFS server.

        Args:
            path: Path to the file to upload.
            stream: File-like object to upload.
            name: Name of the uploaded file.
            additional_headers: Additional headers for the upload request.
            content_type: Content type of the uploaded file.
            **kwargs: Extra parameters forwarded to the ``/dir/assign``
                request (e.g. ``collection``, ``replication``, ``ttl``).

        Returns:
            Fid of the uploaded file or None if the upload failed.

        Raises:
            ValueError: If ``path`` is None and not both ``stream`` and
                ``name`` are provided.
            RuntimeError: If the volume server rejects the upload.

        """
        filename, file_stream, close_stream = prepare_stream(path, stream, name)
        try:
            params = urlencode(kwargs)
            query = f"?{params}" if params else ""
            url = f"http://{self.master_addr}:{self.master_port}/dir/assign{query}"
            res = await self.conn.get_data(url)
            try:
                data = json.loads(res) if res else {}
            except ValueError:
                data = {}
            if not isinstance(data, dict) or data.get("error") is not None:
                return None
            fid = data.get("fid")
            if not isinstance(fid, str) or not fid:
                return None
            key = "publicUrl" if self.use_public_url else "url"
            volume_url = data.get(key) or data.get("url")
            if not volume_url:
                return None
            post_url = f"http://{volume_url}/{fid}"

            res = await self.conn.post_file(post_url, filename, file_stream, additional_headers=additional_headers, content_type=content_type)
        finally:
            if close_stream:
                file_stream.close()

        if res is None:
            return None
        try:
            response_data = json.loads(res)
        except ValueError:
            response_data = {}
        if isinstance(response_data, dict) and "size" in response_data:
            return fid

        raise RuntimeError(f"Upload failed: {response_data}")

    async def submit_file(
        self,
        path: str | None = None,
        stream: BinaryIO | None = None,
        name: str | None = None,
        additional_headers: dict[str, str] | None = None,
        content_type: str | None = None,
    ) -> str | None:
        """Upload file directly through the master ``/submit`` endpoint.

        Convenience one-call upload: the master assigns a file id and
        stores the file on the right volume server. Unlike
        ``upload_file`` it does not support assign parameters
        (``collection``, ``replication``, ``ttl``, ...).

        Args:
            path: Path to the file to upload.
            stream: File-like object to upload.
            name: Name of the uploaded file.
            additional_headers: Additional headers for the upload request.
            content_type: Content type of the uploaded file.

        Returns:
            Fid of the uploaded file or None if the upload failed.

        Raises:
            ValueError: If ``path`` is None and not both ``stream`` and
                ``name`` are provided.

        """
        filename, file_stream, close_stream = prepare_stream(path, stream, name)
        try:
            url = f"http://{self.master_addr}:{self.master_port}/submit"
            res = await self.conn.post_file(url, filename, file_stream, additional_headers=additional_headers, content_type=content_type)
        finally:
            if close_stream:
                file_stream.close()

        if res is None:
            return None
        try:
            data = json.loads(res)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        fid = data.get("fid")
        return fid if isinstance(fid, str) else None

    async def vacuum(self, threshold: float = 0.3) -> bool:
        """Force garbage collection.

        Args:
            threshold: The threshold is optional, and will not change
                the default threshold on the server.

        Returns:
            True if the request succeeded. False otherwise.

        """
        url = f"http://{self.master_addr}:{self.master_port}/vol/vacuum?garbageThreshold={threshold}"
        return await self.conn.get_data(url) is not None

    async def _get_json(self, url: str) -> dict[str, Any] | None:
        """Get and decode a JSON object response from the given url."""
        res = await self.conn.get_data(url)
        try:
            data = json.loads(res) if res else None
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def grow_volumes(self, count: int, **kwargs: str) -> bool:
        """Pre-allocate new volumes on the volume servers.

        Requires free volume slots, i.e. the volume servers must be
        started with a ``-max`` value higher than the number of
        existing volumes.

        Args:
            count: Number of volumes to create.
            **kwargs: Extra parameters forwarded to the ``/vol/grow``
                request (e.g. ``collection``, ``replication``, ``ttl``,
                ``dataCenter``, ``dataNode``, ``rack``, ``disk``).

        Returns:
            True if the volumes were created. False otherwise.

        """
        params = urlencode({"count": str(count), **kwargs})
        url = f"http://{self.master_addr}:{self.master_port}/vol/grow?{params}"
        data = await self._get_json(url)
        return data is not None and "error" not in data

    async def delete_collection(self, collection: str) -> bool:
        """Delete a collection and all its volumes.

        Args:
            collection: Name of the collection to delete.

        Returns:
            True if the collection was deleted. False otherwise.

        """
        params = urlencode({"collection": collection})
        url = f"http://{self.master_addr}:{self.master_port}/col/delete?{params}"
        data = await self._get_json(url)
        return data is not None and "error" not in data

    async def cluster_status(self) -> dict[str, Any] | None:
        """Get the cluster status from the master.

        Returns:
            Cluster status dict (leader, topology) or None if the
            master can't be reached or returns malformed JSON.

        """
        url = f"http://{self.master_addr}:{self.master_port}/cluster/status"
        return await self._get_json(url)

    async def volume_status(self) -> dict[str, Any] | None:
        """Get the status of all volumes from the master.

        Returns:
            Volume status dict or None if the master can't be reached
            or returns malformed JSON.

        """
        url = f"http://{self.master_addr}:{self.master_port}/vol/status"
        return await self._get_json(url)

    async def volume_server_status(self, fid: str, collection: str | None = None) -> dict[str, Any] | None:
        """Get the status of the volume server holding the given fid.

        The internal volume url is used because ``/status`` is an
        administrative endpoint that may not be exposed publicly.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            collection: Optional collection name to speed up the volume
                lookup on the master.

        Returns:
            Volume server status dict (version, volumes, disk stats) or
            None if the volume can't be located or reached.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = await self.get_file_url(fid, public=False, collection=collection)
        if url is None:
            return None
        base_url = url.rsplit("/", 1)[0]
        return await self._get_json(f"{base_url}/status")

    async def is_healthy(self) -> bool:
        """Check the master cluster health endpoint.

        Returns:
            True if the master reports healthy. False otherwise.

        """
        url = f"http://{self.master_addr}:{self.master_port}/cluster/healthz"
        return await self.conn.get_data(url) is not None

    async def version(self) -> str | None:
        """Return Weed-FS master version.

        Unlike ``SeaweedFS.version`` this is a coroutine method and
        must be awaited.

        Returns:
            Version string or None if the master can't be reached.

        """
        url = f"http://{self.master_addr}:{self.master_port}/dir/status"
        data = await self.conn.get_data(url)
        try:
            response_data = json.loads(data) if data else {}
        except ValueError:
            response_data = {}
        if not isinstance(response_data, dict):
            return None
        version_str = response_data.get("Version")
        return version_str if isinstance(version_str, str) else None
