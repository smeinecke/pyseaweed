===========
Changelog
===========

-------
2.1.0
-------

    - **Require Python 3.13+** (dropped Python 3.9 - 3.12)
    - Restructure to ``src`` layout, build with hatchling, ship
      ``py.typed`` marker (PEP 561)
    - Add ``get_file_stream`` for chunked downloads without buffering
      the whole file in memory
    - Add ``byte_range`` support (HTTP Range requests) and read query
      parameters (image resizing, ``readDeleted``) to ``get_file`` and
      ``get_file_url``
    - Add ``collection`` parameter to ``get_file_location``
    - Add ``submit_file`` for one-call uploads via the master
      ``/submit`` endpoint
    - Add admin/status endpoints: ``grow_volumes``,
      ``delete_collection``, ``cluster_status``, ``volume_status``,
      ``volume_server_status`` and ``is_healthy``
    - Add ``Connection.close`` and context-manager support on both
      ``Connection`` and ``SeaweedFS``
    - Add a configurable request ``timeout`` on ``Connection`` and
      ``SeaweedFS``
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
