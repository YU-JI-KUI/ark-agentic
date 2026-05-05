"""Job-run storage adapters (file / sqlite).

``JobRunRow`` registers on the feature-local ``JobsBase`` metadata,
created by ``services.jobs.engine.init_schema()``.
"""

from .file import FileJobRunRepository
from .sqlite import SqliteJobRunRepository

__all__ = [
    "FileJobRunRepository",
    "SqliteJobRunRepository",
]
