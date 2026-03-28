<script>
  import { onMount, onDestroy } from 'svelte';
  import { videoW, videoH, videoDuration, zoomEvents, cursorEvents, webcamInfo, selectedZoomIdx, options } from '../lib/store.js';
  import { setVideoEl, setWebcamEl, getZoomState, seekTo, togglePlay } from '../lib/actions.js';

  let previewCanvas;
  let ctx;
  let videoEl;
  let webcamEl;
  let zoomOverlayEl;
  let animFrame;
  let overlayDragState = null;
  let overlayInterval;

  onMount(() => {
    ctx = previewCanvas.getContext('2d');
    setVideoEl(videoEl);
    setWebcamEl(webcamEl);
    animFrame = requestAnimationFrame(draw);
    overlayInterval = setInterval(renderZoomOverlay, 200);

    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.key === ' ') { e.preventDefault(); togglePlay(); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); seekTo(Math.max(0, videoEl.currentTime - 2)); }
      if (e.key === 'ArrowRight') { e.preventDefault(); seekTo(Math.min($videoDuration, videoEl.currentTime + 2)); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  onDestroy(() => {
    cancelAnimationFrame(animFrame);
    clearInterval(overlayInterval);
  });

  $: if (previewCanvas && $videoW > 0) {
    previewCanvas.width = $videoW;
    previewCanvas.height = $videoH;
  }

  function draw() {
    animFrame = requestAnimationFrame(draw);
    if (!videoEl?.videoWidth || !ctx) return;

    const t = videoEl.currentTime;
    const state = getZoomState(t);
    const vw = $videoW, vh = $videoH;

    if (state.zoom > 1.02) {
      const cw = vw / state.zoom;
      const ch = vh / state.zoom;
      const cx = state.cx * vw;
      const cy = state.cy * vh;
      const x1 = Math.max(0, Math.min(cx - cw / 2, vw - cw));
      const y1 = Math.max(0, Math.min(cy - ch / 2, vh - ch));
      ctx.drawImage(videoEl, x1, y1, cw, ch, 0, 0, vw, vh);
    } else {
      ctx.drawImage(videoEl, 0, 0, vw, vh);
    }

    // Webcam overlay
    if ($options.webcam && webcamEl?.src && webcamEl.videoWidth > 0) {
      drawWebcam(webcamEl, 0, 0, webcamEl.videoWidth, webcamEl.videoHeight);
    } else if ($options.webcam && $webcamInfo?.nx !== undefined) {
      drawWebcam(videoEl, $webcamInfo.nx * vw, $webcamInfo.ny * vh, $webcamInfo.nw * vw, $webcamInfo.nh * vh);
    }

    // Click highlight
    if ($options.clickHighlight && $cursorEvents.length > 0) {
      let lo = 0, hi = $cursorEvents.length - 1;
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; if ($cursorEvents[mid].t <= t) lo = mid; else hi = mid - 1; }
      const cp = $cursorEvents[lo];
      if (cp?.click && cp.in === true && Math.abs(cp.t - t) < 0.6) {
        let cpx = cp.nx * vw, cpy = cp.ny * vh;
        if (state.zoom > 1.05) {
          const cw = vw / state.zoom, ch = vh / state.zoom;
          const sx = Math.max(0, Math.min(state.cx * vw - cw/2, vw - cw));
          const sy = Math.max(0, Math.min(state.cy * vh - ch/2, vh - ch));
          cpx = (cp.nx * vw - sx) / cw * vw;
          cpy = (cp.ny * vh - sy) / ch * vh;
        }
        if (cpx >= 0 && cpx <= vw && cpy >= 0 && cpy <= vh) {
          const age = Math.abs(t - cp.t);
          const prog = age / 0.6;
          const alpha = Math.max(0, 0.7 * (1 - prog));
          ctx.save();
          ctx.strokeStyle = `rgba(139,92,246,${alpha})`;
          ctx.lineWidth = 3;
          ctx.beginPath(); ctx.arc(cpx, cpy, 12 + 20 * prog, 0, Math.PI * 2); ctx.stroke();
          ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(cpx, cpy, 6 + 14 * prog, 0, Math.PI * 2); ctx.stroke();
          ctx.fillStyle = `rgba(139,92,246,${alpha + 0.1})`;
          ctx.beginPath(); ctx.arc(cpx, cpy, 4, 0, Math.PI * 2); ctx.fill();
          ctx.restore();
        }
      }
    }

    // Debug overlays
    if (($options.debugClicks || $options.debugTrail) && $cursorEvents.length > 0) {
      if ($options.debugTrail) {
        ctx.save();
        ctx.lineWidth = 1.5; ctx.lineCap = 'round';
        let started = false;
        for (const ev of $cursorEvents) {
          if (ev.t < t - 2 || ev.t > t) continue;
          const px = (ev.nx || 0) * vw, py = (ev.ny || 0) * vh;
          const alpha = Math.max(0.05, 1 - (t - ev.t) / 2);
          ctx.strokeStyle = `rgba(139,92,246,${alpha * 0.6})`;
          if (!started) { ctx.beginPath(); ctx.moveTo(px, py); started = true; }
          else { ctx.lineTo(px, py); ctx.stroke(); ctx.beginPath(); ctx.moveTo(px, py); }
        }
        ctx.restore();
        let nearest = null, bestDt = Infinity;
        for (const ev of $cursorEvents) { const d = Math.abs(ev.t - t); if (d < bestDt) { bestDt = d; nearest = ev; } }
        if (nearest && bestDt < 0.2) {
          const px = (nearest.nx || 0) * vw, py = (nearest.ny || 0) * vh;
          ctx.save(); ctx.strokeStyle = 'rgba(255,255,255,0.5)'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(px - 15, py); ctx.lineTo(px + 15, py); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(px, py - 15); ctx.lineTo(px, py + 15); ctx.stroke();
          ctx.restore();
        }
      }
      if ($options.debugClicks) {
        ctx.save();
        for (const ev of $cursorEvents) {
          if (!ev.click) continue;
          const isIn = ev.in === true;
          const px = (ev.nx || 0) * vw, py = (ev.ny || 0) * vh;
          ctx.beginPath(); ctx.arc(px, py, 8, 0, Math.PI * 2);
          ctx.fillStyle = isIn ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'; ctx.fill();
          ctx.strokeStyle = 'rgba(255,255,255,0.3)'; ctx.lineWidth = 1; ctx.stroke();
          ctx.font = '9px monospace'; ctx.fillStyle = 'rgba(255,255,255,0.8)';
          ctx.fillText(ev.t.toFixed(1) + 's', px + 10, py + 3);
        }
        ctx.restore();
      }
    }
  }

  function drawWebcam(src, srcX, srcY, srcW, srcH) {
    const shape = $options.webcamShape;
    const pos = $options.webcamPos;
    const sizePct = $options.webcamSize / 100;
    const vw = $videoW, vh = $videoH;
    const camAspect = srcW / Math.max(srcH, 1);
    const dstW = vw * sizePct;
    const dstH = dstW / camAspect;
    const margin = vw * 0.02;
    let dstX, dstY;
    if (pos === 'top-left') { dstX = margin; dstY = margin; }
    else if (pos === 'top-right') { dstX = vw - dstW - margin; dstY = margin; }
    else if (pos === 'bottom-right') { dstX = vw - dstW - margin; dstY = vh - dstH - margin; }
    else { dstX = margin; dstY = vh - dstH - margin; }

    ctx.save();
    if (shape === 'circle') {
      const cx = dstX + dstW / 2, cy = dstY + dstH / 2;
      const r = Math.min(dstW, dstH) / 2;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.clip();
      try { ctx.drawImage(src, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH); } catch(e) {}
      ctx.restore(); ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
    } else if (shape === 'rounded') {
      const r = Math.min(dstW, dstH) / 6;
      ctx.beginPath(); ctx.roundRect(dstX, dstY, dstW, dstH, r); ctx.clip();
      try { ctx.drawImage(src, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH); } catch(e) {}
      ctx.restore(); ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.roundRect(dstX, dstY, dstW, dstH, r); ctx.stroke();
    } else {
      try { ctx.drawImage(src, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH); } catch(e) {}
      ctx.restore(); ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 2; ctx.strokeRect(dstX, dstY, dstW, dstH);
    }
    ctx.restore();
  }

  // --- Zoom overlay ---
  function renderZoomOverlay() {
    if (!zoomOverlayEl || !previewCanvas) return;
    zoomOverlayEl.innerHTML = '';
    if (!$videoW || $zoomEvents.length === 0) return;

    const canvasRect = previewCanvas.getBoundingClientRect();
    const containerRect = previewCanvas.parentElement.getBoundingClientRect();
    const oLeft = canvasRect.left - containerRect.left;
    const oTop = canvasRect.top - containerRect.top;
    const oW = canvasRect.width;
    const oH = canvasRect.height;
    zoomOverlayEl.style.left = oLeft + 'px';
    zoomOverlayEl.style.top = oTop + 'px';
    zoomOverlayEl.style.width = oW + 'px';
    zoomOverlayEl.style.height = oH + 'px';

    const t = videoEl?.currentTime || 0;
    for (let i = 0; i < $zoomEvents.length; i++) {
      const z = $zoomEvents[i];
      if (!z.enabled) continue;
      const dur = (z.ease_in || 0.3) + (z.hold || 1.5) + (z.ease_out || 0.5);
      const isActive = (t >= z.time - 0.5 && t <= z.time + dur + 0.5);
      const isSelected = (i === $selectedZoomIdx);
      if (!isActive && !isSelected) continue;

      const nx = z.nx || 0.5, ny = z.ny || 0.5;
      const zl = z.zoom || 2.0;

      // Dot
      const dot = document.createElement('div');
      Object.assign(dot.style, {
        position: 'absolute', width: '10px', height: '10px', borderRadius: '50%',
        background: '#8b5cf6', border: '2px solid rgba(255,255,255,0.8)',
        transform: 'translate(-50%,-50%)', cursor: 'grab', pointerEvents: 'auto', zIndex: '3',
        boxShadow: '0 0 8px rgba(139,92,246,0.4)',
        left: (nx * oW) + 'px', top: (ny * oH) + 'px',
      });
      dot.addEventListener('mousedown', (e) => startOverlayDrag(e, i, 'dot'));
      zoomOverlayEl.appendChild(dot);

      // Rect
      const rw = 1.0/zl, rh = 1.0/zl;
      const rx = Math.max(0, Math.min(1-rw, nx - rw/2));
      const ry = Math.max(0, Math.min(1-rh, ny - rh/2));
      const rect = document.createElement('div');
      Object.assign(rect.style, {
        position: 'absolute', border: isSelected ? '2px solid rgba(139,92,246,0.6)' : '1px solid rgba(139,92,246,0.3)',
        background: isSelected ? 'rgba(139,92,246,0.08)' : 'rgba(139,92,246,0.04)',
        pointerEvents: 'auto', cursor: 'move', zIndex: '2', borderRadius: '4px',
        left: (rx*oW)+'px', top: (ry*oH)+'px',
        width: (rw*oW)+'px', height: (rh*oH)+'px',
      });
      rect.addEventListener('mousedown', (e) => startOverlayDrag(e, i, 'rect'));
      zoomOverlayEl.appendChild(rect);

      // Handle
      const handle = document.createElement('div');
      Object.assign(handle.style, {
        position: 'absolute', width: '8px', height: '8px',
        background: '#fff', border: '1.5px solid #8b5cf6', borderRadius: '2px',
        cursor: 'nwse-resize', pointerEvents: 'auto', zIndex: '4',
        transform: 'translate(-50%,-50%)',
        left: ((rx+rw)*oW)+'px', top: ((ry+rh)*oH)+'px',
      });
      handle.addEventListener('mousedown', (e) => startOverlayDrag(e, i, 'handle'));
      zoomOverlayEl.appendChild(handle);
    }
  }

  function startOverlayDrag(e, idx, type) {
    e.preventDefault(); e.stopPropagation();
    const z = $zoomEvents[idx];
    const canvasRect = previewCanvas.getBoundingClientRect();
    overlayDragState = {
      type, idx,
      startNx: z.nx || 0.5, startNy: z.ny || 0.5, startZoom: z.zoom || 2.0,
      startClientX: e.clientX, startClientY: e.clientY,
      ox: canvasRect.left, oy: canvasRect.top, w: canvasRect.width, h: canvasRect.height,
    };
    if (type === 'rect') {
      const mx = (e.clientX - canvasRect.left) / canvasRect.width;
      const my = (e.clientY - canvasRect.top) / canvasRect.height;
      overlayDragState.offsetNx = (z.nx || 0.5) - mx;
      overlayDragState.offsetNy = (z.ny || 0.5) - my;
    }
    $selectedZoomIdx = idx;
    seekTo(z.time);

    const onMove = (ev) => {
      const s = overlayDragState;
      const z = $zoomEvents[s.idx];
      if (s.type === 'dot') {
        z.nx = Math.max(0.02, Math.min(0.98, (ev.clientX - s.ox) / s.w));
        z.ny = Math.max(0.02, Math.min(0.98, (ev.clientY - s.oy) / s.h));
      } else if (s.type === 'rect') {
        z.nx = Math.max(0.02, Math.min(0.98, (ev.clientX - s.ox) / s.w + s.offsetNx));
        z.ny = Math.max(0.02, Math.min(0.98, (ev.clientY - s.oy) / s.h + s.offsetNy));
      } else if (s.type === 'handle') {
        const dy = s.startClientY - ev.clientY;
        const dx = ev.clientX - s.startClientX;
        z.zoom = Math.max(1.2, Math.min(4.0, s.startZoom + (dy - dx) * 0.01));
      }
      $zoomEvents = $zoomEvents;
      renderZoomOverlay();
    };
    const onUp = () => {
      overlayDragState = null;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      renderZoomOverlay();
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }
</script>

<div class="flex-1 flex items-center justify-center bg-bg relative min-h-[300px]">
  <video bind:this={videoEl} muted class="hidden"></video>
  <video bind:this={webcamEl} muted class="hidden"></video>
  <canvas bind:this={previewCanvas} class="max-w-full max-h-full cursor-pointer"
    on:click={() => { if (!overlayDragState) togglePlay(); }}
    on:dblclick={(e) => {
      if ($selectedZoomIdx < 0 || !$zoomEvents[$selectedZoomIdx]) return;
      const rect = previewCanvas.getBoundingClientRect();
      const nx = Math.max(0.02, Math.min(0.98, (e.clientX - rect.left) / rect.width));
      const ny = Math.max(0.02, Math.min(0.98, (e.clientY - rect.top) / rect.height));
      $zoomEvents[$selectedZoomIdx].nx = nx;
      $zoomEvents[$selectedZoomIdx].ny = ny;
      $zoomEvents = $zoomEvents;
      e.preventDefault();
    }}></canvas>
  <div bind:this={zoomOverlayEl} class="absolute pointer-events-none z-[2]"></div>
  {#if !$videoW}
    <div class="absolute flex flex-col items-center gap-3 text-txt3">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" class="text-txt3/50"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/><line x1="17" y1="17" x2="22" y2="17"/></svg>
      <div class="text-[13px] font-medium">Glisse tes fichiers dans le panneau</div>
      <div class="text-[11px] text-txt3/60">ou connecte OBS pour enregistrer</div>
    </div>
  {/if}
  {#if $videoW > 0}
    <div class="absolute top-3 right-3 bg-bg2/80 backdrop-blur-sm text-txt2 px-2.5 py-1 rounded-md text-[11px] font-mono border border-border">
      {getZoomState(videoEl?.currentTime || 0).zoom.toFixed(1)}x
    </div>
  {/if}
</div>
