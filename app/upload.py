#!/usr/bin/env python3
"""
Baidu Yunpan upload tool (standalone CLI).

    # Single file (with retry)
    python -m app.upload video.ts --retries 5

    # Directory with resume, 5 parallel workers
    python -m app.upload ./my_videos /apps/movies/my_videos -w 5

    # Skip files larger than 100MB
    python -m app.upload ./my_videos /apps/movies/my_videos --max-size 100MB

    # Keep local file after upload
    python -m app.upload video.ts --no-delete-after-upload

上传逻辑（含重试）由 app.services.baiduyun_upload.BaiduYunUploader 提供，
本模块只是参数解析与进度展示的 CLI 外壳。
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

from config.settings import settings
from app.services.baiduyun_upload import BaiduYunUploader


# ── Constants ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_REMOTE_PREFIX = settings.yun_path_prefix
PROGRESS_FILENAME = ".yunpan_upload_progress.json"

DEFAULT_RETRIES = 5
DEFAULT_WORKERS = 5


# ── Helpers ────────────────────────────────────────────────────────────────

def load_access_token(env_file: str | None = None) -> str:
    """Load ACCESS_TOKEN from a .env file.  Exit if not found."""
    env_path = Path(env_file or DEFAULT_ENV_FILE)

    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path))

    token = os.getenv("ACCESS_TOKEN")
    if not token:
        print(
            f"ERROR: ACCESS_TOKEN not set. "
            f"Place it in {env_path} or use --token.",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def _human_size(num_bytes: int) -> str:
    """Pretty-print file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def _error_detail(exc: Exception) -> str:
    """Extract a short error message for display."""
    msg = str(exc).strip()
    return msg[:120]


# ── Progress tracking (directory resume) ───────────────────────────────────

def _progress_path(local_dir: Path) -> Path:
    return local_dir / PROGRESS_FILENAME


