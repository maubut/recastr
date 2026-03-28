<p align="center">
  <h1 align="center">Recastr</h1>
  <p align="center">Turn any screen recording into a polished, professional video.</p>
  <p align="center">Open source. Local-first. Works with OBS or any MP4.</p>
</p>

<p align="center">
  <a href="#features">Features</a> &middot;
  <a href="#getting-started">Getting Started</a> &middot;
  <a href="#usage">Usage</a> &middot;
  <a href="#contributing">Contributing</a>
</p>

---

## What is Recastr?

Recastr takes a raw screen recording and transforms it into a clean, presentation-ready video with automatic zoom animations, webcam overlay, background styling, and captions — no manual editing needed.

Think of it as the post-production layer that OBS never had, or the editor part of Loom/Tella/Screen Studio — but open source and local-first.

## Features

- **Smart zoom detection** — Automatically detects click clusters, fast cursor arrivals, and sustained pauses to create natural zoom-in moments
- **Smooth camera animations** — Spring-based damping with easing curves for cinematic zoom transitions
- **OBS integration** — Connects via OBS WebSocket to start/stop recording and auto-detect cursor + webcam regions
- **Webcam overlay** — Circle, rounded, or rectangle webcam pip with automatic aspect ratio preservation
- **Background styles** — Carbon, gradient, and mesh backgrounds for a polished look
- **Auto captions** — Whisper-powered subtitle generation (TikTok and classic styles)
- **Visual timeline editor** — Svelte-based UI to preview, adjust, add or remove zoom events in real time
- **Source agnostic** — Works with any MP4 screen recording, not just OBS

## Getting Started

### Prerequisites

- Python 3.10+
- FFmpeg (`winget install FFmpeg` on Windows)
- Node.js 18+ (for UI development only)

### Install

```bash
git clone https://github.com/maubut/recastr.git
cd recastr
pip install numpy
```

Optional dependencies for enhanced features:

```bash
pip install opencv-python    # Better webcam overlay rendering
pip install websocket-client # OBS WebSocket integration
pip install whisper           # Auto captions
```

### Run

```bash
python server.py
```

This starts the local server and opens the UI in your browser at `http://localhost:8888`.

Or use the launcher on Windows:

```bash
RECASTR.bat
```

## Usage

### With OBS (recommended)

1. Enable WebSocket in OBS (Tools > WebSocket Server Settings)
2. Launch Recastr and connect to OBS from the UI
3. Hit Record — Recastr logs cursor movement in the background
4. Stop recording — the UI auto-loads your video, webcam, and cursor data
5. Adjust zoom events in the timeline, tweak options
6. Hit Render

### With any MP4

1. Launch Recastr
2. Drag & drop your screen recording + cursor log into the file panel
3. Zoom events are auto-detected from cursor data
4. Adjust and render

## Tech Stack

- **Backend**: Python (auto_zoom.py, cursor_logger.py, server.py)
- **Frontend**: Svelte 5 + TailwindCSS v4
- **Rendering**: NumPy + FFmpeg (optional OpenCV for webcam overlay)
- **OBS**: WebSocket API integration

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
