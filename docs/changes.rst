===========
Changelog
===========

-------
3.1.0
-------

    - Add ``AsyncSeaweedFS``, an async client mirroring the full
      ``SeaweedFS`` API on top of httpx. Install with
      ``pip install "pyseaweed[async]"``. Available as
      ``from pyseaweed import AsyncSeaweedFS`` or
      ``from pyseaweed.async_client import AsyncSeaweedFS``
    - Add ``retries`` parameter to ``Connection`` and ``SeaweedFS``
      (and the async equivalents) to retry transient server errors
    - Validate fid format strictly (numeric volume id, hex file key,
      optional extension)
    - CI: unit tests now run on Python 3.13 and 3.14; release builds
      are attested with build provenance

-------
3.0.0
-------

    - **Require Python 3.13+** (dropped Python 3.9 - 3.12)
    - Restructure to ``src`` layout, build with hatchling, ship
      ``py.typed`` marker (PEP 561)
    - Add a configurable request ``timeout`` on ``Connection`` and
      ``SeaweedFS``
    - ``Connection`` and ``SeaweedFS`` gain ``close()`` and
      context-manager support
    - Reject fids with empty volume id or file key parts
    - Add ``get_file_stream`` for chunked downloads without buffering
      the whole file in memory
    - Add ``byte_range`` support (HTTP Range requests) and read query
      parameters (image resizing, ``readDeleted``) to ``get_file`` and
      ``get_file_url``
    - Add ``collection`` parameter to ``get_file_location`` and all
      fid-based methods
    - Add ``submit_file`` for one-call uploads via the master
      ``/submit`` endpoint
    - Add admin/status endpoints: ``grow_volumes``,
      ``delete_collection``, ``cluster_status``, ``volume_status``,
      ``volume_server_status`` and ``is_healthy``
    - Accept any 2xx status code for volume operations
    - Harden error handling for malformed server responses

-------
2.0.0
-------

    - Rename module to `pyseaweed`
    - Add pre-commit configuration
    - Code formatting
    - Remove Py27, Py34 from tests

-------
1.0.0
-------

    - Rename to `pyseaweed`

-------
0.3.5
-------

    - Code cleanup
    - Adds ability to use `requests.Session()`

-------
0.3.3
-------

    - Function get_file_size added
    - Function file_exists added
    - upload_file changed to accept file like object and path
