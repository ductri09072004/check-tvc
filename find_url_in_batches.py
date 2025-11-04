import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse


def read_url_from_file(url_file: Path) -> str | None:
    try:
        text = url_file.read_text(encoding="utf-8", errors="ignore").strip()
        return text if text else None
    except Exception:
        return None


def extract_url_key(url: str) -> str:
    """
    Build a resilient key for matching:
    - Prefer the `id/<id>` segment if present in the path
    - Fallback to the full URL string
    This handles cases where query params differ but the `id` (e.g., 18bd21c5bf890d8a) stays the same.
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    try:
        idx = path_parts.index("id")
        if idx + 1 < len(path_parts):
            return f"id/{path_parts[idx + 1]}"
    except ValueError:
        pass
    return url.strip()


def match_urls(target_urls: list[str], base_dir: Path) -> dict[str, list[str]]:
    batch_dir = base_dir / "batch_outputs"
    if not batch_dir.exists():
        raise FileNotFoundError(f"Directory not found: {batch_dir}")

    # Prepare target keys
    targets: dict[str, str] = {u: extract_url_key(u) for u in target_urls}

    results: dict[str, list[str]] = {u: [] for u in target_urls}

    # Iterate folders like url_0001/url.txt
    for url_folder in sorted(batch_dir.glob("url_*")):
        url_txt = url_folder / "url.txt"
        if not url_txt.exists():
            continue
        stored = read_url_from_file(url_txt)
        if not stored:
            continue

        stored_key = extract_url_key(stored)

        for original, target_key in targets.items():
            # Exact match first
            if stored.strip() == original.strip():
                results[original].append(url_folder.name)
                continue
            # Fallback to key match (e.g., id/<id>)
            if stored_key and target_key and stored_key == target_key:
                results[original].append(url_folder.name)

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find which batch_outputs/url_XXXX folder(s) contain the given URL(s) "
            "by checking url.txt contents."
        )
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="One or more URLs to search for. If omitted, reads from stdin (one per line).",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=".",
        help="Project root (defaults to current directory).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.urls:
        targets = args.urls
    else:
        # Read from stdin (PowerShell: you can pipe a file)
        targets = [line.strip() for line in sys.stdin if line.strip()]

    if not targets:
        print("No URLs provided. Pass as arguments or via stdin.", file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    try:
        results = match_urls(targets, root)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    for url in targets:
        folders = results.get(url, [])
        if folders:
            print(f"URL: {url}")
            print("  Found in:")
            for folder in folders:
                print(f"    {folder}")
        else:
            print(f"URL: {url}")
            print("  Not found in batch_outputs")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


