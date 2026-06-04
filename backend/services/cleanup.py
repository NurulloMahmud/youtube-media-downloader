import time
from pathlib import Path

from ..config import DOWNLOADS_DIR, FILE_TTL


def cleanup_old_files() -> int:
    now = time.time()
    removed = 0
    for f in DOWNLOADS_DIR.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > FILE_TTL:
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass
    return removed
