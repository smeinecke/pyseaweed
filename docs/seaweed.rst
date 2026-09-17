===============
SeaweedFS
===============

.. automodule:: pyseaweed.seaweed

.. autoclass:: pyseaweed.seaweed.SeaweedFS
    :members:

    .. automethod:: __init__

.. autoclass:: pyseaweed.seaweed.FileLocation
    :members:

.. autoexception:: pyseaweed.exceptions.BadFidFormat
    :members:


===============
Filer
===============

Path-based file access via the SeaweedFS filer (port 8888).

.. autoclass:: pyseaweed.filer.Filer
    :members:

    .. automethod:: __init__


===============
Async client
===============

Requires the ``async`` extra (``pip install "pyseaweed[async]"``).

.. autoclass:: pyseaweed.async_client.AsyncSeaweedFS
    :members:

    .. automethod:: __init__

.. autoclass:: pyseaweed.async_client.AsyncConnection
    :members:


===============
Utils
===============

.. automodule:: pyseaweed.utils
    :members:
