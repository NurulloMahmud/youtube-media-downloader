import yt_dlp
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
import shutil
import time
from typing import Optional


app = FastAPI(title="YouTube Downloader", version="1.0.0")

DOWNLOAD_DIR = Path("./downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Serve downloaded files statically
app.mount("/downloads", StaticFiles(directory=str(DOWNLOAD_DIR)), name="downloads")

executor = ThreadPoolExecutor(max_workers=3)

jobs: dict[str, dict] = {}


class DownloadRequest(BaseModel):
    url: str


class DownloadResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, downloading, processing, completed, error
    progress: Optional[str] = None
    title: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    error: Optional[str] = None


def sanitize_filename(title: str) -> str:
    """Create a safe filename from video title"""
    safe = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
    return safe[:100] if len(safe) > 100 else safe


def download_video_sync(url: str, job_id: str):
    """
    Synchronous video download function (runs in thread pool).
    Downloads both video (H.264) and audio (MP3).
    """
    job = jobs[job_id]
    job['status'] = 'downloading'
    
    try:
        # First, get video info
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'video')
            job['title'] = title
        
        safe_title = sanitize_filename(title)
        video_filename = f"{job_id}_{safe_title}.mp4"
        audio_filename = f"{job_id}_{safe_title}.mp3"
        
        # Progress hook
        def progress_hook(d):
            if d['status'] == 'downloading':
                job['progress'] = d.get('_percent_str', '').strip()
            elif d['status'] == 'finished':
                job['progress'] = '100%'
        
        # Download video (H.264 for compatibility)
        job['status'] = 'downloading_video'
        video_opts = {
            'format': (
                'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[vcodec^=avc1]+bestaudio/'
                'bestvideo[ext=mp4]+bestaudio[ext=m4a]/'
                'best[ext=mp4]/best'
            ),
            'outtmpl': str(DOWNLOAD_DIR / video_filename),
            'merge_output_format': 'mp4',
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(video_opts) as ydl:
            ydl.download([url])
        
        # Download audio
        job['status'] = 'downloading_audio'
        job['progress'] = '0%'
        
        audio_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(DOWNLOAD_DIR / f"{job_id}_{safe_title}.%(ext)s"),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(audio_opts) as ydl:
            ydl.download([url])
        
        # Verify files exist
        video_path = DOWNLOAD_DIR / video_filename
        audio_path = DOWNLOAD_DIR / audio_filename
        
        # Sometimes the extension changes, search for the files
        if not video_path.exists():
            for f in DOWNLOAD_DIR.glob(f"{job_id}_*.mp4"):
                video_path = f
                break
        
        if not audio_path.exists():
            for f in DOWNLOAD_DIR.glob(f"{job_id}_*.mp3"):
                audio_path = f
                break
        
        job['status'] = 'completed'
        job['video_url'] = f"/downloads/{video_path.name}" if video_path.exists() else None
        job['audio_url'] = f"/downloads/{audio_path.name}" if audio_path.exists() else None
        job['progress'] = '100%'
        
    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main HTML page"""
    html_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.post("/api/download", response_model=DownloadResponse)
async def start_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Start a download job for a YouTube video.
    Returns a job ID to track progress.
    """
    url = request.url.strip()
    
    # Basic URL validation
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    # if not any(domain in url for domain in ['youtube.com', 'youtu.be']):
    #     raise HTTPException(status_code=400, detail="Only YouTube URLs are supported")
    
    # Create job
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        'status': 'pending',
        'progress': '0%',
        'title': None,
        'video_url': None,
        'audio_url': None,
        'error': None,
        'created_at': time.time(),
    }
    
    # Run download in background
    loop = asyncio.get_event_loop()
    loop.run_in_executor(executor, download_video_sync, url, job_id)
    
    return DownloadResponse(
        job_id=job_id,
        status="pending",
        message="Download started"
    )


@app.get("/api/status/{job_id}", response_model=JobStatus)
async def get_status(job_id: str):
    """Get the status of a download job"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    return JobStatus(
        job_id=job_id,
        status=job['status'],
        progress=job.get('progress'),
        title=job.get('title'),
        video_url=job.get('video_url'),
        audio_url=job.get('audio_url'),
        error=job.get('error'),
    )


@app.delete("/api/cleanup/{job_id}")
async def cleanup_job(job_id: str):
    """Clean up files for a job"""
    if job_id in jobs:
        # Delete associated files
        for f in DOWNLOAD_DIR.glob(f"{job_id}_*"):
            f.unlink()
        del jobs[job_id]
    return {"status": "cleaned"}


# Cleanup old jobs periodically (files older than 1 hour)
@app.on_event("startup")
async def startup_cleanup():
    """Clean up old files on startup"""
    for f in DOWNLOAD_DIR.glob("*"):
        if f.is_file() and (time.time() - f.stat().st_mtime) > 3600:
            f.unlink()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)