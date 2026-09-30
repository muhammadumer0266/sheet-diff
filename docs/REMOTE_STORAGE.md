# Remote storage & size limits

xl-diff can compare spreadsheets that live in object storage instead of (or
alongside) files uploaded through the browser or passed as local paths on
the CLI. This covers S3-compatible services — AWS S3, MinIO, Cloudflare R2,
Garage — and Azure Blob Storage.

## Install

```
pip install xl-diff[remote]      # fsspec + s3fs + adlfs
pip install xl-diff[web,remote]  # web UI + remote storage
pip install xl-diff[all]         # everything
```

Without this extra installed, any `s3://`/`az://`/... reference fails fast
with `MissingDependencyError` (web UI returns HTTP 501) telling you which
extra to install — it never falls back to silently treating the URI as a
local path.

## Referencing a remote file

- CLI: pass a URI in place of a local path.
  ```
  sheetdiff s3://my-bucket/reports/2026-01.xlsx s3://my-bucket/reports/2026-02.xlsx --key id
  ```
- Web UI: each file row accepts either an upload *or* a URI in the adjacent
  text field — leave the file input empty and fill in the URI instead.
- Python API: `sheetdiff.resolve_source(uri, dest_dir)` downloads a remote
  object to a local temp file and returns its path; `diff_sheets` etc. still
  only ever see local paths.

Supported schemes: `s3://`, `minio://`, `r2://`, `garage://`, `az://` /
`azure://` (Azure Blob). Anything else — including `http://`/`https://` — is
rejected outright, so the diff endpoint can't be abused as an open proxy to
fetch arbitrary internal or external URLs (see EDGE_CASES.md #83, #46).

## Credentials — never through the web form

Credentials are configured once by whoever deploys xl-diff, via environment
variables. They are **not** accepted as form fields or query parameters —
a user of the web UI can only reference objects inside buckets/containers
the deployment already has credentials for, never supply their own.

### S3 / MinIO / R2 / Garage (all S3-compatible)

Plain AWS S3 uses the standard `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
/ `AWS_DEFAULT_REGION` env vars (or an attached IAM role). For self-hosted
or non-AWS S3-compatible endpoints, set a per-scheme endpoint plus optional
per-scheme credentials — this lets you configure several backends (e.g. both
real S3 and an internal MinIO) at once, each reached by its own scheme:

```
# MinIO
SHEETDIFF_STORAGE_MINIO_ENDPOINT_URL=http://minio.internal:9000
SHEETDIFF_STORAGE_MINIO_KEY=...
SHEETDIFF_STORAGE_MINIO_SECRET=...

# Cloudflare R2
SHEETDIFF_STORAGE_R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
SHEETDIFF_STORAGE_R2_KEY=...
SHEETDIFF_STORAGE_R2_SECRET=...

# Garage
SHEETDIFF_STORAGE_GARAGE_ENDPOINT_URL=https://garage.internal:3900
SHEETDIFF_STORAGE_GARAGE_KEY=...
SHEETDIFF_STORAGE_GARAGE_SECRET=...

# Self-hosted / other S3-compatible reached via the plain s3:// scheme
SHEETDIFF_STORAGE_S3_ENDPOINT_URL=https://s3.example.internal
```

Use whichever scheme matches the backend when referencing a file, e.g.
`minio://my-bucket/file.xlsx`, `r2://my-bucket/file.xlsx`.

### Azure Blob Storage

```
# Either a connection string...
SHEETDIFF_STORAGE_AZ_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...

# ...or account name + key/SAS token
SHEETDIFF_STORAGE_AZ_ACCOUNT_NAME=myaccount
SHEETDIFF_STORAGE_AZ_ACCOUNT_KEY=...
# or
SHEETDIFF_STORAGE_AZ_SAS_TOKEN=...
```

Reference with `az://container/blob.xlsx` (or `azure://...`, an alias).

### Restricting which schemes are enabled

```
SHEETDIFF_ALLOWED_SCHEMES=s3,minio    # only these are ever dispatched remotely
```

Defaults to `s3,minio,r2,garage,az,azure,gs`. Set to an empty string to
disable remote storage entirely regardless of what's installed.

## File size configuration

All limits are set once, at the deployment level, via environment
variables — there's no per-user override, so one user's job can't starve
another's:

| Variable | Default | Meaning |
|---|---|---|
| `SHEETDIFF_MAX_UPLOAD_MB` | 100 | Max size of an uploaded file / total web request body |
| `SHEETDIFF_MAX_REMOTE_MB` | same as upload | Max size of a single remote object, checked both via a `HEAD`-style stat *and* while streaming (in case the reported size lied) |
| `SHEETDIFF_MAX_FILES` | 8 | Max number of files compared in one request (web multi-file view or `--all-sheets`) |
| `SHEETDIFF_REMOTE_CONNECT_TIMEOUT` | 10 | Seconds before a remote connection attempt is abandoned |
| `SHEETDIFF_REMOTE_READ_TIMEOUT` | 60 | Seconds before a stalled remote read is abandoned |

CLI callers can also override the remote cap per-invocation with
`--max-remote-mb`, without touching the deployment's env vars.

Raise these for large internal deployments, e.g.:

```
SHEETDIFF_MAX_UPLOAD_MB=500
SHEETDIFF_MAX_REMOTE_MB=2000
SHEETDIFF_MAX_FILES=4
```

Lower `SHEETDIFF_MAX_FILES` if wide N-way comparisons are causing memory
pressure — each file is loaded fully into a pandas DataFrame in the current
implementation (see "Known limitations" below).

## Failure behavior

| Situation | Web UI | CLI |
|---|---|---|
| Remote extra not installed | 501 | exits 1 with a clear message |
| Disallowed/unknown scheme (incl. `http://`) | 400 | exits 1 |
| Remote object exceeds size cap (reported or while streaming) | 413 | exits 1 |
| Remote object not found / network error | 400 | exits 1 |
| Uploaded request exceeds `SHEETDIFF_MAX_UPLOAD_MB` | 413 | n/a |
| Too many files/URIs in one request | 400 | n/a (CLI is always 2 files) |

Partially-downloaded remote files are always cleaned up, including when a
later file in a multi-file batch fails validation — nothing is left behind
in the temp directory.

## Known limitations / things to budget for

- Every file — local or remote — is still fully materialized on local disk
  and loaded into memory as a pandas DataFrame; remote support changes
  *where the bytes come from*, not the underlying memory model, so very
  large sheets remain bounded by the existing Python-fallback performance
  characteristics (see `RUST_INTEGRATION.md` and `EDGE_CASES.md` #6/#7 for
  the large-sheet path, where the Rust backend is preferred).
- `resolve_many` cleans up files *it* downloaded; it does not delete files
  a caller passes in directly, so callers that manage their own temp
  directories are still responsible for those.
- Presigned/pre-authenticated URLs (a link that already embeds a token) are
  intentionally **not** treated as "remote" here — they're just `https://`
  and are rejected by the scheme allow-list. If you need that, generate the
  presigned URL server-side and reference the object via `s3://`/`az://`
  with normal credentials instead, so the same size caps and timeouts apply.
