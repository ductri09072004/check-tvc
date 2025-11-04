import argparse
import csv
import os
import sys
from urllib.parse import urlparse


def normalize_url(u: str) -> str:
    s = (u or "").strip().strip('"').strip("'")
    # Basic normalization: collapse scheme/host case, drop trailing slash (path only), keep query intact
    try:
        p = urlparse(s)
        scheme = (p.scheme or "").lower()
        netloc = (p.netloc or "").lower()
        path = p.path or ""
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        # Keep params, query, fragment as-is to avoid over-merging distinct assets
        rebuilt = f"{scheme}://{netloc}{path}"
        if p.params:
            rebuilt += f";{p.params}"
        if p.query:
            rebuilt += f"?{p.query}"
        if p.fragment:
            rebuilt += f"#{p.fragment}"
        return rebuilt or s
    except Exception:
        return s


def find_duplicates(input_path: str) -> tuple[int, dict[str, list[str]]]:
    total = 0
    buckets: dict[str, list[str]] = {}

    with open(input_path, "r", encoding="utf-8", newline="") as fin:
        reader = csv.reader(fin)
        rows = list(reader)

    # detect and skip header (expects first column to be a URL with header like tvc/url/decoded_url)
    start_idx = 0
    if rows:
        first = (rows[0][0] if rows[0] else "").strip().lower()
        if first in {"decoded_url", "url", "tvc", "links"}:
            start_idx = 1

    for i in range(start_idx, len(rows)):
        total += 1
        cell = (rows[i][0] if rows[i] else "").strip()
        if not cell:
            continue
        norm = normalize_url(cell)
        buckets.setdefault(norm, []).append(cell)

    dup_map = {k: v for k, v in buckets.items() if len(v) > 1}
    return total, dup_map


def main() -> None:
    parser = argparse.ArgumentParser(description="Check and list duplicate URLs in a CSV (first column)")
    parser.add_argument("--input", dest="input_path", default="unique_urls.csv", help="Input CSV path to check (default: unique_urls.csv)")
    args = parser.parse_args()

    if not os.path.isfile(args.input_path):
        print(f"Input file not found: {args.input_path}", file=sys.stderr)
        sys.exit(1)

    total, dup_map = find_duplicates(args.input_path)
    if not dup_map:
        print(f"No duplicates found. Checked {total} row(s).")
        return

    dup_keys = len(dup_map)
    dup_rows = sum(len(v) for v in dup_map.values())
    print(f"Found {dup_keys} duplicate URL key(s), {dup_rows} duplicated row(s), out of {total} row(s).")
    print()
    for norm, originals in sorted(dup_map.items(), key=lambda x: -len(x[1])):
        print(f"Count {len(originals)} -> {norm}")
        # show up to first 3 originals for visibility
        for o in originals[:3]:
            print(f"  - {o}")
        if len(originals) > 3:
            print(f"  ... and {len(originals) - 3} more")


if __name__ == "__main__":
    main()


