
# xl-diff (sheetdiff)

Minimal, efficient spreadsheet diff tool. Load CSV/XLSX and produce unified +/- row and cell diffs.

## Run locally from a clone (web UI)

If you just want to clone the repo and use the web UI on your own machine, without publishing to PyPI:

```bash
git clone https://github.com/muhammadumer0266/xl-diff.git
cd xl-diff

# Create and activate a virtualenv
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Install the package in editable mode with the web extra
pip install -e ".[web]"

# Start the web server
xldiff-web
```

Then open http://localhost:5000, upload two spreadsheets (optionally a key column), and view a GitHub-style row/cell diff (green = added, red = removed, yellow = modified with old value struck through above the new one).

The pure-Python (pandas-based) diff engine works out of the box after `pip install -e ".[web]"`. If you also want the faster Rust-backed engine, additionally run `maturin develop --release` (see "Building the Rust extension" below) before starting `xldiff-web`.

## Install from PyPI (distributed as `sheetdiff`)

```
pip install sheetdiff
```

Quick CLI

```
python -m sheetdiff.cli left.xlsx right.xlsx --key id
```

Web UI (GitHub-style diff viewer)

```
pip install sheetdiff[web]
xldiff-web
```

Open http://localhost:5000, upload two spreadsheets (optionally a key column), and view a GitHub-style row/cell diff (green = added, red = removed, yellow = modified with old value struck through above the new one).

Remote storage (S3, MinIO, Cloudflare R2, Garage, Azure Blob)

```
pip install sheetdiff[remote]
sheetdiff s3://my-bucket/left.xlsx s3://my-bucket/right.xlsx --key id
```

Files can also be referenced by URI in the web UI (each row accepts an upload *or* a URI) and from the Python API via `sheetdiff.resolve_source`. Credentials and per-backend endpoints are configured once via environment variables, never through the web form — see [docs/REMOTE_STORAGE.md](docs/REMOTE_STORAGE.md) for the full list, plus how to configure upload/remote size limits (`SHEETDIFF_MAX_UPLOAD_MB`, `SHEETDIFF_MAX_REMOTE_MB`, `SHEETDIFF_MAX_FILES`).

Python API

```
from sheetdiff.core import diff_sheets, format_unified

changes = diff_sheets('left.csv','right.csv', key='id')
print(format_unified(changes))
```

Functions

- `diff_sheets(left, right, key=None, sheet_name=None)` — compare two files; if `key` provided, rows are matched by that column, otherwise by position. Returns list of tuples `(type, row_key_or_index, column, old, new)`.
- `format_unified(changes)` — render a compact unified +/- text view.

Integration notes

- For web backends (Django/Celery), call `diff_sheets` or `compare_workbooks` inside a worker and serialize `changes` to JSON for paginated display.
- The package will prefer a Rust-backed binary extension `xl_diff` when available (faster, memory-efficient). If the Rust extension is not installed, the pure-Python fallback (`pandas` based) is used.
- For very large files implement the Rust core (see `RUST_INTEGRATION.md`) and build wheels via `maturin` for best performance.

# xl-diff

[![CI](https://github.com/muhammadumer0266/xl-diff/actions/workflows/CI.yml/badge.svg)](https://github.com/muhammadumer0266/xl-diff/actions/workflows/CI.yml)
[![crates.io](https://img.shields.io/crates/v/xl_diff.svg)](https://crates.io/crates/xl_diff)
[![PyPI](https://img.shields.io/pypi/v/sheetdiff.svg)](https://pypi.org/project/sheetdiff/)
[![Language](https://img.shields.io/badge/Language-Rust%20%2F%20Python-orange.svg)](https://www.rust-lang.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

xl-diff is a high-performance, memory-safe Excel comparison engine written in Rust and exposed as a Python extension via PyO3. It is designed to integrate into Django/Celery pipelines and produce cell-level semantic diffs between spreadsheet versions.

Features
- Fast, zero-copy reading of XLSX using `calamine`.
- Parallel diff computation using `rayon`.
- Row alignment using an optional key column or positional fallback.
- Python bindings (PyO3) for seamless integration.
- Cross-platform packaging with `maturin` and GitHub Actions.

## Building the Rust extension

The package prefers a Rust-backed binary extension (`xl_diff`, faster and more memory-efficient) when available, falling back to the pure-Python implementation otherwise. To build it in-place inside your virtualenv:

```bash
pip install maturin
maturin develop --release
```

Python usage

```python
import xl_diff

# List sheets
sheets = xl_diff.get_sheet_names("/path/to/file.xlsx")

# Diff two sheets by key column 0
deltas = xl_diff.diff_sheets(
    "/path/to/old.xlsx",
    "Sheet1",
    "/path/to/new.xlsx",
    "Sheet1",
    0,
)

for d in deltas:
    print(d.row_idx_old, d.row_idx_new, d.col_idx, d.status, d.old_value, d.new_value)
```

Badge & CI

This repository includes GitHub Actions workflows to build manylinux/musllinux and wheels for Windows/macOS, along with an sdist job. The CI badge above links to the main workflow.

Contributing

Please open issues for bugs and feature requests. Pull requests should target the `main` branch; the `issue/traceability-phase2` branch contains traceability and test improvements.

License

MIT
