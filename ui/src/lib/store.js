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

// --- UI state ---
export const selectedZoomIdx = writable(-1);
export const toastMessage = writable('');
export const obsStatus = writable({ connected: false, recording: false, label: 'OBS deconnecte' });

// --- Options ---
export const options = writable({
  bg: false,
  bgStyle: 'carbon',
  webcam: false,
  webcamShape: 'circle',
  webcamPos: 'bottom-right',
  webcamSize: 20,
  captions: false,
  captionStyle: 'tiktok',
  captionModel: 'base',
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
