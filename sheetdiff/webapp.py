"""Web UI: upload two or more spreadsheets, view a GitHub/VSCode-style diff.

Files can either be uploaded directly or referenced by a remote URI
(s3://, minio://, r2://, garage://, az:///azure://) — see storage.py and
config.py for how remote credentials and size limits are configured.

Run: python -m sheetdiff.webapp
"""
import os
import tempfile
from flask import Flask, request, render_template

from . import config, storage
from .core import diff_rows_full, _is_excel
import pandas as pd

app = Flask(__name__)
# Total request body cap. This bounds *uploaded* bytes; remote downloads are
# capped separately and independently via config.MAX_REMOTE_BYTES, since
# they never pass through the request body.
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES


def _build_items(rows, context=3):
    """Collapse long unchanged runs into fold markers + hunk headers, VSCode-diff style."""
    n = len(rows)
    visible = [False] * n
    for i, r in enumerate(rows):
        if r["status"] != "unchanged":
            for j in range(max(0, i - context), min(n, i + context + 1)):
                visible[j] = True

    items = []
    i = 0
    prev_visible = False
    while i < n:
        if visible[i]:
            if not prev_visible:
                items.append({"type": "hunk", "old_line": rows[i]["old_line"] or 0, "new_line": rows[i]["new_line"] or 0})
            items.append({"type": "row", "row": rows[i]})
            prev_visible = True
            i += 1
        else:
            j = i
            while j < n and not visible[j]:
                j += 1
            items.append({"type": "fold", "count": j - i, "rows": rows[i:j]})
            prev_visible = False
            i = j
    return items


def _sheet_names(path: str):
    if not _is_excel(path):
        return ["sheet"]
    with pd.ExcelFile(path) as xl:
        return xl.sheet_names


@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        remote_enabled=bool(config.ALLOWED_REMOTE_SCHEMES),
        allowed_schemes=sorted(config.ALLOWED_REMOTE_SCHEMES),
        max_upload_mb=config.MAX_UPLOAD_MB,
        max_remote_mb=config.MAX_REMOTE_MB,
        max_files=config.MAX_FILES,
    )


@app.route("/diff", methods=["POST"])
def diff():
    uploads = request.files.getlist("files")
    remote_refs = request.form.getlist("remote_refs")
    # Every row submits both a (possibly empty) file part and a (possibly
    # empty) remote_refs entry, so the two lists line up 1:1 by row.
    if len(remote_refs) < len(uploads):
        remote_refs = remote_refs + [""] * (len(uploads) - len(remote_refs))

    slots = []  # list of (source, display_name) where source is a FileStorage or a remote URI string
    for f, ref in zip(uploads, remote_refs):
        ref = (ref or "").strip()
        if ref:
            slots.append((ref, ref))
        elif f and f.filename:
            slots.append((f, f.filename))

    if len(slots) < 2:
        return "At least two files (uploaded or remote) are required.", 400
    if len(slots) > config.MAX_FILES:
        return (
            f"Too many files: {len(slots)} given, {config.MAX_FILES} allowed "
            "(configure via SHEETDIFF_MAX_FILES).",
            400,
        )
    key = request.form.get("key") or None
    header = bool(request.form.get("header"))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        paths, names = [], []
        try:
            for i, (source, name) in enumerate(slots):
                if isinstance(source, str):
                    p = storage.resolve(source, tmp, max_bytes=config.MAX_REMOTE_BYTES)
                else:
                    p = os.path.join(tmp, f"{i}_{source.filename}")
                    source.save(p)
                paths.append(p)
                names.append(name)
        except storage.MissingDependencyError as e:
            return str(e), 501
        except storage.SchemeNotAllowedError as e:
            return str(e), 400
        except storage.RemoteFileTooLargeError as e:
            return str(e), 413
        except storage.StorageError as e:
            return str(e), 400

        sheet_lists = [_sheet_names(p) for p in paths]

        all_sheets = []
        for sl in sheet_lists:
            for s in sl:
                if s not in all_sheets:
                    all_sheets.append(s)

        presence = {s: [s in sl for sl in sheet_lists] for s in all_sheets}

        # --- Unified view: pairwise consecutive comparisons ---
        pairs = []
        for i in range(len(paths) - 1):
            pair_sheets = {}
            for s in all_sheets:
                l_ok, r_ok = presence[s][i], presence[s][i + 1]
                if not l_ok and not r_ok:
                    continue
                try:
                    d = diff_rows_full(
                        paths[i], paths[i + 1], key=key, sheet_name=s, header=header,
                        left_exists=l_ok, right_exists=r_ok,
                    )
                    d["diff_items"] = _build_items(d["rows"])
                    d["added"] = sum(1 for r in d["rows"] if r["status"] == "added")
                    d["removed"] = sum(1 for r in d["rows"] if r["status"] == "removed")
                    d["modified"] = sum(1 for r in d["rows"] if r["status"] == "modified")
                    d["sheet_status"] = "both" if (l_ok and r_ok) else ("added" if r_ok else "removed")
                    pair_sheets[s] = d
                except Exception as e:
                    pair_sheets[s] = {"columns": [], "rows": [], "diff_items": [], "error": str(e), "sheet_status": "both"}
            pairs.append({"left_name": names[i], "right_name": names[i + 1], "sheets": pair_sheets})

    return render_template(
        "diff.html",
        file_names=names,
        pairs=pairs,
        multi_file=len(paths) > 2,
    )


@app.errorhandler(413)
def too_large(_e):
    return (
        f"Upload too large. The server accepts at most {config.MAX_UPLOAD_MB} MB "
        "per request (configure via SHEETDIFF_MAX_UPLOAD_MB), or use a remote:// "
        "URI so the file doesn't have to pass through the browser.",
        413,
    )


def main():
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    main()
