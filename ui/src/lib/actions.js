import { get } from 'svelte/store';
import { videoW, videoH, videoDuration, videoFps, zoomEvents, cursorEvents, webcamInfo, captionSegments, analysisReady, selectedZoomIdx, obsStatus, options, apiCall, showToast, fmt, videoPath, webcamPath, logPath } from './store.js';

// --- Video/Webcam elements (bound from Preview component) ---
let videoEl = null;
let webcamEl = null;

export function setVideoEl(el) { videoEl = el; }
export function setWebcamEl(el) { webcamEl = el; }
export function getVideoEl() { return videoEl; }
export function getWebcamEl() { return webcamEl; }

// --- Helpers ---
function webcamReady() {
  return webcamEl && webcamEl.readyState > 0 && webcamEl.videoWidth > 0;
}

// --- Seek ---
export function seekTo(t) {
  if (videoEl) videoEl.currentTime = t;
  if (webcamReady()) webcamEl.currentTime = t;
}

// --- Playback ---
export function togglePlay() {
  if (!videoEl) return;
  if (videoEl.paused) {
    videoEl.play().catch(() => {});
    if (webcamReady()) { webcamEl.currentTime = videoEl.currentTime; webcamEl.play().catch(() => {}); }
  } else {
    videoEl.pause();
    if (webcamReady()) webcamEl.pause();
  }
}

export function setSpeed(s) {
  if (videoEl) videoEl.playbackRate = s;
  if (webcamReady()) webcamEl.playbackRate = s;
  showToast(`Vitesse: ${s}x`);
}

// --- Local zoom analysis (3-strategy detection matching auto_zoom.py) ---
export function analyzeLocal() {
  const events = get(cursorEvents);
  if (!events || events.length === 0) return;

  let zooms = [];
  const maxTime = events[events.length - 1].t - 3.0;

  // ── STRATEGIE 1: Clics + clusters ──
  const clicks = events.filter(e => e.click && e.t < maxTime && e.in === true);
  const clusters = [];
  let cur = [];
  for (const ev of clicks) {
    if (cur.length > 0) {
      const last = cur[cur.length - 1];
      const dt = ev.t - last.t;
      const dist = Math.sqrt((ev.nx - last.nx) ** 2 + (ev.ny - last.ny) ** 2);
      if (dt < 2.0 && dist < 0.08) { cur.push(ev); continue; }
    }
    if (cur.length) clusters.push(cur);
    cur = [ev];
  }
  if (cur.length) clusters.push(cur);

  for (const cl of clusters) {
    const avgNx = cl.reduce((s, e) => s + e.nx, 0) / cl.length;
    const avgNy = cl.reduce((s, e) => s + e.ny, 0) / cl.length;
    if (cl.length === 1) {
      zooms.push({
        id: 0, time: cl[0].t, nx: avgNx, ny: avgNy,
        zoom: 2.0, hold: 1.5, ease_in: 0.2, ease_out: 0.35,
        type: 'click', enabled: true,
      });
    } else {
      const clDur = cl[cl.length - 1].t - cl[0].t;
      zooms.push({
        id: 0, time: cl[0].t, nx: avgNx, ny: avgNy,
        zoom: Math.min(2.3, 3.5), hold: Math.min(clDur + 1.0, 3.0),
        ease_in: 0.2, ease_out: 0.4, type: 'click', enabled: true,
      });
    }
  }

  // ── STRATEGIE 2: Arrivees rapides ──
  const SPD_FAST = 0.015, SPD_SLOW = 0.003, ARR_WIN = 8;
  let wasFast = false, slowFrames = 0;
  for (let i = 0; i < events.length; i++) {
    const ev = events[i];
    if (ev.t >= maxTime) break;
    const spd = ev.spd || 0;
    if (spd > SPD_FAST) { wasFast = true; slowFrames = 0; }
    else if (wasFast && spd < SPD_SLOW) {
      slowFrames++;
      if (slowFrames >= ARR_WIN) {
        const hasNearby = zooms.some(z => Math.abs(z.time - ev.t) < 1.0);
        const isDrag = events.slice(Math.max(0, i - ARR_WIN * 2), i).some(e => e.drag);
        if (!hasNearby && !isDrag) {
          zooms.push({
            id: 0, time: ev.t - 0.1, nx: ev.nx, ny: ev.ny,
            zoom: 1.6, hold: 1.5, ease_in: 0.3, ease_out: 0.4,
            type: 'arrive', enabled: true,
          });
        }
        wasFast = false; slowFrames = 0;
      }
    } else if (spd > SPD_SLOW) { slowFrames = 0; }
  }

  // ── STRATEGIE 3: Pauses (curseur immobile) ──
  const STILL_THR = 0.012, STILL_MIN = 1.5;
  let stillStart = null, stillNx = 0, stillNy = 0, stillN = 0;
  for (const ev of events) {
    if (ev.t >= maxTime) break;
    if (ev.drag) { stillStart = null; continue; }
    const nx = ev.nx, ny = ev.ny;
    if (stillStart === null) { stillStart = ev.t; stillNx = nx; stillNy = ny; stillN = 1; continue; }
    const dist = Math.sqrt((nx - stillNx) ** 2 + (ny - stillNy) ** 2);
    if (dist > STILL_THR) {
      const dur = ev.t - stillStart;
      if (dur >= STILL_MIN) {
        const hasNearby = zooms.some(z => Math.abs(z.time - stillStart) < 1.2);
        if (!hasNearby) {
          zooms.push({
            id: 0, time: stillStart + 0.2, nx: stillNx, ny: stillNy,
            zoom: 1.4, hold: Math.min(dur - 0.5, 3.0), ease_in: 0.4, ease_out: 0.4,
            type: 'still', enabled: true,
          });
        }
      }
      stillStart = ev.t; stillNx = nx; stillNy = ny; stillN = 1;
    } else {
      stillN++;
      stillNx += (nx - stillNx) / stillN;
      stillNy += (ny - stillNy) / stillN;
    }
  }

  // ── MERGE: priorite click > arrive > still ──
  const PRIO = { click: 3, arrive: 2, still: 1 };
  zooms.sort((a, b) => a.time - b.time);
  const merged = [];
  for (const ze of zooms) {
    if (merged.length > 0) {
      const prev = merged[merged.length - 1];
      const prevEnd = prev.time + (prev.ease_in || 0.2) + (prev.hold || 1.5) + (prev.ease_out || 0.35);
      if (ze.time < prevEnd + 0.5) {
        const zePrio = PRIO[ze.type] || 0;
        const prevPrio = PRIO[prev.type] || 0;
        if (zePrio > prevPrio || (zePrio === prevPrio && ze.zoom > prev.zoom)) {
          merged[merged.length - 1] = ze;
        }
        continue;
      }
    }
    merged.push(ze);
  }
  merged.forEach((z, i) => z.id = i);

  zoomEvents.set(merged);
  analysisReady.set(true);
  showToast(`${merged.length} zooms detectes`);
}

