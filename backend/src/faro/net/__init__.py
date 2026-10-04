"""Network boundary: the only package allowed to import networking libraries.

``guard`` blocks every non-loopback connection and DNS lookup at runtime;
``download`` is the single, explicit way out to the Internet.
"""
