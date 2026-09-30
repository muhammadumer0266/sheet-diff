# sheet-diff

[![CI](https://github.com/muhammadumer0266/sheet-diff/actions/workflows/CI.yml/badge.svg)](https://github.com/muhammadumer0266/sheet-diff/actions/workflows/CI.yml)
[![PyPI](https://img.shields.io/pypi/v/sheetdiff.svg)](https://pypi.org/project/sheetdiff/)
[![Language](https://img.shields.io/badge/Language-Rust%20%2F%20Python-orange.svg)](https://www.rust-lang.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A high-performance, memory-safe spreadsheet diff tool. Load CSV/XLSX files and get unified +/- row and cell diffs — from the command line, from Python, or from a GitHub/VS Code-style web UI.

The diff engine is pure Python (pandas-based) by default, with an optional Rust-backed extension (via `calamine` + `rayon` + PyO3) for large files. Both ship the same API; the Rust extension is used automatically when available and falls back silently otherwise.

- Fast, zero-copy reading of XLSX using `calamine`
- Parallel diff computation using `rayon`
- Row alignment by an optional key column, or positional fallback
- Cell-level, not just row-level, diffs
- A web UI with unified and side-by-side (VS Code-style, synced scroll) views
- Optional remote file support (S3, MinIO, Cloudflare R2, Garage, Azure Blob)

## Installation

```bash
pip install sheetdiff[all]     # recommended: CLI + Python API + web UI + remote storage
```

Only need part of it? Install a specific extra instead:

```bash
pip install sheetdiff[cli]     # CLI + Python API only, no web UI or remote storage deps
pip install sheetdiff[web]     # CLI + Python API + local web UI
pip install sheetdiff[remote]  # CLI + Python API + S3 / MinIO / R2 / Garage / Azure Blob support
```

## Usage

### Command line

```bash
python -m sheetdiff.cli left.xlsx right.xlsx --key id
```

### Python API

```python
from sheetdiff.core import diff_sheets, format_unified

changes = diff_sheets("left.csv", "right.csv", key="id")
print(format_unified(changes))
```

- `diff_sheets(left, right, key=None, sheet_name=None)` — compare two files; if `key` is given, rows are matched by that column's value, otherwise by position. Returns a list of tuples `(type, row_key_or_index, column, old, new)`.
- `format_unified(changes)` — render a compact unified +/- text view.

For web backends (Django/Celery, etc.), call `diff_sheets` or `compare_workbooks` inside a worker and serialize `changes` to JSON for paginated display.

### Web UI

```bash
pip install sheetdiff[web]
xldiff-web
```

Open `http://localhost:5000`, upload two (or more) spreadsheets (optionally with a key column), and view a GitHub-style diff: green = added, red = removed, yellow = modified (old value struck through above the new one). Switch between a unified view and a VS Code-style split view with synced scrolling.

### Remote storage

```bash
pip install sheetdiff[remote]
sheetdiff s3://my-bucket/left.xlsx s3://my-bucket/right.xlsx --key id
```

Files can also be referenced by URI in the web UI (each row accepts an upload *or* a URI) and from the Python API via `sheetdiff.resolve_source`. Credentials and per-backend endpoints are configured once via environment variables, never through the web form — see [docs/REMOTE_STORAGE.md](docs/REMOTE_STORAGE.md) for the full list, plus how to configure upload/remote size limits (`SHEETDIFF_MAX_UPLOAD_MB`, `SHEETDIFF_MAX_REMOTE_MB`, `SHEETDIFF_MAX_FILES`).

## Running from source (git clone)

Use this if you want to hack on the code, or run the web UI locally without publishing anywhere.

```bash
git clone https://github.com/muhammadumer0266/sheet-diff.git
cd sheet-diff

python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e ".[web]"
xldiff-web
```

That installs the pure-Python engine and starts the web UI at `http://localhost:5000`. To also build the faster Rust-backed engine in-place (optional):

```bash
pip install maturin
maturin develop --release
```

Run the test suite with:

```bash
pip install -e ".[web]" pytest
pytest
```

### Using the Rust core directly

The Rust extension can also be used on its own, independent of the `sheetdiff` Python package:

```python
import xl_diff

sheets = xl_diff.get_sheet_names("/path/to/file.xlsx")

deltas = xl_diff.diff_sheets(
    "/path/to/old.xlsx", "Sheet1",
    "/path/to/new.xlsx", "Sheet1",
    0,  # key column index
)
for d in deltas:
    print(d.row_idx_old, d.row_idx_new, d.col_idx, d.status, d.old_value, d.new_value)
```

This repository's GitHub Actions workflows build manylinux/musllinux and Windows/macOS wheels plus an sdist for the Rust extension; the CI badge above links to that workflow.

## Contributing

Please open issues for bugs and feature requests. Pull requests should target the `main` branch; the `issue/traceability-phase2` branch contains traceability and test improvements.

## License

MIT — see [LICENSE](LICENSE).
