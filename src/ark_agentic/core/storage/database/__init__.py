"""Database backend — SQLAlchemy infrastructure shared by all SQL dialects.

Holds the AsyncEngine factory, ``DBConfig``, the core ``Base``, and core ORM
models. Dialect-specific repository implementations live in subpackages
(``sqlite/`` today, ``pg/`` / ``mysql/`` in the future).

This package is loaded only when ``mode.is_database()`` is true.
"""
