from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ..services.downloader import cleanup_job, get_job, start_download

router = APIRouter(prefix="/api")

SUPPORTED_DOMAINS = ['youtube.com', 'youtu.be', 'instagram.com']


class DownloadRequest(BaseModel):
    url: str

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not any(d in v for d in SUPPORTED_DOMAINS):
            raise ValueError('Only YouTube and Instagram URLs are supported')
        return v


@router.post("/download")
async def create_download(request: DownloadRequest):
    job_id = start_download(request.url)
    return {"job_id": job_id}


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "title": job["title"],
        "video_url": job.get("video_url"),
        "audio_url": job.get("audio_url"),
        "error": job.get("error"),
        "platform": job.get("platform"),
    }


@router.delete("/cleanup/{job_id}")
async def delete_job(job_id: str):
    if not cleanup_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"message": "Cleaned up successfully"}
