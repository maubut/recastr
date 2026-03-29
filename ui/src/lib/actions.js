import { get } from 'svelte/store';
import { videoW, videoH, videoDuration, videoFps, zoomEvents, cursorEvents, webcamInfo, captionSegments, analysisReady, selectedZoomIdx, obsStatus, options, apiCall, showToast, fmt, videoPath, webcamPath, logPath, layoutEvents, LAYOUT_PRESETS } from './store.js';

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

  // ── STRATEGIE 1: Clics + clusters (with release-aware hold duration) ──
  // Build click-release pairs: each click (mousedown) matched with its next release (mouseup)
  const clickPairs = [];
  const clicks = events.filter(e => e.click && e.t < maxTime && e.in === true);
  for (const clickEv of clicks) {
    // Find the next release event after this click
    let releaseTime = clickEv.t + 0.15; // default: quick click (150ms)
    let hasDrag = false;
    for (let j = events.indexOf(clickEv) + 1; j < events.length; j++) {
      if (events[j].drag) hasDrag = true;
      if (events[j].release) {
        releaseTime = events[j].t;
        break;
      }
      // Safety: if we find another click before a release, assume quick click
      if (events[j].click) break;
    }
    const clickDur = releaseTime - clickEv.t;
    clickPairs.push({ ...clickEv, releaseTime, clickDur, hasDrag });
  }

  // Cluster nearby click pairs
  const clusters = [];
  let cur = [];
  for (const cp of clickPairs) {
    if (cp.hasDrag) continue; // Skip drag operations (not real clicks)
    if (cur.length > 0) {
      const last = cur[cur.length - 1];
      const dt = cp.t - last.t;
      const dist = Math.sqrt((cp.nx - last.nx) ** 2 + (cp.ny - last.ny) ** 2);
      if (dt < 2.0 && dist < 0.08) { cur.push(cp); continue; }
    }
    if (cur.length) clusters.push(cur);
    cur = [cp];
  }
  if (cur.length) clusters.push(cur);

  for (const cl of clusters) {
    const avgNx = cl.reduce((s, e) => s + e.nx, 0) / cl.length;
    const avgNy = cl.reduce((s, e) => s + e.ny, 0) / cl.length;
    // Anticipate: start zoom BEFORE the click
    const anticipate = 0.35;
    // Use actual click-to-release duration to set hold time
    const lastRelease = Math.max(...cl.map(c => c.releaseTime));
    const firstClick = cl[0].t;
    const interactionDur = lastRelease - firstClick;
    // Hold = interaction duration + a buffer to let user see the result
    const hold = Math.max(0.8, Math.min(interactionDur + 0.6, 3.5));

    if (cl.length === 1) {
      zooms.push({
        id: 0, time: Math.max(0, firstClick - anticipate), nx: avgNx, ny: avgNy,
        zoom: 2.0, hold, ease_in: 0.35, ease_out: 0.45,
        type: 'click', enabled: true,
      });
    } else {
      zooms.push({
        id: 0, time: Math.max(0, firstClick - anticipate), nx: avgNx, ny: avgNy,
        zoom: Math.min(2.3, 3.5), hold,
        ease_in: 0.35, ease_out: 0.5, type: 'click', enabled: true,
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
            id: 0, time: Math.max(0, ev.t - 0.3), nx: ev.nx, ny: ev.ny,
            zoom: 1.6, hold: 1.5, ease_in: 0.4, ease_out: 0.5,
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
            id: 0, time: Math.max(0, stillStart - 0.1), nx: stillNx, ny: stillNy,
            zoom: 1.4, hold: Math.min(dur - 0.5, 3.0), ease_in: 0.5, ease_out: 0.5,
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

// --- Easing curves (smooth cinematic style) ---
function easeZoomIn(t) {
  t = Math.max(0, Math.min(1, t));
  // Smooth quintic ease-in-out: very gentle start and end, no overshoot
  if (t < 0.5) return 16 * t * t * t * t * t;
  const u = -2 * t + 2;
  return 1 - u * u * u * u * u / 2;
}
function easeZoomOut(t) {
  t = Math.max(0, Math.min(1, t));
  // Quintic ease-out: smooth deceleration, no bounce
  const u = 1 - t;
  return 1 - u * u * u * u * u;
}
function smoothDamp(current, target, velocity, smoothTime, dt) {
  smoothTime = Math.max(0.01, smoothTime);
  const omega = 2.0 / smoothTime;
  const x = omega * dt;
  const exp = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x);
  const change = current - target;
  // Clamp maximum change to prevent overshooting on large dt
  const maxChange = smoothTime * 2.0;
  const clampedChange = Math.max(-maxChange, Math.min(maxChange, change));
  const adjustedTarget = current - clampedChange;
  const temp = (velocity + omega * clampedChange) * dt;
  const newVel = (velocity - omega * temp) * exp;
  const newVal = adjustedTarget + (clampedChange + temp) * exp;
  return [newVal, newVel];
}

// --- Layout state interpolation ---
// Default layout = "demo" (screen full, webcam corner)
const DEFAULT_LAYOUT = LAYOUT_PRESETS['demo'];

export function getLayoutState(t) {
  const events = get(layoutEvents);
  if (!events || events.length === 0) return DEFAULT_LAYOUT;

  // Find surrounding keyframes
  // Events are sorted by time
  if (t <= events[0].time) return { ...DEFAULT_LAYOUT, ...events[0] };
  if (t >= events[events.length - 1].time + (events[events.length - 1].transition || 0.8)) {
    return { ...DEFAULT_LAYOUT, ...events[events.length - 1] };
  }

  // Find which two keyframes we're between
  for (let i = 0; i < events.length; i++) {
    const ev = events[i];
    const trans = ev.transition || 0.8;
    const nextEv = events[i + 1];

    if (nextEv && t >= ev.time && t < nextEv.time) {
      // Are we in the transition zone leading into nextEv?
      const transStart = nextEv.time - trans;
      if (t >= transStart) {
        // Interpolate between ev and nextEv
        const progress = (t - transStart) / trans;
        const ease = progress * progress * (3 - 2 * progress); // smoothstep
        return lerpLayout({ ...DEFAULT_LAYOUT, ...ev }, { ...DEFAULT_LAYOUT, ...nextEv }, ease);
      }
      // Holding at ev
      return { ...DEFAULT_LAYOUT, ...ev };
    }

    // Last event
    if (!nextEv && t >= ev.time) {
      return { ...DEFAULT_LAYOUT, ...ev };
    }
  }
  return DEFAULT_LAYOUT;
}

function lerpLayout(a, b, t) {
  const result = {};
  for (const key of ['screenX', 'screenY', 'screenW', 'camX', 'camY', 'camW', 'camH']) {
    const va = a[key] ?? 0, vb = b[key] ?? 0;
    result[key] = va + (vb - va) * t;
  }
  return result;
}

// Camera state for smooth panning (persistent across frames)
let camCx = 0.5, camCy = 0.5, camZoom = 1.0;
let velCx = 0, velCy = 0, velZoom = 0;
let lastPreviewT = -1;
// Cache last computed state so template reads don't run the spring sim
let lastZoomResult = { zoom: 1.0, cx: 0.5, cy: 0.5 };
let lastZoomCalcT = -1;

// Reset camera state (call on seek / video change)
export function resetCamera() {
  camCx = 0.5; camCy = 0.5; camZoom = 1.0;
  velCx = 0; velCy = 0; velZoom = 0;
  lastPreviewT = -1;
  lastZoomCalcT = -1;
}

// --- Get cursor position at time t (for smooth tracking during zoom) ---
function getCursorAt(t) {
  const events = get(cursorEvents);
  if (!events || events.length === 0) return null;
  // Binary search for closest event <= t
  let lo = 0, hi = events.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (events[mid].t <= t) lo = mid; else hi = mid - 1;
  }
  const ev = events[lo];
  if (!ev || typeof ev.t !== 'number' || Math.abs(ev.t - t) > 0.5) return null;
  const nx = typeof ev.nx === 'number' ? ev.nx : 0.5;
  const ny = typeof ev.ny === 'number' ? ev.ny : 0.5;
  return { nx, ny };
}

// --- Zoom state calculation (spring-based smooth camera) ---
export function getZoomState(t) {
  // If called with the same time (e.g. template re-render), return cached result
  // This prevents the template's call from advancing the spring simulation
  if (t === lastZoomCalcT) return lastZoomResult;
  lastZoomCalcT = t;

  const zooms = get(zoomEvents);

  // Phase 1: compute raw target zoom + position from events
  let targetZoom = 1.0, targetCx = 0.5, targetCy = 0.5;
  let active = false;
  let inHoldPhase = false;
  let activeZoomEvent = null;

  for (const z of zooms) {
    if (!z.enabled) continue;
    const start = z.time;
    const ei = z.ease_in || 0.3;
    const hold = z.hold || 1.5;
    const eo = z.ease_out || 0.5;
    const end = start + ei + hold + eo;
    if (t < start || t > end) continue;

    const lt = t - start;
    let f;
    if (lt < ei) {
      f = easeZoomIn(lt / ei);
    } else if (lt < ei + hold) {
      f = 1.0;
      inHoldPhase = true;
    } else {
      f = 1.0 - easeZoomOut((lt - ei - hold) / eo);
    }

    const thisZoom = 1.0 + (z.zoom - 1.0) * f;
    if (thisZoom > targetZoom) {
      targetZoom = thisZoom;
      targetCx = z.nx || 0.5;
      targetCy = z.ny || 0.5;
      active = true;
      activeZoomEvent = z;
    }
  }

  // During hold phase: follow cursor position for natural camera tracking
  if (inHoldPhase && activeZoomEvent) {
    const cursor = getCursorAt(t);
    if (cursor) {
      const zoomCx = activeZoomEvent.nx || 0.5;
      const zoomCy = activeZoomEvent.ny || 0.5;
      // Adaptive tracking: the further the cursor is from zoom center, the more we follow it
      // This keeps the cursor visible even during fast movements
      const dist = Math.sqrt((cursor.nx - zoomCx) ** 2 + (cursor.ny - zoomCy) ** 2);
      // viewRadius = half the visible area at current zoom (in normalized coords)
      const viewRadius = 0.5 / (activeZoomEvent.zoom || 2.0);
      // When cursor is near edge of visible area, track up to 90%
      const trackWeight = Math.min(0.9, 0.2 + 0.7 * Math.min(1, dist / viewRadius));
      targetCx = zoomCx + (cursor.nx - zoomCx) * trackWeight;
      targetCy = zoomCy + (cursor.ny - zoomCy) * trackWeight;
    }
  }

  // Phase 2: handle seek detection — snap camera on large time jumps
  const rawDt = (lastPreviewT >= 0) ? (t - lastPreviewT) : 1 / 30;
  const isSeek = Math.abs(rawDt) > 0.25 || rawDt < 0; // jumped > 250ms or went backward
  lastPreviewT = t;

  if (isSeek) {
    // Snap camera to target instantly on seek (no spring chase)
    camCx = active ? targetCx : 0.5;
    camCy = active ? targetCy : 0.5;
    camZoom = targetZoom;
    velCx = 0; velCy = 0; velZoom = 0;
    lastZoomResult = { zoom: Math.max(1.0, camZoom), cx: camCx, cy: camCy, speed: 0 };
    return lastZoomResult;
  }

  const dt = Math.max(rawDt, 1 / 120); // min dt for stability

  // Phase 3: smooth damp camera (cinematic spring constants)
  if (active && targetZoom > 1.05) {
    // Adaptive smoothTime: faster when camera is far from target (fast cursor moves)
    // slower when close (smooth settle). Range: 0.10 (fast) to 0.30 (cinematic)
    const panDist = Math.sqrt((camCx - targetCx) ** 2 + (camCy - targetCy) ** 2);
    const panSmooth = Math.max(0.10, 0.30 - panDist * 2.0);
    [camCx, velCx] = smoothDamp(camCx, targetCx, velCx, panSmooth, dt);
    [camCy, velCy] = smoothDamp(camCy, targetCy, velCy, panSmooth, dt);
    [camZoom, velZoom] = smoothDamp(camZoom, targetZoom, velZoom, 0.30, dt);
  } else {
    // Zooming out / returning to full view: gentle return
    [camZoom, velZoom] = smoothDamp(camZoom, 1.0, velZoom, 0.40, dt);
    [camCx, velCx] = smoothDamp(camCx, 0.5, velCx, 0.55, dt);
    [camCy, velCy] = smoothDamp(camCy, 0.5, velCy, 0.55, dt);
  }

  // NaN safety: if camera state gets corrupted, reset to defaults
  if (isNaN(camZoom) || isNaN(camCx) || isNaN(camCy)) {
    camCx = 0.5; camCy = 0.5; camZoom = 1.0;
    velCx = 0; velCy = 0; velZoom = 0;
  }

  // Expose velocity components for directional motion blur
  const camSpeed = Math.sqrt(velCx * velCx + velCy * velCy) * 25.0 + Math.abs(velZoom) * 6.0;

  lastZoomResult = {
    zoom: Math.max(1.0, camZoom), cx: camCx, cy: camCy,
    speed: camSpeed,
    // Directional velocity (normalized-coord-scaled) for directional blur
    dvx: velCx,
    dvy: velCy,
    dvz: velZoom,
  };
  return lastZoomResult;
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

  if (opts.bg) config.background = {
    style: opts.bgStyle,
    color1: opts.bgColor1,
    color2: opts.bgColor2,
    padding: opts.padding,
    border_radius: opts.borderRadius,
    inset_shadow: opts.insetShadow,
  };
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
