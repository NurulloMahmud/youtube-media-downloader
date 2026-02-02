# YouTube Downloader Web App

A simple web application to download YouTube videos and audio using FastAPI and yt-dlp.

## Features

- Download videos in H.264 format (compatible with all players)
- Extract audio as MP3
- Real-time progress tracking
- Modern, responsive UI
- Background processing with job queue

## Requirements

- Python 3.10+
- FFmpeg (for merging video/audio streams)
- Deno (recommended for full yt-dlp functionality)

## Installation

1. **Clone or copy the project files**

2. **Install FFmpeg** (if not already installed):
   ```bash
   # macOS
   brew install ffmpeg
   
   # Ubuntu/Debian
   sudo apt install ffmpeg
   
   # Windows
   # Download from https://ffmpeg.org/download.html
   ```

3. **Install Deno** (recommended):
   ```bash
   # macOS
   brew install deno
   
   # Or using curl
   curl -fsSL https://deno.land/install.sh | sh
   ```

4. **Create a virtual environment and install dependencies**:
   ```bash
   cd youtube-downloader
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Usage

1. **Start the server**:
   ```bash
   python app.py
   ```
   
   Or with uvicorn directly:
   ```bash
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Open your browser** and go to:
   ```
   http://localhost:8000
   ```

3. **Paste a YouTube URL** and click Download!

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/yt` | Web interface |
| POST | `/yt/api/download` | Start a download job |
| GET | `/yt/api/status/{job_id}` | Check job status |
| DELETE | `/yt/api/cleanup/{job_id}` | Delete job files |

### Example API Usage

```bash
# Start download
curl -X POST http://localhost:8000/yt/api/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtu.be/dQw4w9WgXcQ"}'

# Response: {"job_id": "abc123", "status": "pending", "message": "Download started"}

# Check status
curl http://localhost:8000/yt/api/status/abc123

# Response: {"job_id": "abc123", "status": "completed", "video_url": "/downloads/...", ...}
```

## Project Structure

```
youtube-downloader/
├── app.py              # FastAPI application
├── templates/
│   └── index.html      # Web interface
├── downloads/          # Downloaded files (auto-created)
├── requirements.txt    # Python dependencies
└── README.md
```

## How It Works

1. **User submits URL** → Creates a background job
2. **yt-dlp extracts info** → Gets available formats
3. **Downloads video** → Prefers H.264 for compatibility
4. **Downloads audio** → Converts to MP3
5. **Files served** → Static file serving for downloads

## Notes

- Downloaded files are automatically cleaned up after 1 hour
- Only YouTube URLs are supported (youtube.com and youtu.be)
- H.264 codec is prioritized for maximum player compatibility
- Audio is extracted at 192kbps MP3

## Troubleshooting

**"FFmpeg not found" error**
- Make sure FFmpeg is installed and in your PATH
- Run `ffmpeg -version` to verify

**"No supported JavaScript runtime" warning**
- Install Deno: `brew install deno`
- This is needed for some YouTube videos

**Video downloads but no audio**
- This usually means FFmpeg failed to merge
- Check FFmpeg installation

## License

For personal use only. Respect YouTube's Terms of Service.