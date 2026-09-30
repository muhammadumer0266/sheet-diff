"""Central, environment-driven configuration for sheet_diff.

Every knob here can be overridden with an environment variable so a
deployment can tune limits and remote-storage credentials without touching
code. Nothing here reads a hardcoded secret — credentials only ever come
from the environment (or a `.env` loaded by the process before start-up),
never from user-submitted form fields, so a web UI cannot be used to smuggle
credentials for a backend the operator didn't configure.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, Optional


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a valid integer") from None
    if value <= 0:
        raise ValueError(f"{name}={raw!r} must be a positive integer")
    return value


def _env_list(name: str, default: str) -> list:
    raw = os.environ.get(name, default)
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


# --- Upload / download size limits -----------------------------------------
# All expressed in MB for readability at the env-var layer; converted to
# bytes for use. Change per-deployment via env vars, e.g.:
#   SHEET_DIFF_MAX_UPLOAD_MB=250
#   SHEET_DIFF_MAX_REMOTE_MB=500
#   SHEET_DIFF_MAX_FILES=6
MAX_UPLOAD_MB = _env_int("SHEET_DIFF_MAX_UPLOAD_MB", 100)
MAX_REMOTE_MB = _env_int("SHEET_DIFF_MAX_REMOTE_MB", MAX_UPLOAD_MB)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_REMOTE_BYTES = MAX_REMOTE_MB * 1024 * 1024

# Hard ceiling on how many files can be compared in one request (web UI and
# CLI --all-sheets multi-file mode), to bound memory/CPU on shared servers.
MAX_FILES = _env_int("SHEET_DIFF_MAX_FILES", 8)

# Network timeouts for remote storage reads (seconds).
REMOTE_CONNECT_TIMEOUT = _env_int("SHEET_DIFF_REMOTE_CONNECT_TIMEOUT", 10)
REMOTE_READ_TIMEOUT = _env_int("SHEET_DIFF_REMOTE_READ_TIMEOUT", 60)

# Which remote URI schemes are enabled at all. Empty by default in the sense
# that only schemes listed here are ever dispatched to fsspec; anything else
# (including http/https, to avoid turning the diff endpoint into an SSRF
# proxy) is rejected outright.
ALLOWED_REMOTE_SCHEMES = set(
    _env_list("SHEET_DIFF_ALLOWED_SCHEMES", "s3,minio,r2,garage,az,azure,gs")
)


@dataclass
class BackendConfig:
    protocol: str  # fsspec protocol, e.g. "s3" or "az"
    storage_options: Dict[str, str] = field(default_factory=dict)


def _s3_backend(scheme: str) -> BackendConfig:
    prefix = f"SHEET_DIFF_STORAGE_{scheme.upper()}_"
    opts: Dict[str, str] = {}
    endpoint = os.environ.get(prefix + "ENDPOINT_URL")
    if endpoint:
        opts["client_kwargs"] = {"endpoint_url": endpoint}
    key = os.environ.get(prefix + "KEY") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get(prefix + "SECRET") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    region = os.environ.get(prefix + "REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if key:
        opts["key"] = key
    if secret:
        opts["secret"] = secret
    if region:
        opts.setdefault("client_kwargs", {})["region_name"] = region
    return BackendConfig(protocol="s3", storage_options=opts)


def _azure_backend() -> BackendConfig:
    prefix = "SHEET_DIFF_STORAGE_AZ_"
    opts: Dict[str, str] = {}
    conn_str = os.environ.get(prefix + "CONNECTION_STRING")
    if conn_str:
        opts["connection_string"] = conn_str
    else:
        account = os.environ.get(prefix + "ACCOUNT_NAME")
        account_key = os.environ.get(prefix + "ACCOUNT_KEY")
        sas_token = os.environ.get(prefix + "SAS_TOKEN")
        if account:
            opts["account_name"] = account
        if account_key:
            opts["account_key"] = account_key
        if sas_token:
            opts["sas_token"] = sas_token
    return BackendConfig(protocol="az", storage_options=opts)


def _gcs_backend() -> BackendConfig:
    opts: Dict[str, str] = {}
    creds = os.environ.get("SHEET_DIFF_STORAGE_GS_TOKEN")
    if creds:
        opts["token"] = creds
    return BackendConfig(protocol="gcs", storage_options=opts)


def backend_for_scheme(scheme: str) -> Optional[BackendConfig]:
    """Map a URI scheme (e.g. 'minio', 'r2', 'az') to an fsspec backend.

    Returns None if the scheme isn't recognized/enabled, so callers can
    reject it instead of silently falling through to some default.
    """
    scheme = scheme.lower()
    if scheme not in ALLOWED_REMOTE_SCHEMES:
        return None
    if scheme in ("s3", "minio", "r2", "garage"):
        return _s3_backend(scheme)
    if scheme in ("az", "azure"):
        return _azure_backend()
    if scheme == "gs":
        return _gcs_backend()
    return None
