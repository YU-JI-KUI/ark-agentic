"""Studio user-repository storage adapters.

File mode stores grants in ``data/ark_studio.json``. SQLite mode stores
them in the shared core database through feature-local metadata.
"""

from .file import FileStudioUserRepository
from .sqlite import SqliteStudioUserRepository

__all__ = ["FileStudioUserRepository", "SqliteStudioUserRepository"]
