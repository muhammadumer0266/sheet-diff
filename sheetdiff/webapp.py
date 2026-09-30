"""Web UI: upload two or more spreadsheets, view a GitHub/VSCode-style diff.

Run: python -m sheetdiff.webapp
"""
import os
import tempfile
from flask import Flask, request, render_template

from .core import diff_rows_full, diff_multi_grid, _is_excel
import pandas as pd

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


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
    return render_template("index.html")


@app.route("/diff", methods=["POST"])
def diff():
    uploads = request.files.getlist("files")
    if len(uploads) < 2:
        return "At least two files are required.", 400
    key = request.form.get("key") or None
    header = bool(request.form.get("header"))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        paths, names = [], []
        for i, f in enumerate(uploads):
            p = os.path.join(tmp, f"{i}_{f.filename}")
            f.save(p)
            paths.append(p)
            names.append(f.filename)

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

        # --- Split view: N-way grid per sheet ---
        multi_sheets = {}
        for s in all_sheets:
            present = presence[s]
            try:
                g = diff_multi_grid(paths, present, key=key, sheet_name=s, header=header)
                g["present"] = present
                g["diff_rows"] = sum(1 for r in g["rows"] if r["status"] == "diff")
                multi_sheets[s] = g
            except Exception as e:
                multi_sheets[s] = {"columns": [], "rows": [], "present": present, "error": str(e)}

    return render_template(
        "diff.html",
        file_names=names,
        pairs=pairs,
        all_sheets=all_sheets,
        multi_sheets=multi_sheets,
        multi_file=len(paths) > 2,
    )


def main():
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    main()
