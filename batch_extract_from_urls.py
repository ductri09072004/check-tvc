import argparse
import csv
import os
import sys
import tempfile
import time
from typing import Optional

import cv2
from PIL import Image

from app import ensure_dir, embed_image_clip_to_npy


def safe_slug(text: str) -> str:
    s = (text or "").strip()
    allowed = []
    for ch in s:
        if ch.isalnum() or ch in " .-_()[]{}":
            allowed.append(ch)
        else:
            allowed.append("_")
    slug = "".join(allowed).strip()
    return slug or "item"


def read_urls(csv_path: str, column: Optional[str]) -> list[dict]:
    """Read CSV and return list of dicts with all columns."""
    rows: list[dict] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Get URL from specified column or first column
            url = None
            if column and column in row:
                url = (row.get(column) or "").strip()
            else:
                # Fallback: first column
                first_col = list(row.values())[0] if row else ""
                url = (first_col or "").strip()
            
            if url:
                rows.append(row)
    return rows


def detect_media_type(url: str) -> str:
    """Detect if URL is an image or video based on extension and Content-Type."""
    url_lower = url.lower()
    # Check extension first
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.tiff', '.tif'}
    video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v', '.3gp'}
    
    # Check extension in URL path (before query params)
    path_part = url_lower.split('?')[0].split('#')[0]
    for ext in image_exts:
        if ext in path_part:
            return 'image'
    for ext in video_exts:
        if ext in path_part:
            return 'video'
    
    # Try to detect from Content-Type header (without downloading full file)
    try:
        import requests  # type: ignore
        head_response = requests.head(url, timeout=10, allow_redirects=True)
        content_type = head_response.headers.get('Content-Type', '').lower()
        if any(img_type in content_type for img_type in ['image/', 'image']):
            return 'image'
        if any(vid_type in content_type for vid_type in ['video/', 'video']):
            return 'video'
    except Exception:
        pass
    
    # Default to video if cannot determine (for backward compatibility)
    return 'video'


def download_file(url: str, dest_path: str) -> tuple[str, Optional[str]]:
    """Download file (image or video) from URL. Returns (media_type, error)."""
    # Try requests first, fallback to urllib
    try:
        import requests  # type: ignore
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            # Detect media type from Content-Type
            content_type = r.headers.get('Content-Type', '').lower()
            media_type = None
            if any(img_type in content_type for img_type in ['image/', 'image']):
                media_type = 'image'
            elif any(vid_type in content_type for vid_type in ['video/', 'video']):
                media_type = 'video'
            else:
                # Fallback to URL-based detection
                media_type = detect_media_type(url)
            
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return media_type, None
    except Exception as e:
        error_msg = str(e)
        # Try to still determine media type from URL
        media_type = detect_media_type(url)
        return media_type, error_msg

    # Fallback urllib
    try:
        from urllib.request import urlopen
        with urlopen(url, timeout=60) as r, open(dest_path, "wb") as f:
            while True:
                chunk = r.read(8192)
                if not chunk:
                    break
                f.write(chunk)
        media_type = detect_media_type(url)
        return media_type, None
    except Exception as e:
        media_type = detect_media_type(url)
        return media_type, f"Download failed: {e}"


