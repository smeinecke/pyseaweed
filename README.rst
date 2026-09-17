*********************************************************
PySeaweed
*********************************************************

|ci| |release| |docs| |python|

.. |ci| image:: https://github.com/smeinecke/pyseaweed/actions/workflows/check.yml/badge.svg
   :target: https://github.com/smeinecke/pyseaweed/actions/workflows/check.yml
.. |release| image:: https://img.shields.io/github/v/release/smeinecke/pyseaweed
   :target: https://github.com/smeinecke/pyseaweed/releases
.. |docs| image:: https://img.shields.io/badge/docs-pages-blue
   :target: https://smeinecke.github.io/pyseaweed/
.. |python| image:: https://img.shields.io/badge/python-%3E%3D3.13-blue
   :target: https://pypi.org/project/pyseaweed/

Class to simplify communication with Seaweed-FS_

============
Installation
============

Requires Python 3.13 or later.

From PyPI::

    pip install pyseaweed

    # for the async client (httpx)
    pip install "pyseaweed[async]"

============
Tests
============
Install dependencies (requires uv_)::

    uv sync

Run unit tests::

    uv run pytest tests/unit

Or using make::

    make test

.. note::
    Integration tests assume that there is a SeaweedFS master running on
    localhost:9333 (defaults). Start one with ``make weed-up`` and run
    ``make test-integration`` (``make test-integration-local`` does both).

.. _uv: https://docs.astral.sh/uv/


============
Usage
============

Upload file to SeaweedFS

.. code-block:: python

    from pyseaweed import SeaweedFS

    # WeedFS is kept as a backward-compatible alias
    w = SeaweedFS("localhost", 9333)  # master address and port

    # Optionally: request timeout and a reusable session, closed on exit
    with SeaweedFS("localhost", 9333, use_session=True, timeout=30) as w:
        ...

    # File upload (assigns a file id, then stores on a volume server)
    fid = w.upload_file("n.txt")  # path to file

    # One-call upload via the master /submit endpoint
    fid = w.submit_file("n.txt")

    # Get file url
    file_url = w.get_file_url(fid)

    # Read whole file, or a byte range
    content = w.get_file(fid)
    first_kib = w.get_file(fid, byte_range=(0, 1023))

    # Stream large files without buffering them in memory
    for chunk in w.get_file_stream(fid, chunk_size=65536):
        ...

    # Server-side image resizing / other volume read parameters
    thumb_url = w.get_file_url(fid, params={"width": "100", "height": "100"})

    # Delete file
    res = w.delete_file(fid)
    # res is boolean (True if file was deleted)

Cluster administration and status

.. code-block:: python

    w.is_healthy()                # /cluster/healthz
    w.cluster_status()            # leader and topology
    w.volume_status()             # all volumes on the master
    w.volume_server_status(fid)   # volume server holding the fid
    w.grow_volumes(4, collection="images")
    w.delete_collection("old-collection")
    w.vacuum(0.4)                 # force garbage collection
    w.version                     # master version string

Async client (requires ``pip install "pyseaweed[async]"``, mirrors the
full ``SeaweedFS`` API on top of httpx)

.. code-block:: python

    from pyseaweed import AsyncSeaweedFS

    async with AsyncSeaweedFS("localhost", 9333, timeout=30, retries=3) as w:
        fid = await w.upload_file("n.txt")
        content = await w.get_file(fid)
        stream = await w.get_file_stream(fid, chunk_size=65536)
        async for chunk in stream:
            ...
        await w.delete_file(fid)
        await w.version()           # method, not a property

Filer (path-based file access on the SeaweedFS filer, port 8888)

.. code-block:: python

    from pyseaweed import Filer

    with Filer("localhost", 8888) as f:
        f.upload_file("/docs/report.pdf", "report.pdf")
        f.mkdir("/docs/archive")

        for entry in f.list_dir("/docs")["Entries"]:
            print(entry["FullPath"], entry["FileSize"])

        content = f.download_file("/docs/report.pdf")
        f.move("/docs/report.pdf", "/docs/archive/report.pdf")
        f.set_tags("/docs/archive/report.pdf", {"kind": "report"})
        f.get_tags("/docs/archive/report.pdf")   # {"Kind": "report"}
        f.delete("/docs/archive", recursive=True)

AsyncFiler (async variant of ``Filer``, requires
``pip install "pyseaweed[async]"``)

.. code-block:: python

    from pyseaweed import AsyncFiler

    async with AsyncFiler("localhost", 8888) as f:
        await f.upload_file("/docs/report.pdf", "report.pdf")
        content = await f.download_file("/docs/report.pdf")
        async for chunk in await f.get_file_stream("/docs/report.pdf"):
            ...
        await f.delete("/docs", recursive=True)


.. _Seaweed-FS: https://github.com/chrislusf/seaweedfs
