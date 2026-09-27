from typing import List, Tuple, Optional, Any, Dict
import pandas as pd
import json

# Optional Rust backend (xl_diff) if built and installed
_RUST_AVAILABLE = False
_rust = None
try:
    import xl_diff as _rust  # rust extension built via maturin/pyo3
    _RUST_AVAILABLE = True
except Exception:
    _RUST_AVAILABLE = False

def _load(path: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
    if str(path).lower().endswith(('.xls', '.xlsx', '.xlsm')):
        return pd.read_excel(path, sheet_name=sheet_name if sheet_name is not None else 0, dtype=object)
    return pd.read_csv(path, dtype=object)

def _col_letter(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA ... (Excel-style column naming)."""
    s = ""
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s

def _load_grid(path: str, sheet_name: Optional[str] = None, header: bool = False) -> pd.DataFrame:
    """Load a sheet as a raw cell grid (no assumed header row) unless header=True.

    Every spreadsheet row becomes a data row, and columns are labelled A, B, C...
    matching real Excel column letters, so line numbers line up with actual rows.
    """
    is_excel = str(path).lower().endswith(('.xls', '.xlsx', '.xlsm'))
    read_header = 0 if header else None
    if is_excel:
        df = pd.read_excel(path, sheet_name=sheet_name if sheet_name is not None else 0, dtype=object, header=read_header)
    else:
        df = pd.read_csv(path, dtype=object, header=read_header)
    if not header:
        df.columns = [_col_letter(i) for i in range(len(df.columns))]
    return df

def _norm(df: pd.DataFrame) -> pd.DataFrame:
    return df.fillna("").astype(str)

Change = Tuple[str, Any, Optional[str], Optional[str], Optional[str]]

def diff_sheets(left: str, right: str, key: Optional[str] = None, sheet_name: Optional[str] = None) -> List[Change]:
    """Return list of changes: (type, row_key_or_index, column, old, new).
    Types: 'added_row','removed_row','modified_cell'.
    """
    L = _norm(_load(left, sheet_name))
    R = _norm(_load(right, sheet_name))

    changes: List[Change] = []
    if key:
        L2 = L.set_index(key)
        R2 = R.set_index(key)
        all_keys = list(sorted(set(L2.index).union(R2.index)))
        for k in all_keys:
            inL = k in L2.index
            inR = k in R2.index
            if not inL:
                changes.append(("added_row", k, None, None, None))
                continue
            if not inR:
                changes.append(("removed_row", k, None, None, None))
                continue
            lrow = L2.loc[k]
            rrow = R2.loc[k]
            cols = sorted(set(lrow.index).union(rrow.index))
            for c in cols:
                a = str(lrow.get(c, ""))
                b = str(rrow.get(c, ""))
                if a != b:
                    changes.append(("modified_cell", k, c, a, b))
    else:
        maxr = max(len(L), len(R))
        for i in range(maxr):
            if i >= len(L):
                changes.append(("added_row", i, None, None, None)); continue
            if i >= len(R):
                changes.append(("removed_row", i, None, None, None)); continue
            lrow = L.iloc[i]
            rrow = R.iloc[i]
            cols = sorted(set(lrow.index).union(rrow.index))
            for c in cols:
                a = str(lrow.get(c, ""))
                b = str(rrow.get(c, ""))
                if a != b:
                    changes.append(("modified_cell", i, c, a, b))
    return changes

def _is_excel(path: str) -> bool:
    return str(path).lower().endswith(('.xls', '.xlsx', '.xlsm'))

def diff_workbook(left: str, right: str, key: Optional[str] = None) -> Dict[str, List[Change]]:
    """Compare workbooks across all sheets. Returns dict: sheet_name -> changes."""
    # If neither is excel, fallback to single-sheet comparison named 'sheet'
    if not (_is_excel(left) or _is_excel(right)):
        return {"sheet": diff_sheets(left, right, key=key)}

    left_sheets = []
    right_sheets = []
    if _is_excel(left):
        with pd.ExcelFile(left) as xl:
            left_sheets = xl.sheet_names
    else:
        left_sheets = ["sheet"]
    if _is_excel(right):
        with pd.ExcelFile(right) as xl:
            right_sheets = xl.sheet_names
    else:
        right_sheets = ["sheet"]

    all_sheets = list(dict.fromkeys(list(left_sheets) + list(right_sheets)))
    result: Dict[str, List[Change]] = {}
    for s in all_sheets:
        # If a sheet is missing in one workbook, represent as added/removed row marker
        Lpath = left
        Rpath = right
        if s not in left_sheets:
            # left missing: represent as empty file vs sheet in right
            # create an empty CSV temp via pandas for comparison fallback
            empty = pd.DataFrame()
            empty.to_csv(f".tmp_empty_{s}.csv", index=False)
            Lpath = f".tmp_empty_{s}.csv"
        if s not in right_sheets:
            empty = pd.DataFrame()
            empty.to_csv(f".tmp_empty_{s}.csv", index=False)
            Rpath = f".tmp_empty_{s}.csv"
        result[s] = diff_sheets(Lpath, Rpath, key=key, sheet_name=s)
    return result


def compare_workbooks(left: str, right: str, key: Optional[str] = None) -> Dict[str, List[Change]]:
    """High-level comparator that prefers a Rust backend when available.

    Returns a mapping of sheet_name -> list of Change tuples.
    """
    if _RUST_AVAILABLE:
        try:
            # rust function returns JSON string report
            raw = _rust.compare_workbooks_json(left, right, None, None)
            report = json.loads(raw)
            out: Dict[str, List[Change]] = {}
            for sheet in report.get("sheets", []):
                name = sheet.get("sheet_name")
                deltas = []
                for d in sheet.get("cell_deltas", []):
                    status = d.get("status")
                    row_old = d.get("row_idx_old")
                    row_new = d.get("row_idx_new")
                    col = d.get("col_idx")
                    oldv = d.get("old_value")
                    newv = d.get("new_value")
                    if status == "Added":
                        deltas.append(("added_row", row_new, None, None, None))
                    elif status == "Deleted":
                        deltas.append(("removed_row", row_old, None, None, None))
                    else:
                        deltas.append(("modified_cell", row_new if row_new is not None else row_old, col, oldv, newv))
                out[name] = deltas
            return out
        except Exception:
            # On any rust failure, fallback to Python implementation
            pass

    return diff_workbook(left, right, key=key)

def diff_rows_full(left: str, right: str, key: Optional[str] = None, sheet_name: Optional[str] = None, header: bool = False) -> Dict[str, Any]:
    """Full row-level diff for GitHub-style rendering.

    By default every spreadsheet row is treated as data (no assumed header row),
    so line numbers match real Excel row numbers and columns are labelled A, B, C...
    Pass header=True to treat row 1 as column names instead (then `key` is a column name).

    Returns {"columns": [...], "rows": [{"status": "unchanged"|"added"|"removed"|"modified",
    "left": {col: val}, "right": {col: val}, "changed": [col, ...]}, ...]}.
    """
    L = _norm(_load_grid(left, sheet_name, header=header))
    R = _norm(_load_grid(right, sheet_name, header=header))
    columns = list(dict.fromkeys(list(L.columns) + list(R.columns)))
    rows: List[Dict[str, Any]] = []

    def row_dict(row, key_val=None) -> Dict[str, str]:
        d = {c: str(row.get(c, "")) for c in columns}
        if key_val is not None:
            d[key] = str(key_val)
        return d

    if key and key in L.columns and key in R.columns:
        L2, R2 = L.set_index(key), R.set_index(key)
        for k in sorted(set(L2.index) | set(R2.index)):
            inL, inR = k in L2.index, k in R2.index
            if inL and not inR:
                rows.append({"status": "removed", "left": row_dict(L2.loc[k], k), "right": None, "changed": []})
            elif inR and not inL:
                rows.append({"status": "added", "left": None, "right": row_dict(R2.loc[k], k), "changed": []})
            else:
                lrow, rrow = row_dict(L2.loc[k], k), row_dict(R2.loc[k], k)
                changed = [c for c in columns if lrow.get(c) != rrow.get(c)]
                rows.append({"status": "modified" if changed else "unchanged", "left": lrow, "right": rrow, "changed": changed})
    else:
        maxr = max(len(L), len(R))
        for i in range(maxr):
            if i >= len(L):
                rows.append({"status": "added", "left": None, "right": row_dict(R.iloc[i]), "changed": []}); continue
            if i >= len(R):
                rows.append({"status": "removed", "left": row_dict(L.iloc[i]), "right": None, "changed": []}); continue
            lrow, rrow = row_dict(L.iloc[i]), row_dict(R.iloc[i])
            changed = [c for c in columns if lrow.get(c) != rrow.get(c)]
            rows.append({"status": "modified" if changed else "unchanged", "left": lrow, "right": rrow, "changed": changed})

    old_ln = new_ln = 0
    for r in rows:
        if r["status"] in ("removed", "modified", "unchanged"):
            old_ln += 1
            r["old_line"] = old_ln
        else:
            r["old_line"] = None
        if r["status"] in ("added", "modified", "unchanged"):
            new_ln += 1
            r["new_line"] = new_ln
        else:
            r["new_line"] = None

    return {"columns": columns, "rows": rows}


def format_unified(changes: List[Change]) -> str:
    out: List[str] = []
    for t, r, col, a, b in changes:
        if t == "added_row":
            out.append(f"+ ROW {r}")
        elif t == "removed_row":
            out.append(f"- ROW {r}")
        else:
            out.append(f"- {r} | {col} = {a}")
            out.append(f"+ {r} | {col} = {b}")
    return "\n".join(out)

def format_workbook(changes_map: Dict[str, List[Change]]) -> str:
    parts: List[str] = []
    for sheet, changes in changes_map.items():
        parts.append(f"--- Sheet: {sheet} ---")
        parts.append(format_unified(changes) or "(no changes)")
    return "\n\n".join(parts)
