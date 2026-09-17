# vi:si:et:sw=4:sts=4:ts=4


"""Helper module that contains functions to ease communication with seaweedfs."""

from __future__ import annotations

from types import ModuleType
from typing import BinaryIO

import requests

from pyseaweed.version import __version__


class Connection:
    """Handle http communication with SeaweedFS."""

    def __init__(self, use_session: bool = False) -> None:
        """Create a Connection instance.

        Args:
            use_session: Use ``requests.Session()`` for connections instead of
                plain ``requests`` calls (default: False).

        """
        self._conn: requests.Session | ModuleType
        if use_session:
            self._conn = requests.Session()
        else:
            self._conn = requests

    def close(self) -> None:
        """Close the underlying session, if any."""
        if isinstance(self._conn, requests.Session):
            self._conn.close()

    def __enter__(self) -> Connection:
        """Return self for context manager usage."""
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Close the underlying session on context manager exit."""
        self.close()

    def _prepare_headers(self, additional_headers: dict[str, str] | None = None) -> dict[str, str]:
        """Prepare headers for http communication.

        Return dict of headers to be used in requests.

        Args:
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Headers dict. Keys and values are strings.

        """
        user_agent = f"pyseaweed/{__version__}"
        headers = {"User-Agent": user_agent}
        if additional_headers is not None:
            headers.update(additional_headers)
        return headers

    def head(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> requests.Response | None:
        """Return response to http HEAD on provided url.

        Args:
            url: Address of the wanted data.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Response object or None if the request failed.

        """
        try:
            res = self._conn.head(url, headers=self._prepare_headers(additional_headers), timeout=timeout)
        except requests.RequestException:
            return None
        if 200 <= res.status_code < 300:
            return res
        return None

    def get_data(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> str | None:
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
        try:
            res = self._conn.get(url, headers=self._prepare_headers(additional_headers), timeout=timeout)
        except requests.RequestException:
            return None
        if 200 <= res.status_code < 300:
            return res.text
        else:
            return None

    def get_raw_data(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> bytes | None:
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
        try:
            res = self._conn.get(url, headers=self._prepare_headers(additional_headers), timeout=timeout)
        except requests.RequestException:
            return None
        if 200 <= res.status_code < 300:
            return res.content
        else:
            return None

    def post_file(
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
        try:
            res = self._conn.post(
                url,
                files={"file": (filename, file_stream) if content_type is None else (filename, file_stream, content_type)},
                headers=self._prepare_headers(additional_headers),
                timeout=timeout,
            )
        except requests.RequestException:
            return None
        if 200 <= res.status_code < 300:
            return res.text
        else:
            return None

    def delete_data(self, url: str, timeout: float | None = None, additional_headers: dict[str, str] | None = None) -> bool:
        """Delete data under provided url.

        Args:
            url: Address of file to be deleted.
            timeout: Optional request timeout in seconds.
            additional_headers: Additional headers to be used
                with the request.

        Returns:
            Boolean. True if request was successful. False if not.

        """
        try:
            res = self._conn.delete(url, headers=self._prepare_headers(additional_headers), timeout=timeout)
        except requests.RequestException:
            return False
        if 200 <= res.status_code < 300:
            return True
        else:
            return False
