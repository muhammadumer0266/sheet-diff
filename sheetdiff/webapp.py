"""Minimal web UI: upload two spreadsheets, view a GitHub-style diff.

Run: python -m sheetdiff.webapp
"""
import os
import tempfile
from flask import Flask, request, render_template

from .core import diff_rows_full, _is_excel
import pandas as pd

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


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
        return [None]
    with pd.ExcelFile(path) as xl:
        return xl.sheet_names


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/diff", methods=["POST"])
def diff():
    left_file = request.files["left"]
    right_file = request.files["right"]
    key = request.form.get("key") or None
    header = bool(request.form.get("header"))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        lpath = os.path.join(tmp, left_file.filename)
        rpath = os.path.join(tmp, right_file.filename)
        left_file.save(lpath)
        right_file.save(rpath)

        left_sheets = _sheet_names(lpath)
        right_sheets = _sheet_names(rpath)
        all_sheets = list(dict.fromkeys([s for s in left_sheets + right_sheets if s is not None])) or [None]

        sheets = {}
        for s in all_sheets:
            try:
                d = diff_rows_full(lpath, rpath, key=key, sheet_name=s, header=header)
                d["diff_items"] = _build_items(d["rows"])
                d["added"] = sum(1 for r in d["rows"] if r["status"] == "added")
                d["removed"] = sum(1 for r in d["rows"] if r["status"] == "removed")
                d["modified"] = sum(1 for r in d["rows"] if r["status"] == "modified")
                sheets[s or "sheet"] = d
            except Exception as e:
                sheets[s or "sheet"] = {"columns": [], "rows": [], "diff_items": [], "error": str(e)}

    return render_template(
        "diff.html",
        sheets=sheets,
        left_name=left_file.filename,
        right_name=right_file.filename,
    )


def main():
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    main()
