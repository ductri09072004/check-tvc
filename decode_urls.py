import argparse
import csv
import os
import sys
from urllib.parse import unquote, urlparse


def smart_unquote(value: str) -> str:
    if value is None:
        return ""
    s = value.strip().strip('"').strip("'")
    # Some entries may be quoted full URLs already; decode percent-encodings.
    # Decode twice to handle cases like %253D (encoded '%3D').
    try:
        once = unquote(s)
        twice = unquote(once)
        decoded = twice
    except Exception:
        decoded = s

    # Fix protocol-relative URLs if any
    if decoded.startswith("//"):
        decoded = "https:" + decoded

    return decoded


def looks_like_url(s: str) -> bool:
    try:
        p = urlparse(s)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def decode_file(input_path: str, output_path: str, url_column: str = None) -> int:
    """Decode URLs in CSV while preserving all other columns."""
    count = 0
    with open(input_path, "r", encoding="utf-8", newline="") as fin, open(
        output_path, "w", encoding="utf-8", newline=""
    ) as fout:
        reader = csv.DictReader(fin)
        if not reader.fieldnames:
            return 0
        
        # Determine which column contains URLs
        url_col = None
        if url_column and url_column in reader.fieldnames:
            url_col = url_column
        else:
            # Use first column as default
            url_col = reader.fieldnames[0]
        
        # Write header with all columns (URL column will be decoded)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        
        for row in reader:
            if not row:
                continue
            
            # Decode the URL column
            url_value = row.get(url_col, "").strip()
            if url_value:
                decoded = smart_unquote(url_value)
                if looks_like_url(decoded):
                    row[url_col] = decoded
                else:
                    # Keep original as fallback if decoding doesn't look like a URL
                    row[url_col] = decoded or url_value
            
            # Write all columns
            writer.writerow(row)
            count += 1
    
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode percent-encoded URLs in a CSV while preserving all other columns")
    parser.add_argument("--input", dest="input_path", default="tvc-full.csv", help="Input CSV path (default: tvc-full.csv)")
    parser.add_argument("--output", dest="output_path", default="tvc-full.decoded.csv", help="Output CSV path (default: tvc-full.decoded.csv)")
    parser.add_argument("--column", dest="url_column", default="tvc", help="Column name containing URLs to decode (default: tvc)")
    args = parser.parse_args()

    if not os.path.isfile(args.input_path):
        print(f"Input file not found: {args.input_path}", file=sys.stderr)
        sys.exit(1)

    total = decode_file(args.input_path, args.output_path, url_column=args.url_column)
    print(f"Decoded {total} row(s) → {args.output_path}")


if __name__ == "__main__":
    main()


