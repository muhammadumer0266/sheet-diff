from .core import diff_sheets, format_unified, diff_rows_full, diff_multi_grid, compare_workbooks
from . import config
from .storage import resolve as resolve_source, resolve_many as resolve_sources, StorageError

__all__ = [
    "diff_sheets", "format_unified", "diff_rows_full", "diff_multi_grid", "compare_workbooks",
    "config", "resolve_source", "resolve_sources", "StorageError",
]