def process_url(index: int, row_data: dict, url_column: Optional[str], out_root: str, overwrite: bool) -> tuple[str, int, Optional[str]]:
    """Process a single URL row with all metadata."""
    # Get URL from specified column or first column
    url = None
    if url_column and url_column in row_data:
        url = (row_data.get(url_column) or "").strip()
    else:
        first_col = list(row_data.values())[0] if row_data else ""
        url = (first_col or "").strip()
    
    if not url:
        return f"url_{index:04d}", 0, "no_url_in_row"
    
    job_id = f"url_{index:04d}"
    job_dir = os.path.join(out_root, job_id)
    # Save only the embedding (no frame image saved in repo)
    first_embed_path = os.path.join(job_dir, "first_frame.npy")
    url_txt_path = os.path.join(job_dir, "url.txt")
    metadata_txt_path = os.path.join(job_dir, "metadata.txt")
    media_type_path = os.path.join(job_dir, "media_type.txt")
    ensure_dir(job_dir)
    if overwrite:
        try:
            if os.path.exists(first_embed_path):
                os.remove(first_embed_path)
        except Exception:
            pass
        try:
            if os.path.exists(url_txt_path):
                os.remove(url_txt_path)
        except Exception:
            pass
        try:
            if os.path.exists(metadata_txt_path):
                os.remove(metadata_txt_path)
        except Exception:
            pass
        try:
            if os.path.exists(media_type_path):
                os.remove(media_type_path)
        except Exception:
            pass

    # Persist the source URL into the job folder
    try:
        with open(url_txt_path, "w", encoding="utf-8") as f:
            f.write(url)
    except Exception:
        pass

    # Save all metadata (fid, cid, adid, etc.) to metadata.txt
    try:
        with open(metadata_txt_path, "w", encoding="utf-8") as f:
            for key, value in row_data.items():
                if key != url_column:  # Skip URL column as it's already in url.txt
                    f.write(f"{key}={value}\n")
    except Exception:
        pass

    # Download to temp file and detect media type
    with tempfile.TemporaryDirectory() as tdir:
        # Determine appropriate file extension based on URL
        url_lower = url.lower()
        if any(ext in url_lower for ext in ['.jpg', '.jpeg']):
            default_ext = '.jpg'
        elif '.png' in url_lower:
            default_ext = '.png'
        elif any(ext in url_lower for ext in ['.gif', '.webp', '.bmp']):
            default_ext = '.gif'  # Will be determined by actual content
        else:
            default_ext = '.mp4'  # Default to video
        
        tmp_path = os.path.join(tdir, safe_slug(os.path.basename(url)) or f"media{default_ext}")
        
        media_type, download_error = download_file(url, tmp_path)
        if download_error:
            return job_id, 0, f"download_error: {download_error}"
        
        # Save media type
        try:
            with open(media_type_path, "w", encoding="utf-8") as f:
                f.write(media_type)
        except Exception:
            pass
        
        temp_frame_path = os.path.join(tdir, "first_frame.png")
        
        if media_type == 'image':
            # For images, use directly
            try:
                # Validate and convert image if needed
                img = Image.open(tmp_path)
                # Convert to RGB if needed (for formats like RGBA, P, etc.)
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                img.save(temp_frame_path, 'PNG')
            except Exception as e:
                return job_id, 0, f"image_process_error: {e}"
        else:
            # For videos, extract first frame
            try:
                cap = cv2.VideoCapture(tmp_path)
                if not cap.isOpened():
                    return job_id, 0, "video_open_error"
                cap.set(cv2.CAP_PROP_POS_MSEC, 0)
                success, frame = cap.read()
                if not success or frame is None:
                    cap.release()
                    return job_id, 0, "read_first_frame_error"
                # Save first frame to temp path (not in repo) only to compute embedding
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                img.save(temp_frame_path)
                cap.release()
            except Exception as e:
                return job_id, 0, f"first_frame_error: {e}"

        # Compute embedding for the image/first frame
        try:
            embed_image_clip_to_npy(temp_frame_path, first_embed_path, model_id="openai/clip-vit-base-patch32")
        except Exception as e:
            return job_id, 1, f"embed_error: {e}"

    return job_id, 1, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch download videos/images from CSV URLs, extract first frame (for videos) or use directly (for images), and save CLIP embedding")
    parser.add_argument("--input", default="tvc-full-decoded.csv", help="CSV path containing URLs (default: tvc-full.csv)")
    parser.add_argument("--column", default="tvc", help="Column name containing URLs (default: tvc)")
    parser.add_argument("--out_dir", default="batch_outputs", help="Output directory for per-URL embeddings (default: batch_outputs)")
    parser.add_argument("--start", type=int, default=0, help="Start index (inclusive) in URL list (default: 0)")
    parser.add_argument("--end", type=int, default=None, help="End index (exclusive) in URL list (default: None)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing embeddings for a job")
    args = parser.parse_args()

    # Check if input file exists
    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found.", file=sys.stderr)
        print(f"Please specify a valid CSV file with --input option.", file=sys.stderr)
        sys.exit(1)

    ensure_dir(args.out_dir)
    rows = read_urls(args.input, args.column)
    if args.end is None or args.end > len(rows):
        end = len(rows)
    else:
        end = args.end
    start = max(0, args.start)
    if start >= end:
        print("No URLs to process in the given range.", file=sys.stderr)
        sys.exit(1)

    print(f"Processing URLs {start}..{end-1} out of {len(rows)} total (supports both images and videos)")
    successes = 0
    failures = 0
    t0 = time.time()
    for i in range(start, end):
        row_data = rows[i]
        job_id, num_frames, err = process_url(i, row_data, args.column, args.out_dir, args.overwrite)
        if err:
            failures += 1
            print(f"[{i}] {job_id} FAIL ({err})")
        else:
            successes += 1
            print(f"[{i}] {job_id} OK - {num_frames} frame(s)")

    dt = time.time() - t0
    print(f"Done. OK={successes}, FAIL={failures}, elapsed={dt:.1f}s")


if __name__ == "__main__":
    main()


