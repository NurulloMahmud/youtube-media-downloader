'use strict';

const YT_DOMAINS  = ['youtube.com', 'youtu.be'];
const IG_DOMAINS  = ['instagram.com'];

let currentJobId  = null;
let pollInterval  = null;

// ── URL detection ────────────────────────────────────────────────────
function detectPlatform(url) {
  if (YT_DOMAINS.some(d => url.includes(d))) return 'youtube';
  if (IG_DOMAINS.some(d => url.includes(d))) return 'instagram';
  return url.length > 5 ? 'invalid' : 'neutral';
}

document.getElementById('urlInput').addEventListener('input', function () {
  const platform = detectPlatform(this.value.trim());
  const dot  = document.getElementById('indicatorDot');
  const text = document.getElementById('indicatorText');

  dot.className = 'url-indicator-dot ' + platform;

  const labels = {
    youtube:   '▶ YouTube detected',
    instagram: '◆ Instagram Reels detected',
    invalid:   'Unsupported URL — please use YouTube or Instagram',
    neutral:   'Paste a YouTube or Instagram URL below',
  };
  text.textContent = labels[platform];
});

document.getElementById('urlInput').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') startDownload();
});

// ── Download flow ────────────────────────────────────────────────────
async function startDownload() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) return;

  const platform = detectPlatform(url);
  if (platform === 'invalid' || platform === 'neutral') {
    showError('Please enter a valid YouTube or Instagram URL.');
    return;
  }

  setLoading(true);
  hideDownloads();
  hideError();
  showProgress();
  setStatus('pending', 'Queued…');

  try {
    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || 'Failed to start download');
    }

    const { job_id } = await res.json();
    currentJobId = job_id;
    startPolling(job_id);
  } catch (err) {
    setLoading(false);
    hideProgress();
    showError(err.message);
  }
}

function startPolling(jobId) {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(() => pollStatus(jobId), 1000);
}

async function pollStatus(jobId) {
  try {
    const res = await fetch(`/api/status/${jobId}`);
    if (!res.ok) return;
    const job = await res.json();
    handleJobUpdate(job);
  } catch (_) {
    // Network hiccup — keep polling
  }
}

function handleJobUpdate(job) {
  const status   = job.status;
  const progress = job.progress || '0%';
  const title    = job.title    || '';

  if (title) document.getElementById('videoTitle').textContent = title;

  const statusLabels = {
    pending:           'Queued…',
    fetching_info:     'Fetching info…',
    downloading_video: 'Downloading video…',
    downloading_audio: 'Extracting audio…',
    completed:         'Complete!',
    error:             'Error',
  };

  setStatus(status, statusLabels[status] || status);
  setProgress(progress);

  if (status === 'completed') {
    stopPolling();
    setLoading(false);
    showDownloadLinks(job.video_url, job.audio_url);

    // Schedule server-side cleanup after 1 hour (client hint)
    setTimeout(() => cleanupJob(currentJobId), 60 * 60 * 1000);
  }

  if (status === 'error') {
    stopPolling();
    setLoading(false);
    hideProgress();
    showError(job.error || 'An unknown error occurred.');
    cleanupJob(currentJobId);
  }
}

async function cleanupJob(jobId) {
  if (!jobId) return;
  try {
    await fetch(`/api/cleanup/${jobId}`, { method: 'DELETE' });
  } catch (_) { /* best-effort */ }
}

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

// ── UI helpers ───────────────────────────────────────────────────────
function setLoading(loading) {
  const btn     = document.getElementById('downloadBtn');
  const btnText = document.getElementById('btnText');
  const spinner = document.getElementById('btnSpinner');

  btn.disabled = loading;
  btnText.textContent = loading ? 'Processing…' : 'Download';
  spinner.classList.toggle('hidden', !loading);
}

function showProgress() {
  document.getElementById('progressArea').classList.remove('hidden');
}

function hideProgress() {
  document.getElementById('progressArea').classList.add('hidden');
}

function setStatus(status, label) {
  const pill = document.getElementById('statusPill');
  pill.setAttribute('data-status', status);
  document.getElementById('statusLabel').textContent = label;
}

function setProgress(pct) {
  const num = parseInt(pct, 10) || 0;
  document.getElementById('progressBar').style.width = num + '%';
  document.getElementById('progressLabel').textContent = pct;
}

function showDownloadLinks(videoUrl, audioUrl) {
  const grid      = document.getElementById('downloadsGrid');
  const videoLink = document.getElementById('videoLink');
  const audioLink = document.getElementById('audioLink');

  if (videoUrl) {
    videoLink.href = videoUrl;
    videoLink.setAttribute('download', '');
  }
  if (audioUrl) {
    audioLink.href = audioUrl;
    audioLink.setAttribute('download', '');
  }

  grid.classList.remove('hidden');
}

function hideDownloads() {
  document.getElementById('downloadsGrid').classList.add('hidden');
}

function showError(message) {
  const area = document.getElementById('errorArea');
  document.getElementById('errorMsg').textContent = message;
  area.classList.remove('hidden');
}

function hideError() {
  document.getElementById('errorArea').classList.add('hidden');
}
