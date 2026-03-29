import { writable, derived } from 'svelte/store';

// --- File paths (server-side) ---
export const videoPath = writable(null);
export const webcamPath = writable(null);
export const logPath = writable(null);

// --- Video metadata ---
export const videoW = writable(0);
export const videoH = writable(0);
export const videoDuration = writable(0);
export const videoFps = writable(30);

// --- Data ---
export const zoomEvents = writable([]);
export const cursorEvents = writable([]);
export const captionSegments = writable([]);
export const webcamInfo = writable(null);
export const analysisReady = writable(false);

// --- Layout keyframes ---
// Each keyframe defines the scene layout at a given time.
// The preview interpolates between keyframes for smooth transitions.
// Presets: 'intro' (cam big, screen small), 'demo' (screen big, cam corner),
//          'split' (50/50 side-by-side), 'cam-only' (cam fullscreen)
export const LAYOUT_PRESETS = {
  'intro':    { screenX: 0.55, screenY: 0.15, screenW: 0.42, camX: 0.04, camY: 0.12, camW: 0.48, camH: 0.76 },
  'demo':     { screenX: 0.0,  screenY: 0.0,  screenW: 1.0,  camX: 0.76, camY: 0.72, camW: 0.20, camH: 0.24 },
  'split':    { screenX: 0.01, screenY: 0.1,  screenW: 0.48, camX: 0.51, camY: 0.1,  camW: 0.48, camH: 0.80 },
  'cam-only': { screenX: 0.0,  screenY: 0.0,  screenW: 0.0,  camX: 0.0,  camY: 0.0,  camW: 1.0,  camH: 1.0 },
};
export const layoutEvents = writable([]);
export const selectedLayoutIdx = writable(-1);

// --- UI state ---
export const selectedZoomIdx = writable(-1);
export const toastMessage = writable('');
export const obsStatus = writable({ connected: false, recording: false, label: 'OBS deconnecte' });

// --- Options ---
export const options = writable({
  // Canvas layout
  bg: false,
  bgStyle: 'carbon',
  bgColor1: '#1a1a2e',
  bgColor2: '#6c5ce7',
  padding: 5,
  borderRadius: 12,
  insetShadow: true,
  // Webcam
  webcam: false,
  webcamShape: 'circle',
  webcamPos: 'bottom-right',
  webcamSize: 20,
  // Captions
  captions: false,
  captionStyle: 'tiktok',
  captionModel: 'base',
  // Cursor
  clickHighlight: true,
  debugClicks: false,
  debugTrail: false,
});

// --- Derived ---
export const enabledZoomCount = derived(zoomEvents, $z => $z.filter(z => z.enabled).length);

// --- API helper ---
const API = '';
export async function apiCall(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  return await res.json();
}

// --- Toast ---
let toastTimer;
export function showToast(msg, duration = 2500) {
  toastMessage.set(msg);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastMessage.set(''), duration);
}

// --- Format time ---
export function fmt(t) {
  const m = Math.floor(t / 60);
  const s = t % 60;
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}
