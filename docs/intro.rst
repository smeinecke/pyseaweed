***************
Intro
***************

Python module to communicate with Seaweed-FS_.


============
Installation
============

From PyPI::

    pip install pyseaweed


From GitHub::

    pip install git+https://github.com/utek/pyseaweed.git


From source::

    git clone git@github.com:utek/pyseaweed.git
    cd pyseaweed
    pip install .

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


.. _Weed-FS: https://github.com/chrislusf/seaweedfs
