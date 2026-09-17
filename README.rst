*********************************************************
PySeaweed
*********************************************************

Class to simplify communication with Seaweed-FS_

============
Installation
============

From PyPI::

    pip install pyseaweed

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

Upload file to weedFS

.. code-block:: python

    from pyseaweed import WeedFS

    # File upload
    w = WeedFS("localhost", 9333) # weed-fs master address and port
    fid = w.upload_file("n.txt") # path to file

    # Get file url
    file_url = w.get_file_url(fid)

    # Delete file
    res = w.delete_file(fid)
    # res is boolean (True if file was deleted)


.. _Weed-FS: https://github.com/chrislusf/seaweedfs
