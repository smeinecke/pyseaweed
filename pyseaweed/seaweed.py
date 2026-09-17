# vi:si:et:sw=4:sts=4:ts=4


"""Main PySeaweed module. Contains SeaweedFS class."""

from __future__ import annotations

import json
import os
import random
from typing import BinaryIO, NamedTuple
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

    def get_file(self, fid: str) -> bytes | None:
        """Get file from SeaweedFS.

        Return file content. May be problematic for large files as content is
        stored in memory.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.

        Returns:
            Content of the file with provided fid or None if file doesn't
            exist on the server.

        """
        url = self.get_file_url(fid)
        if url is None:
            return None
        return self.conn.get_raw_data(url)

    def get_file_url(self, fid: str, public: bool | None = None) -> str | None:
        """Get url for the file.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.
            public: Use the public or the internal url. Defaults to the
                ``use_public_url`` setting of this instance.

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
        return f"http://{volume_url}/{fid}"

    def get_file_location(self, volume_id: str) -> FileLocation | None:
        """Get location for the file.

        SeaweedFS volume is chosen randomly.

        Args:
            volume_id: Volume id.

        Returns:
            ``FileLocation`` namedtuple or None if the volume
            can't be located.

        """
        url = f"http://{self.master_addr}:{self.master_port}/dir/lookup?volumeId={volume_id}"
        res = self.conn.get_data(url)
        try:
            data = json.loads(res) if res else {}
        except ValueError:
            return None
        locations = data.get("locations") if isinstance(data, dict) else None
        if not isinstance(locations, list) or not locations:
            return None
        location = random.choice(locations)
        if not isinstance(location, dict) or "url" not in location:
            return None
        return FileLocation(location.get("publicUrl") or location["url"], location["url"])

    def get_file_size(self, fid: str) -> int | None:
        """Get size of uploaded file on SeaweedFS volume.

        For some type of files Gzip Compression might be applied.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.

        Returns:
            Size in bytes or None if file doesn't exist.

        """
        url = self.get_file_url(fid)
        if url is None:
            return None
        res = self.conn.head(url)
        if res is not None:
            size = res.headers.get("content-length", None)
            if size is not None:
                return int(size)
        return None

    def file_exists(self, fid: str) -> bool:
        """Check if file with provided fid exists.

        Args:
            fid: File identifier ``<volume_id>,<file_name_hash>``.

        Returns:
            True if file exists. False if not.

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
        # we have file like object and filename
        close_stream = False
        if path is not None:
            filename = os.path.basename(path) if name is None else name
            file_stream = open(path, "rb")
            close_stream = True
        elif stream is not None and name is not None:
            filename = name
            file_stream = stream
        else:
            raise ValueError("If `path` is None then *both* `stream` and `name` must not be None")

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
            volume_url = data.get(key)
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


if __name__ == "__main__":
    pass