// --- Easing curves matching auto_zoom.py ---
function easeZoomIn(t) {
  t = Math.max(0, Math.min(1, t));
  const base = t * t * (3 - 2 * t); // smoothstep
  const overshoot = Math.sin(t * Math.PI) * 0.04; // subtle 4% bump
  return Math.min(1.0, base + overshoot);
}
function easeZoomOut(t) {
  t = Math.max(0, Math.min(1, t));
  return 1 - Math.pow(1 - t, 2.5); // deceleration power curve
}
function smoothDamp(current, target, velocity, smoothTime, dt) {
  smoothTime = Math.max(0.01, smoothTime);
  const omega = 2.0 / smoothTime;
  const x = omega * dt;
  const exp = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x);
  const change = current - target;
  const temp = (velocity + omega * change) * dt;
  const newVel = (velocity - omega * temp) * exp;
  const newVal = target + (change + temp) * exp;
  return [newVal, newVel];
}

// Camera state for smooth panning (persistent across frames)
let camCx = 0.5, camCy = 0.5, camZoom = 1.0;
let velCx = 0, velCy = 0, velZoom = 0;
let lastPreviewT = -1;

// Reset camera state (call on seek / video change)
export function resetCamera() {
  camCx = 0.5; camCy = 0.5; camZoom = 1.0;
  velCx = 0; velCy = 0; velZoom = 0;
  lastPreviewT = -1;
}

// --- Zoom state calculation (spring-based smooth camera) ---
export function getZoomState(t) {
  const zooms = get(zoomEvents);

  // Phase 1: compute raw target zoom from events
  let targetZoom = 1.0, targetCx = 0.5, targetCy = 0.5;
  let active = false;

  for (const z of zooms) {
    if (!z.enabled) continue;
    const start = z.time;
    const ei = z.ease_in || 0.2;
    const hold = z.hold || 1.5;
    const eo = z.ease_out || 0.35;
    const end = start + ei + hold + eo;
    if (t < start || t > end) continue;

    const lt = t - start;
    let f;
    if (lt < ei) {
      f = easeZoomIn(lt / ei);
    } else if (lt < ei + hold) {
      f = 1.0;
    } else {
      f = 1.0 - easeZoomOut((lt - ei - hold) / eo);
    }

    const thisZoom = 1.0 + (z.zoom - 1.0) * f;
    if (thisZoom > targetZoom) {
      targetZoom = thisZoom;
      targetCx = z.nx || 0.5;
      targetCy = z.ny || 0.5;
      active = true;
    }
  }

  // Phase 2: smooth damp camera position + zoom (spring-based)
  const dt = (lastPreviewT >= 0) ? Math.min(t - lastPreviewT, 0.1) : 1 / 30;
  lastPreviewT = t;
  const adt = Math.max(dt, 1 / 60);

  if (active && targetZoom > 1.05) {
    [camCx, velCx] = smoothDamp(camCx, targetCx, velCx, 0.12, adt);
    [camCy, velCy] = smoothDamp(camCy, targetCy, velCy, 0.12, adt);
    [camZoom, velZoom] = smoothDamp(camZoom, targetZoom, velZoom, 0.15, adt);
  } else {
    [camZoom, velZoom] = smoothDamp(camZoom, 1.0, velZoom, 0.22, adt);
    [camCx, velCx] = smoothDamp(camCx, 0.5, velCx, 0.4, adt);
    [camCy, velCy] = smoothDamp(camCy, 0.5, velCy, 0.4, adt);
  }

  return { zoom: Math.max(1.0, camZoom), cx: camCx, cy: camCy };
}

