<p align="center">
  <h1 align="center">Recastr</h1>
  <p align="center">The post-production toolkit that OBS never had.<br/>Turn any screen recording into a polished, professional video.</p>
</p>

<p align="center">
  <a href="#why-recastr">Why Recastr</a> &middot;
  <a href="#features">Features</a> &middot;
  <a href="#getting-started">Getting Started</a> &middot;
  <a href="#usage">Usage</a> &middot;
  <a href="#contributing">Contributing</a>
</p>

---

## Why Recastr?

Tools like Screen Studio, Tella, and Cap bundle their own recorder with an editor. You're locked into their capture pipeline, often on a single platform, and you pay for the package.

Recastr takes a different approach: **bring your own recording.**

You already have a screen recorder you like — OBS, ShareX, Game Bar, Loom, whatever. Recastr plugs in after the fact and handles the part that actually takes time: making the result look good.

**Source-agnostic** — Drop in any MP4. Recastr doesn't care where it came from.

**OBS-native** — Connects directly to OBS via WebSocket. Hit record from the Recastr UI, and it automatically tracks your cursor, detects your webcam region, and logs everything it needs. When you stop, the editor is pre-loaded and ready to go. No other tool does this.

**Intelligent auto-zoom** — Instead of manually keyframing zoom animations, Recastr analyzes your cursor behavior — click clusters, fast movements that land on a target, sustained pauses — and generates zoom events automatically. You review and tweak, not create from scratch.

**Open source, local-first** — Everything runs on your machine. No upload, no account, no subscription. Your recordings stay yours.

---

## Features

- **Smart zoom detection** — Three detection strategies (click clusters, fast arrivals, sustained pauses) with priority-based merging
- **Smooth camera animations** — Spring-based damping with easing curves for cinematic zoom transitions
- **OBS WebSocket integration** — Start/stop recording, auto-detect cursor and webcam regions, seamless workflow
- **Webcam overlay** — Circle, rounded, or rectangle PiP with automatic aspect ratio preservation
- **Background styles** — Carbon, gradient, and mesh backgrounds
- **Auto captions** — Whisper-powered subtitle generation (TikTok and classic styles)
- **Visual timeline editor** — Preview, drag, resize, or drag-out-to-delete zoom events in real time
- **One-click render** — FFmpeg-based export with all effects baked in

## Getting Started

### Prerequisites

- Python 3.10+
- FFmpeg (`winget install FFmpeg` on Windows)

### Install

```bash
git clone https://github.com/maubut/recastr.git
cd recastr
pip install numpy
```

Optional dependencies:

```bash
pip install opencv-python    # Better webcam overlay rendering
pip install websocket-client # OBS WebSocket integration
pip install whisper           # Auto captions
```

### Run

```bash
python server.py
```

Opens the UI in your browser at `http://localhost:8888`.

On Windows, double-click `RECASTR.bat`.

## Usage

### With OBS

1. Enable WebSocket in OBS (Tools > WebSocket Server Settings)
2. Launch Recastr and connect to OBS from the UI
3. Hit Record — cursor movement is tracked automatically
4. Stop — the editor loads your video, webcam, and cursor data
5. Review auto-detected zooms, tweak if needed
6. Render

### With any MP4

1. Launch Recastr
2. Drag & drop your screen recording + cursor log
3. Review auto-detected zoom events
4. Render

## Tech Stack

- **Backend** — Python (NumPy + FFmpeg, optional OpenCV)
- **Frontend** — Svelte 5, TailwindCSS v4
- **OBS** — WebSocket API (obs-websocket 5.x)

## Contributing

Contributions are welcome. Feel free to open issues or submit pull requests.

## License

AGPL-3.0 — see [LICENSE](LICENSE) for details.
