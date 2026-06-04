import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import DOWNLOADS_DIR, FRONTEND_DIR
from .services.cleanup import cleanup_old_files


async def _periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(1800)  # Every 30 minutes
        cleanup_old_files()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_old_files()
    task = asyncio.create_task(_periodic_cleanup())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Video Downloader API", lifespan=lifespan)

app.include_router(router)

# Serve downloaded files
app.mount("/downloads", StaticFiles(directory=str(DOWNLOADS_DIR)), name="downloads")

# Serve the frontend — must be last; html=True serves index.html for "/"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