// --- OBS Stop handler ---
export async function handleObsStop() {
  const res = await apiCall('POST', '/api/obs/stop', {});
  obsStatus.set({ connected: true, recording: false, label: 'OBS connecte' });

  if (res.success) {
    if (res.video_path) {
      videoPath.set(res.video_path);
      const videoName = res.video_path.split(/[\\/]/).pop();
      if (videoEl) {
        videoEl.src = '/' + encodeURIComponent(videoName);
        videoEl.load();
        videoEl.addEventListener('loadedmetadata', () => {
          videoW.set(videoEl.videoWidth);
          videoH.set(videoEl.videoHeight);
          videoDuration.set(videoEl.duration);
        }, { once: true });
      }
    }
    if (res.cursor_log_path) {
      logPath.set(res.cursor_log_path);
      if (res.cursor_log_data) {
        const data = res.cursor_log_data;
        cursorEvents.set(data.events || []);
        webcamInfo.set(data.metadata?.webcam || null);
      }
    }
    if (res.webcam_file_path) {
      webcamPath.set(res.webcam_file_path);
      const camName = res.webcam_file_path.split(/[\\/]/).pop();
      if (webcamEl) {
        webcamEl.src = '/' + encodeURIComponent(camName);
        webcamEl.load();
      }
    }
    // Auto-analyze
    const events = get(cursorEvents);
    if (events.length > 0) {
      setTimeout(() => {
        analyzeLocal();
        showToast(`Pret! ${get(zoomEvents).length} zooms detectes`);
      }, 800);
    }
  }
}

// --- Render ---
export async function startRender() {
  const opts = get(options);
  const activeZooms = get(zoomEvents).filter(z => z.enabled).map(z => ({
    time: z.time, nx: z.nx, ny: z.ny, zoom: z.zoom,
    hold: z.hold, ease_in: z.ease_in, ease_out: z.ease_out, type: z.type,
  }));

  const config = {
    video_path: get(videoPath),
    zoom_events: activeZooms,
    fps: get(videoFps) || 30,
  };

  if (opts.bg) config.background = { style: opts.bgStyle };
  if (opts.captions && get(captionSegments).length > 0) {
    config.captions = { style: opts.captionStyle, segments: get(captionSegments) };
  }
  if (opts.webcam) {
    const sizePct = opts.webcamSize / 100;
    // Get real webcam aspect ratio — check multiple sources
    let camAspect = 16/9; // safe fallback
    if (webcamEl && webcamEl.videoWidth > 0 && webcamEl.videoHeight > 0) {
      camAspect = webcamEl.videoWidth / webcamEl.videoHeight;
    } else {
      // Try to get from webcamInfo (OBS-detected region)
      const wi = get(webcamInfo);
      if (wi && wi.nw > 0 && wi.nh > 0) {
        camAspect = (wi.nw * get(videoW)) / (wi.nh * get(videoH));
      }
    }
    // out_nh is normalized to output height, so we need to factor in the output aspect ratio
    // In pixel space: dstW = out_w * sizePct, dstH = dstW / camAspect
    // Normalized: out_nh = dstH / out_h = (out_w * sizePct) / (camAspect * out_h) = sizePct * outAspect / camAspect
    const vw = get(videoW), vh = Math.max(get(videoH), 1);
    const outAspect = vw / vh;
    let out_nw_final = sizePct;
    let out_nh = sizePct * outAspect / camAspect;

    // For circle shape, force a square bounding box in pixel space (dst_w == dst_h)
    if (opts.webcamShape === 'circle') {
      // Square side = sizePct * vw (pixels), so out_nh = (sizePct * vw) / vh = sizePct * outAspect
      out_nh = sizePct * outAspect;
    }

    const margin = 0.02;
    let out_nx, out_ny;
    const pos = opts.webcamPos;
    if (pos === 'top-left') { out_nx = margin; out_ny = margin; }
    else if (pos === 'top-right') { out_nx = 1 - sizePct - margin; out_ny = margin; }
    else if (pos === 'bottom-right') { out_nx = 1 - sizePct - margin; out_ny = 1 - out_nh - margin; }
    else { out_nx = margin; out_ny = 1 - out_nh - margin; }
    config.webcam = { out_nx, out_ny, out_nw: sizePct, out_nh, cam_aspect: camAspect, shape: opts.webcamShape, border: 3, border_color: [255,255,255] };
    const wp = get(webcamPath);
    if (wp) config.webcam_file = wp;
  }

  // Dispatch custom event for render modal
  window.dispatchEvent(new CustomEvent('render-start', { detail: config }));
}
