# VideoGrab — YouTube & Instagram Downloader

Download YouTube videos and Instagram Reels with audio extraction, available as a web app and a Telegram bot.

## Features

- Download YouTube videos and Instagram Reels
- Extracts MP3 audio (192 kbps) automatically
- Real-time download progress in the web UI
- Telegram bot — paste a link, receive video + audio
- Files automatically deleted from the server after 1 hour

## Requirements

- Python 3.10+
- FFmpeg — for audio extraction and video stream merging

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg
```

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and edit the environment file
cp .env.example .env
# Edit .env — set BASE_URL and TELEGRAM_BOT_TOKEN
```

## Running

### Web server

```bash
python run_api.py
# Open http://localhost:8000
```

### Telegram bot

```bash
python run_bot.py
```

Both processes can run at the same time — they share the same download worker pool.

## Project structure

```
video-downloader/
├── backend/
│   ├── main.py            # FastAPI app
│   ├── config.py          # Config & paths
│   ├── api/
│   │   └── routes.py      # REST endpoints
│   └── services/
│       ├── downloader.py  # yt-dlp download logic
│       └── cleanup.py     # File cleanup service
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── bot/
│   └── bot.py             # Telegram bot
├── run_api.py
├── run_bot.py
└── requirements.txt
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/download` | Start a download job |
| GET | `/api/status/{job_id}` | Poll job progress |
| DELETE | `/api/cleanup/{job_id}` | Delete job files |