def _load_progress(local_dir: Path, remote_dir: str) -> set[str]:
    """Return the set of already-uploaded filenames.

    If the progress file doesn't exist, is unreadable, or was written for
    a *different* remote directory, return an empty set and remove the stale
    file.
    """
    pp = _progress_path(local_dir)
    if not pp.exists():
        return set()
    try:
        data = json.loads(pp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    if data.get("remote_prefix") != remote_dir:
        tqdm.write("[resume] Remote path changed — starting fresh.")
        pp.unlink(missing_ok=True)
        return set()
    return set(data.get("uploaded", []))


def _save_progress(local_dir: Path, remote_dir: str, uploaded: set[str]) -> None:
    """Persist the set of uploaded filenames to the progress file."""
    _progress_path(local_dir).write_text(
        json.dumps(
            {
                "remote_prefix": remote_dir,
                "uploaded": sorted(uploaded),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _clear_progress(local_dir: Path) -> None:
    """Remove the progress file (called when all uploads succeed)."""
    _progress_path(local_dir).unlink(missing_ok=True)


# ── Single-file upload ─────────────────────────────────────────────────────

async def upload_file(
    svc: BaiduYunUploader,
    local_path: str,
    remote_path: str,
    ondup: str,
    max_retries: int,
    max_size: int | None = None,
    delete_after_upload: bool = True,
) -> dict:
    """Upload a single file to Baidu Yunpan (with retry)."""
    local = Path(local_path)

    if not local.exists():
        print(f"ERROR: file not found: {local_path}", file=sys.stderr)
        sys.exit(1)
    if not local.is_file():
        print(f"ERROR: not a regular file: {local_path}", file=sys.stderr)
        sys.exit(1)

    size = local.stat().st_size

    # Check file size limit
    if max_size is not None and size > max_size:
        print(f"SKIPPED: {local}  ({_human_size(size)}) - exceeds size limit of {_human_size(max_size)}")
        return {
            'skipped': True,
            'path': str(local),
            'size': size,
            'reason': f'Exceeds size limit of {max_size} bytes'
        }

    print(f"Uploading: {local}  ({_human_size(size)})")
    print(f"Target:    {remote_path}")
    if max_retries > 0:
        print(f"Retries:   {max_retries}")
    print()

    result = await svc.upload_file(str(local), remote_path, ondup=ondup, max_retries=max_retries)

    print()
    print("Upload successful!")
    print(f"  fs_id: {result.get('fs_id', 'N/A')}")
    print(f"  path:  {result.get('path', 'N/A')}")
    print(f"  size:  {result.get('size', 'N/A')}")
    if result.get("md5"):
        print(f"  md5:   {result['md5']}")

    # Delete local file after successful upload if requested
    if delete_after_upload:
        try:
            local.unlink()
            print(f"  Local file deleted: {local}")
        except OSError as e:
            print(f"  WARNING: Failed to delete local file {local}: {e}", file=sys.stderr)

    return result


# ── Directory upload ───────────────────────────────────────────────────────

async def upload_directory(
    svc: BaiduYunUploader,
    local_dir: str,
    remote_dir: str,
    ondup: str,
    resume: bool,
    workers: int,
    max_retries: int,
    max_size: int | None = None,
) -> None:
    """Upload every ordinary file in *local_dir* to *remote_dir*.

    - **resume**: skip already-uploaded files (persisted in *local_dir*).
    - **workers**: number of parallel uploads (default 5).
    - **max_retries**: per-file retry count with exponential backoff.
    """
    local = Path(local_dir).resolve()

    if not local.exists():
        print(f"ERROR: directory not found: {local_dir}", file=sys.stderr)
        sys.exit(1)
    if not local.is_dir():
        print(f"ERROR: not a directory: {local_dir}", file=sys.stderr)
        sys.exit(1)

    all_files = sorted(
        [p for p in local.iterdir() if p.is_file() and p.name != PROGRESS_FILENAME],
        key=lambda p: p.name,
    )

    if not all_files:
        print(f"No files found in {local}")
        return

    # Filter files by size limit
    if max_size is not None:
        size_skipped = [f for f in all_files if f.stat().st_size > max_size]
        if size_skipped:
            print(f"Size limit: {_human_size(max_size)} - skipping {len(size_skipped)} file(s) that exceed limit:")
            for fpath in size_skipped:
                print(f"  SKIPPED: {fpath.name} ({_human_size(fpath.stat().st_size)})")
            print()
        all_files = [f for f in all_files if f.stat().st_size <= max_size]

    if not all_files:
        print("No files to upload after filtering.")
        return

    remote_dir = remote_dir.rstrip("/") + "/"

    print(f"Local dir:  {local}")
    print(f"Remote dir: {remote_dir}")
    print(f"Files:      {len(all_files)}")
    print(f"Workers:    {workers}")
    if max_retries > 0:
        print(f"Retries:    {max_retries}")
    if max_size is not None:
        print(f"Size limit: {_human_size(max_size)}")
    print()

    # ── Resume state ─────────────────────────────────────────────────
    uploaded: set[str] = set()
    if resume:
        uploaded = _load_progress(local, remote_dir)
        if uploaded:
            tqdm.write(
                f"[resume] {len(uploaded)} file(s) already uploaded — skipping.\n"
            )

    # Build pending list and skip count
    pending = [f for f in all_files if f.name not in uploaded]
    skipped = len(all_files) - len(pending)

    if not pending:
        print("All files already uploaded — nothing to do.")
        if resume:
            _clear_progress(local)
            print("[resume] Progress record cleared.")
        return

    success = 0
    failed = 0
    failed_details: list[tuple[str, str]] = []

    semaphore = asyncio.Semaphore(workers)

    async def upload_one(fpath: Path) -> tuple[Path, Exception | None]:
        async with semaphore:
            try:
                await svc.upload_file(str(fpath), remote_dir + fpath.name, ondup=ondup, max_retries=max_retries)
                return fpath, None
            except Exception as exc:
                return fpath, exc

    # ── Upload with tqdm ─────────────────────────────────────────────
    with tqdm(
        total=len(all_files),
        desc="Uploading",
        unit="file",
        initial=skipped,
        ncols=100,
    ) as pbar:

        async def finish(fpath: Path, exc: Exception | None) -> None:
            nonlocal success, failed
            if exc is None:
                success += 1
                if resume:
                    uploaded.add(fpath.name)
                    _save_progress(local, remote_dir, uploaded)
            else:
                failed += 1
                failed_details.append((fpath.name, _error_detail(exc)))
                tqdm.write(f"  FAIL  {fpath.name}  {_error_detail(exc)}")
            pbar.update(1)

        if workers == 1:
            for fpath in pending:
                fpath, exc = await upload_one(fpath)
                await finish(fpath, exc)
        else:
            tasks = [asyncio.create_task(upload_one(fpath)) for fpath in pending]
            for coro in asyncio.as_completed(tasks):
                fpath, exc = await coro
                await finish(fpath, exc)

    # ── Summary ──────────────────────────────────────────────────────
    print()
    print("─" * 50)
    print(
        f"Done.  {success} uploaded, {skipped} skipped, {failed} failed."
    )

    if failed_details:
        print("\nFailed files:")
        for name, reason in failed_details:
            print(f"  {name}  —  {reason}")

    if failed == 0 and resume:
        _clear_progress(local)
        print("[resume] Progress record cleared.")
    elif failed > 0 and resume:
        print(
            f"[resume] Progress saved ({success} ok). "
            f"Re-run to retry the {failed} failed file(s)."
        )


# ── CLI ────────────────────────────────────────────────────────────────────

def _positive_int(value: str) -> int:
    ival = int(value)
    if ival < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {ival}")
    return ival


def _parse_size(size_str: str) -> int:
    """Parse size string like '100MB', '1GB' to bytes.

    Examples:
        '100' -> 100 bytes
        '100KB' -> 102400 bytes
        '100MB' -> 104857600 bytes
        '100GB' -> 107374182400 bytes
    """
    size_str = size_str.strip().upper()

    if size_str.isdigit():
        return int(size_str)

    units = {
        'KB': 1024,
        'MB': 1024 ** 2,
        'GB': 1024 ** 3,
        'TB': 1024 ** 4,
        'B': 1,
    }

    for unit, multiplier in units.items():
        if size_str.endswith(unit):
            number = size_str[:-len(unit)].strip()
            if not number.isdigit():
                raise argparse.ArgumentTypeError(f"Invalid size format: {size_str}")
            return int(number) * multiplier

    raise argparse.ArgumentTypeError(f"Invalid size format: {size_str}. Use format like '100MB', '1GB', etc.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload a file or directory to Baidu Yunpan (standalone CLI).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file
  python -m app.upload video.ts
  python -m app.upload video.ts -r /apps/movies/my-video.ts --retries 5

  # Directory with resume + 5 parallel workers
  python -m app.upload ./my_videos -r /apps/movies/my_videos -w 5

  # Directory — no resume, overwrite existing files
  python -m app.upload ./my_videos -r /apps/movies/my_videos --no-resume -o overwrite

  # Skip files larger than 100MB
  python -m app.upload ./my_videos -r /apps/movies/my_videos --max-size 100MB

  # Skip files larger than 1GB
  python -m app.upload ./large_files -r /apps/large --max-size 1GB

  # Keep local file after upload (don't delete)
  python -m app.upload video.ts --no-delete-after-upload

  # Upload and delete (default behavior)
  python -m app.upload video.ts
        """,
    )
    parser.add_argument(
        "file",
        help="Local file or directory path to upload.",
    )
    parser.add_argument(
        "--remote-path",
        "-r",
        default=None,
        help=(
            f"Target path on Baidu Pan "
            f"(default: {DEFAULT_REMOTE_PREFIX}/<name>)."
        ),
    )
    parser.add_argument(
        "--token",
        "-t",
        default=None,
        help="Baidu Pan access token (overrides ACCESS_TOKEN from .env).",
    )
    parser.add_argument(
        "--ondup",
        "-o",
        choices=["fail", "overwrite", "newcopy"],
        default="overwrite",
        help="Action when target file already exists (default: overwrite).",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help=f"Path to .env file (default: {DEFAULT_ENV_FILE}).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=False,
        help="Disable resume for directory uploads (do not track progress).",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel uploads for directory mode "
             f"(default: {DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "--retries",
        type=_positive_int,
        default=DEFAULT_RETRIES,
        help=f"Max retries per file with exponential backoff "
             f"(default: {DEFAULT_RETRIES}, 0 = no retry).",
    )
    parser.add_argument(
        "--max-size",
        type=_parse_size,
        default=None,
        help="Skip files larger than this size. "
             "Examples: '100MB', '1GB', '500KB'. If not set, no size limit.",
    )
    delete_group = parser.add_mutually_exclusive_group()
    delete_group.add_argument(
        "--delete-after-upload",
        action="store_true",
        default=True,
        help="Delete local file after successful upload (default: True).",
    )
    delete_group.add_argument(
        "--no-delete-after-upload",
        action="store_true",
        help="Do not delete local file after successful upload.",
    )
    return parser


async def _run(args: argparse.Namespace) -> None:
    token = args.token or load_access_token(args.env_file)
    path_arg = Path(args.file)

    # Determine delete_after_upload flag
    delete_after_upload = args.delete_after_upload and not args.no_delete_after_upload

    # Determine remote path
    if args.remote_path:
        remote_path = args.remote_path
    else:
        remote_path = f"{DEFAULT_REMOTE_PREFIX}/{path_arg.name}"

    async with BaiduYunUploader(access_token=token) as svc:
        if path_arg.is_dir():
            await upload_directory(
                svc,
                local_dir=str(path_arg),
                remote_dir=remote_path,
                ondup=args.ondup,
                resume=not args.no_resume,
                workers=args.workers,
                max_retries=args.retries,
                max_size=args.max_size,
            )
        else:
            await upload_file(
                svc,
                local_path=str(path_arg),
                remote_path=remote_path,
                ondup=args.ondup,
                max_retries=args.retries,
                max_size=args.max_size,
                delete_after_upload=delete_after_upload,
            )


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
