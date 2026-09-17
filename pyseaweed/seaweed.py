# vi:si:et:sw=4:sts=4:ts=4


"""Main PySeaweed module. Contains SeaweedFS class."""

from __future__ import annotations

import json
import os
import random
from collections.abc import Iterator
from typing import Any, BinaryIO, NamedTuple
from urllib.parse import urlencode

from pyseaweed.exceptions import BadFidFormat
from pyseaweed.utils import Connection


class FileLocation(NamedTuple):
    """Location of a SeaweedFS volume server."""

    public_url: str
    url: str


class SeaweedFS:
    """Client for the SeaweedFS HTTP API."""

    def __init__(
        self,
        master_addr: str = "localhost",
        master_port: int = 9333,
        use_session: bool = False,
        use_public_url: bool = True,
    ) -> None:
        """Create a SeaweedFS instance.

        Args:
            master_addr: Address of SeaweedFS master server
                (default: localhost).
            master_port: SeaweedFS master server port (default: 9333).
            use_session: Use ``requests.Session()`` for connections instead of
                plain ``requests`` calls (default: False).
            use_public_url: If ``True``, all the requests will use
                ``publicUrl`` link instead of ``url``.

        Returns:
            SeaweedFS instance.

        """
        self.master_addr = master_addr
        self.master_port = master_port
        self.conn = Connection(use_session)
        self.use_public_url = use_public_url

    def __repr__(self) -> str:
        """Return string representation of the instance."""
        return f"<{self.__class__.__name__} {self.master_addr}:{self.master_port}>"

    @staticmethod
    def _range_headers(byte_range: tuple[int | None, int | None] | None) -> dict[str, str] | None:
        """Build a ``Range`` request header from a (start, end) tuple.

        Either bound may be None to leave it open (e.g. ``(None, 500)``
        requests the last 500 bytes, ``(100, None)`` requests from byte
        100 to the end).
        """
        if byte_range is None:
            return None
        start, end = byte_range
        return {"Range": f"bytes={'' if start is None else start}-{'' if end is None else end}"}

    def get_file(
        self,
        fid: str,
        byte_range: tuple[int | None, int | None] | None = None,
        params: dict[str, str] | None = None,
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

        Returns:
            Content of the file with provided fid or None if file doesn't
            exist on the server.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = self.get_file_url(fid, params=params)
        if url is None:
            return None
        return self.conn.get_raw_data(url, additional_headers=self._range_headers(byte_range))

    def get_file_stream(
        self,
        fid: str,
        byte_range: tuple[int | None, int | None] | None = None,
        params: dict[str, str] | None = None,
        chunk_size: int = 8192,
    ) -> Iterator[bytes] | None:
        """Get file from SeaweedFS as a stream of chunks.

        Unlike ``get_file`` this does not load the whole file into memory.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            byte_range: Optional ``(start, end)`` tuple for a HTTP range
                request. Either bound may be None to leave it open.
            params: Optional query parameters for the volume request.
            chunk_size: Size of the chunks yielded by the iterator.

        Returns:
            Iterator of file chunks or None if the file doesn't exist
            on the server.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = self.get_file_url(fid, params=params)
        if url is None:
            return None
        return self.conn.get_stream(url, additional_headers=self._range_headers(byte_range), chunk_size=chunk_size)

    def get_file_url(self, fid: str, public: bool | None = None, params: dict[str, str] | None = None) -> str | None:
        """Get url for the file.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            public: Use the public or the internal url. Defaults to the
                ``use_public_url`` setting of this instance.
            params: Optional query parameters appended to the file url
                (e.g. ``width``/``height``/``mode``/crop parameters for
                server-side image resizing or ``readDeleted``).

        Returns:
            File url as string or None if the volume can't be located.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        fid = fid.strip()
        try:
            volume_id, _ = fid.split(",")
        except ValueError:
            raise BadFidFormat("fid must be in format: <volume_id>,<file_name_hash>")
        file_location = self.get_file_location(volume_id)
        if file_location is None:
            return None
        if public is None:
            public = self.use_public_url
        volume_url = file_location.public_url if public else file_location.url
        url = f"http://{volume_url}/{fid}"
        if params:
            url += f"?{urlencode(params)}"
        return url

    def get_file_location(self, volume_id: str, collection: str | None = None) -> FileLocation | None:
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
        res = self.conn.get_data(url)
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

    def get_file_size(self, fid: str) -> int | None:
        """Get size of uploaded file on SeaweedFS volume.

        For some type of files Gzip Compression might be applied.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.

        Returns:
            Size in bytes or None if file doesn't exist.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = self.get_file_url(fid)
        if url is None:
            return None
        res = self.conn.head(url)
        if res is not None:
            size = res.headers.get("content-length", None)
            if size is not None:
                try:
                    return int(size)
                except ValueError:
                    return None
        return None

    def file_exists(self, fid: str) -> bool:
        """Check if file with provided fid exists.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.

        Returns:
            True if file exists. False if not.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = self.get_file_url(fid)
        if url is None:
            return False
        return self.conn.head(url) is not None

    def delete_file(self, fid: str) -> bool:
        """Delete file from SeaweedFS.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.

        Returns:
            True if file was deleted. False otherwise.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = self.get_file_url(fid)
        if url is None:
            return False
        return self.conn.delete_data(url)

    def upload_file(
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
        filename, file_stream, close_stream = self._prepare_stream(path, stream, name)
        try:
            params = urlencode(kwargs)
            query = f"?{params}" if params else ""
            url = f"http://{self.master_addr}:{self.master_port}/dir/assign{query}"
            res = self.conn.get_data(url)
            try:
                data = json.loads(res) if res else {}
            except ValueError:
                data = {}
            if not isinstance(data, dict) or data.get("error") is not None or "fid" not in data:
                return None
            key = "publicUrl" if self.use_public_url else "url"
            volume_url = data.get(key) or data.get("url")
            if not volume_url:
                return None
            post_url = f"http://{volume_url}/{data['fid']}{query}"

            res = self.conn.post_file(post_url, filename, file_stream, additional_headers=additional_headers, content_type=content_type)
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
            return data.get("fid")

        raise RuntimeError(f"Upload failed: {response_data}")

    @staticmethod
    def _prepare_stream(
        path: str | None,
        stream: BinaryIO | None,
        name: str | None,
    ) -> tuple[str, BinaryIO, bool]:
        """Resolve path/stream/name into a (filename, stream, close) triple.

        The returned flag indicates whether the caller owns the stream
        (opened from ``path``) and must close it afterwards.
        """
        if path is not None:
            filename = os.path.basename(path) if name is None else name
            return filename, open(path, "rb"), True
        if stream is not None and name is not None:
            return name, stream, False
        raise ValueError("If `path` is None then *both* `stream` and `name` must not be None")

    def submit_file(
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
        filename, file_stream, close_stream = self._prepare_stream(path, stream, name)
        try:
            url = f"http://{self.master_addr}:{self.master_port}/submit"
            res = self.conn.post_file(url, filename, file_stream, additional_headers=additional_headers, content_type=content_type)
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

    def vacuum(self, threshold: float = 0.3) -> bool:
        """Force garbage collection.

        Args:
            threshold: The threshold is optional, and will not change
                the default threshold on the server.

        Returns:
            True if the request succeeded. False otherwise.

        """
        url = f"http://{self.master_addr}:{self.master_port}/vol/vacuum?garbageThreshold={threshold}"
        return self.conn.get_data(url) is not None

    def _get_json(self, url: str) -> dict[str, Any] | None:
        """Get and decode a JSON object response from the given url."""
        res = self.conn.get_data(url)
        try:
            data = json.loads(res) if res else None
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def grow_volumes(self, count: int, **kwargs: str) -> bool:
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
        data = self._get_json(url)
        return data is not None and "error" not in data

    def delete_collection(self, collection: str) -> bool:
        """Delete a collection and all its volumes.

        Args:
            collection: Name of the collection to delete.

        Returns:
            True if the collection was deleted. False otherwise.

        """
        params = urlencode({"collection": collection})
        url = f"http://{self.master_addr}:{self.master_port}/col/delete?{params}"
        data = self._get_json(url)
        return data is not None and "error" not in data

    def cluster_status(self) -> dict[str, Any] | None:
        """Get the cluster status from the master.

        Returns:
            Cluster status dict (leader, topology) or None if the
            master can't be reached or returns malformed JSON.

        """
        url = f"http://{self.master_addr}:{self.master_port}/cluster/status"
        return self._get_json(url)

    def volume_status(self) -> dict[str, Any] | None:
        """Get the status of all volumes from the master.

        Returns:
            Volume status dict or None if the master can't be reached
            or returns malformed JSON.

        """
        url = f"http://{self.master_addr}:{self.master_port}/vol/status"
        return self._get_json(url)

    def volume_server_status(self, fid: str) -> dict[str, Any] | None:
        """Get the status of the volume server holding the given fid.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.

        Returns:
            Volume server status dict (version, volumes, disk stats) or
            None if the volume can't be located or reached.

        Raises:
            BadFidFormat: If fid is not in the
                ``<volume_id>,<file_name_hash>`` format.

        """
        url = self.get_file_url(fid)
        if url is None:
            return None
        base_url = url.rsplit("/", 1)[0]
        return self._get_json(f"{base_url}/status")

    def is_healthy(self) -> bool:
        """Check the master cluster health endpoint.

        Returns:
            True if the master reports healthy. False otherwise.

        """
        url = f"http://{self.master_addr}:{self.master_port}/cluster/healthz"
        return self.conn.get_data(url) is not None

    @property
    def version(self) -> str | None:
        """Return Weed-FS master version.

        Returns:
            Version string or None if the master can't be reached.

        """
        url = f"http://{self.master_addr}:{self.master_port}/dir/status"
        data = self.conn.get_data(url)
        try:
            response_data = json.loads(data) if data else {}
        except ValueError:
            response_data = {}
        if not isinstance(response_data, dict):
            return None
        return response_data.get("Version")
