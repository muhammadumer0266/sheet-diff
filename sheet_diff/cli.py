import argparse
import sys
import tempfile

from . import config, storage
from .core import diff_sheets, format_unified, diff_workbook, format_workbook

def main():
    p = argparse.ArgumentParser(prog="sheet-diff")
    p.add_argument("left", help="local path or remote URI (s3://, minio://, r2://, garage://, az://)")
    p.add_argument("right", help="local path or remote URI (s3://, minio://, r2://, garage://, az://)")
    p.add_argument("--key", help="column name to use as row key")
    p.add_argument("--sheet", help="sheet name for Excel files")
    p.add_argument("--all-sheets", action="store_true", help="compare all sheets in workbooks")
    p.add_argument(
        "--max-remote-mb", type=int, default=None,
        help=f"override the remote download size cap (default: {config.MAX_REMOTE_MB} MB, "
             "also settable via SHEET_DIFF_MAX_REMOTE_MB)",
    )
    args = p.parse_args()

    max_bytes = args.max_remote_mb * 1024 * 1024 if args.max_remote_mb else None

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        try:
            left_path = storage.resolve(args.left, tmp, max_bytes=max_bytes)
            right_path = storage.resolve(args.right, tmp, max_bytes=max_bytes)
        except storage.StorageError as e:
            print(f"error: {e}", file=sys.stderr)
            raise SystemExit(1)

        if args.all_sheets:
            from .core import compare_workbooks
            wb = compare_workbooks(left_path, right_path, key=args.key)
            print(format_workbook(wb))
        else:
            changes = diff_sheets(left_path, right_path, key=args.key, sheet_name=args.sheet)
            print(format_unified(changes))


if __name__ == "__main__":
    main()
