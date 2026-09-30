"""Resolve a spreadsheet reference — local path or remote URI — to a local
file that the rest of sheet_diff (pandas / the Rust core) can read.

Supported remote schemes: s3://, minio://, r2://, garage:// (all S3-compatible,
routed through `s3fs` with a per-scheme endpoint/credentials from
`sheet_diff.config`), and az:// / azure:// (Azure Blob Storage via `adlfs`).

Design notes / edge cases handled here (see docs/EDGE_CASES.md for the full
list this project tracks):

- Windows local paths (`C:\\foo\\bar.xlsx`) must not be mistaken for a URI
  scheme — `_split_scheme` only treats a prefix as a scheme if it's followed
  by `://`, so a single-letter drive + `:` never matches.
- Only an explicit allow-list of schemes is dispatched remotely (see
  `config.ALLOWED_REMOTE_SCHEMES`); everything else, including arbitrary
  http(s) URLs, is rejected so the diff endpoint can't be turned into an
  open SSRF proxy.
- Size is checked *before* downloading whenever the backend can report it
  (`fs.info(path)["size"]`), and the download is additionally capped while
  streaming in case the reported size was wrong or missing — this is the
  remote-storage analogue of the "zip bomb" / "very large sheet" cases in
  EDGE_CASES.md.
- Missing optional dependency (`fsspec`/`s3fs`/`adlfs` not installed) raises
  a clear, actionable error instead of an opaque ImportError deep in fsspec.
- Every temp file this module creates is tracked so callers can clean up
  even when an exception happens partway through a multi-file batch.
"""
import os
import re
import uuid
from typing import List, Optional, Tuple

from . import config

_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://")


class StorageError(Exception):
    """Base class for remote-storage resolution failures."""


class SchemeNotAllowedError(StorageError):
    pass


class MissingDependencyError(StorageError):
    pass


class RemoteFileTooLargeError(StorageError):
    pass


class RemoteReadError(StorageError):
    pass


def _split_scheme(ref: str) -> Optional[str]:
    m = _SCHEME_RE.match(ref)
    return m.group(1).lower() if m else None


def is_remote_ref(ref: str) -> bool:
    return _split_scheme(ref) in config.ALLOWED_REMOTE_SCHEMES


def _get_filesystem(scheme: str):
    backend = config.backend_for_scheme(scheme)
    if backend is None:
        raise SchemeNotAllowedError(
            f"Remote scheme '{scheme}://' is not enabled. Allowed schemes: "
            f"{', '.join(sorted(config.ALLOWED_REMOTE_SCHEMES)) or '(none configured)'}"
        )
    try:
        import fsspec
    except ImportError as e:
        raise MissingDependencyError(
            "Remote storage support requires the 'remote' extra: "
            "pip install xl-diff[remote]"
        ) from e
    try:
        fs = fsspec.filesystem(
            backend.protocol,
            **backend.storage_options,
            connect_timeout=config.REMOTE_CONNECT_TIMEOUT,
            read_timeout=config.REMOTE_READ_TIMEOUT,
        )
    except TypeError:
        # Some fsspec backends don't accept timeout kwargs directly.
        fs = fsspec.filesystem(backend.protocol, **backend.storage_options)
    return fs


def _strip_scheme(ref: str, scheme: str) -> str:
    return ref[len(scheme) + 3:]  # drop "<scheme>://"


def fetch_to_local(ref: str, dest_dir: str, max_bytes: Optional[int] = None) -> str:
    """Download a remote object to `dest_dir` and return the local path.

    Raises RemoteFileTooLargeError if the object's reported (or actual,
    streamed) size exceeds `max_bytes` (defaults to config.MAX_REMOTE_BYTES).
    """
    scheme = _split_scheme(ref)
    if scheme is None:
        raise StorageError(f"'{ref}' is not a remote URI (missing scheme://)")
    limit = config.MAX_REMOTE_BYTES if max_bytes is None else max_bytes

    fs = _get_filesystem(scheme)
    remote_path = _strip_scheme(ref, scheme)

    try:
        info = fs.info(remote_path)
        size = info.get("size")
    except Exception as e:
        raise RemoteReadError(f"Could not stat '{ref}': {e}") from e

    if size is not None and size > limit:
        raise RemoteFileTooLargeError(
            f"'{ref}' is {size / (1024 * 1024):.1f} MB, which exceeds the "
            f"{limit / (1024 * 1024):.0f} MB remote file size limit "
            f"(configure via SHEET_DIFF_MAX_REMOTE_MB)."
        )

    basename = os.path.basename(remote_path) or f"remote-{uuid.uuid4().hex}"
    local_path = os.path.join(dest_dir, f"{uuid.uuid4().hex}_{basename}")

    written = 0
    chunk_size = 8 * 1024 * 1024
    try:
        with fs.open(remote_path, "rb") as src, open(local_path, "wb") as dst:
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise RemoteFileTooLargeError(
                        f"'{ref}' exceeded the {limit / (1024 * 1024):.0f} MB "
                        "remote file size limit while streaming (actual size "
                        "was larger than reported)."
                    )
                dst.write(chunk)
    except RemoteFileTooLargeError:
        _safe_remove(local_path)
        raise
    except FileNotFoundError as e:
        _safe_remove(local_path)
        raise RemoteReadError(f"'{ref}' was not found") from e
    except Exception as e:
        _safe_remove(local_path)
        raise RemoteReadError(f"Failed to download '{ref}': {e}") from e

    return local_path


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def resolve(ref: str, dest_dir: str, max_bytes: Optional[int] = None) -> str:
    """Resolve `ref` (local path or remote URI) to a local, readable path."""
    if is_remote_ref(ref):
        return fetch_to_local(ref, dest_dir, max_bytes=max_bytes)
    scheme = _split_scheme(ref)
    if scheme is not None:
        raise SchemeNotAllowedError(
            f"'{ref}' uses scheme '{scheme}://', which is not an allowed "
            f"remote scheme. Allowed: {', '.join(sorted(config.ALLOWED_REMOTE_SCHEMES))}"
        )
    if not os.path.exists(ref):
        raise StorageError(f"Local file not found: '{ref}'")
    return ref


def resolve_many(
    refs: List[str], dest_dir: str, max_bytes: Optional[int] = None
) -> Tuple[List[str], List[str]]:
    """Resolve several refs; returns (local_paths, downloaded_paths).

    `downloaded_paths` is the subset the caller is responsible for cleaning
    up (local, already-on-disk paths are left untouched); if this raises
    partway through, everything downloaded so far is cleaned up automatically.
    """
    local_paths: List[str] = []
    downloaded: List[str] = []
    try:
        for ref in refs:
            before = is_remote_ref(ref)
            path = resolve(ref, dest_dir, max_bytes=max_bytes)
            local_paths.append(path)
            if before:
                downloaded.append(path)
    except Exception:
        for p in downloaded:
            _safe_remove(p)
        raise
    return local_paths, downloaded
