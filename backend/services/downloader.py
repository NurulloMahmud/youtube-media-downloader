import re
import shutil
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

import yt_dlp

from ..config import DOWNLOADS_DIR, INSTAGRAM_COOKIES_FILE, MAX_WORKERS

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Shared job store — used by both the web API and the Telegram bot
jobs: Dict[str, Dict[str, Any]] = {}


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[^\w\s-]', '', name)   # keep word chars, spaces, hyphens only
    name = re.sub(r'\s+', '_', name.strip())
    return name[:100] or 'video'


def get_platform(url: str) -> str:
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    if 'instagram.com' in url:
        return 'instagram'
    return 'unknown'


def _base_opts(platform: str) -> dict:
    """Common yt-dlp options shared by every download call."""
    opts: dict = {
        'quiet': True,
        'no_warnings': True,
    }
    # Find ffmpeg wherever it lives (macOS Homebrew, Linux /usr/bin, etc.)
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:
        opts['ffmpeg_location'] = ffmpeg
    # Pass Chrome cookies to YouTube to bypass bot-detection — only when Chrome exists
    if platform == 'youtube':
        chrome = (
            shutil.which('google-chrome') or
            shutil.which('google-chrome-stable') or
            shutil.which('chromium') or
            shutil.which('chromium-browser') or
            shutil.which('chrome')
        )
        if chrome:
            opts['cookiesfrombrowser'] = ('chrome',)
    # Use cookies file for Instagram (required on server/datacenter IPs)
    if platform == 'instagram' and INSTAGRAM_COOKIES_FILE.exists():
        opts['cookiefile'] = str(INSTAGRAM_COOKIES_FILE)
    return opts


def _run_download(url: str, job_id: str) -> None:
    try:
        jobs[job_id]['status'] = 'fetching_info'
        platform = jobs[job_id]['platform']

        with yt_dlp.YoutubeDL({**_base_opts(platform)}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'video')

        safe_title = sanitize_filename(title)
        jobs[job_id]['title'] = title

        def make_progress_hook(stage: str):
            def hook(d):
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        jobs[job_id]['progress'] = f"{int(downloaded / total * 100)}%"
            return hook

        # ── Video ──────────────────────────────────────────────────────────
        jobs[job_id]['status'] = 'downloading_video'
        jobs[job_id]['progress'] = '0%'

        video_format = (
            'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/'
            'bestvideo[ext=mp4]+bestaudio[ext=m4a]/'
            'bestvideo+bestaudio/best[ext=mp4]/best'
            if platform == 'youtube'
            else 'best[ext=mp4]/best'
        )

        video_stem = f"{job_id}_{safe_title}"
        video_opts = {
            **_base_opts(platform),
            'format': video_format,
            # Include %(ext)s so yt-dlp always appends the correct extension.
            'outtmpl': str(DOWNLOADS_DIR / f"{video_stem}.%(ext)s"),
            'merge_output_format': 'mp4',
            'progress_hooks': [make_progress_hook('video')],
        }
        with yt_dlp.YoutubeDL(video_opts) as ydl:
            ydl.download([url])

        video_path: Optional[Path] = None
        for ext in ('.mp4', '.mkv', '.webm', '.mov'):
            candidate = DOWNLOADS_DIR / f"{video_stem}{ext}"
            if candidate.exists():
                video_path = candidate
                break

        # Some platforms (e.g. Instagram) save without extension — rename to .mp4.
        if not video_path:
            bare = DOWNLOADS_DIR / video_stem
            if bare.exists():
                renamed = bare.with_suffix('.mp4')
                bare.rename(renamed)
                video_path = renamed

        if not video_path:
            raise FileNotFoundError("Video file not found after download")

        jobs[job_id]['video_path'] = str(video_path)
        jobs[job_id]['video_url'] = f"/downloads/{video_path.name}"

        # ── Audio — extract from the already-downloaded video via ffmpeg ──────
        # Avoids a second network request (prevents Instagram rate-limit hits).
        jobs[job_id]['status'] = 'downloading_audio'
        jobs[job_id]['progress'] = '0%'

        audio_stem = f"{job_id}_{safe_title}_audio"
        audio_final = DOWNLOADS_DIR / f"{audio_stem}.mp3"

        ffmpeg_bin = shutil.which('ffmpeg') or 'ffmpeg'
        proc = subprocess.run(
            [ffmpeg_bin, '-i', str(video_path), '-vn',
             '-codec:a', 'libmp3lame', '-b:a', '192k', '-y', str(audio_final)],
            capture_output=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg audio extraction failed: {proc.stderr.decode(errors='replace')[-400:]}"
            )

        jobs[job_id]['progress'] = '100%'

        if not audio_final.exists():
            raise FileNotFoundError("Audio file not found after extraction")

        jobs[job_id]['audio_path'] = str(audio_final)
        jobs[job_id]['audio_url'] = f"/downloads/{audio_final.name}"
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['progress'] = '100%'

    except Exception as exc:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(exc)


def start_download(url: str) -> str:
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        'status': 'pending',
        'progress': '0%',
        'title': '',
        'video_url': None,
        'audio_url': None,
        'video_path': None,
        'audio_path': None,
        'error': None,
        'created_at': time.time(),
        'platform': get_platform(url),
    }
    executor.submit(_run_download, url, job_id)
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return jobs.get(job_id)


def cleanup_job(job_id: str) -> bool:
    job = jobs.pop(job_id, None)
    if not job:
        return False
    for key in ('video_path', 'audio_path'):
        path_str = job.get(key)
        if path_str:
            try:
                Path(path_str).unlink(missing_ok=True)
            except Exception:
                pass
    return True
