<script>
  import { onMount, onDestroy } from 'svelte';
  import { videoW, videoH, videoDuration, zoomEvents, cursorEvents, webcamInfo, selectedZoomIdx, options, layoutEvents } from '../lib/store.js';
  import { setVideoEl, setWebcamEl, getZoomState, getLayoutState, seekTo, togglePlay } from '../lib/actions.js';

  let previewCanvas;
  let ctx;
  let videoEl;
  let webcamEl;
  let zoomOverlayEl;
  let animFrame;
  let overlayDragState = null;
  let overlayInterval;

  // Temporal motion blur: accumulation buffer
  // Each frame, we blend the current video frame with the previous accumulated result.
  // This creates a natural trail that follows exact camera movement direction.
  let accumCanvas = null;
  let accumCtx = null;
  let prevSpeed = 0; // track speed for smooth ramp

  onMount(() => {
    ctx = previewCanvas.getContext('2d');
    // High-quality image interpolation for smooth zooms
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
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
    // Canvas is larger when background/padding is enabled
    const pad = $options.bg ? $options.padding / 100 : 0;
    const scale = 1 / (1 - 2 * pad);
    const targetW = Math.round($videoW * scale);
    const targetH = Math.round($videoH * scale);
    // Only resize if dimensions changed (resizing clears the canvas!)
    if (previewCanvas.width !== targetW || previewCanvas.height !== targetH) {
      previewCanvas.width = targetW;
      previewCanvas.height = targetH;
      if (ctx) {
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
      }
    }
  }

  function drawBackground(cw, ch) {
    const style = $options.bgStyle;
    if (style === 'carbon') {
      ctx.fillStyle = '#111113';
      ctx.fillRect(0, 0, cw, ch);
      // Subtle dot pattern
      ctx.fillStyle = 'rgba(255,255,255,0.03)';
      for (let y = 0; y < ch; y += 12) {
        for (let x = 0; x < cw; x += 12) {
          ctx.fillRect(x, y, 1, 1);
        }
      }
    } else if (style === 'gradient') {
      const grad = ctx.createLinearGradient(0, 0, cw, ch);
      grad.addColorStop(0, $options.bgColor1);
      grad.addColorStop(1, $options.bgColor2);
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, cw, ch);
    } else if (style === 'mesh') {
      ctx.fillStyle = '#0f0f12';
      ctx.fillRect(0, 0, cw, ch);
      ctx.strokeStyle = 'rgba(255,255,255,0.04)';
      ctx.lineWidth = 1;
      const step = 40;
      for (let x = 0; x < cw; x += step) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, ch); ctx.stroke(); }
      for (let y = 0; y < ch; y += step) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(cw, y); ctx.stroke(); }
    } else if (style === 'solid') {
      ctx.fillStyle = $options.bgColor1;
      ctx.fillRect(0, 0, cw, ch);
    }
  }

  function draw() {
    animFrame = requestAnimationFrame(draw);
    if (!videoEl?.videoWidth || !ctx) return;

    const t = videoEl.currentTime;
    const state = getZoomState(t);
    const vw = $videoW || videoEl.videoWidth;
    const vh = $videoH || videoEl.videoHeight;
    const cw = previewCanvas.width, ch = previewCanvas.height;

    // Clear canvas each frame
    ctx.clearRect(0, 0, cw, ch);

    const hasBg = $options.bg;
    const pad = hasBg ? $options.padding / 100 : 0;
    const radius = hasBg ? $options.borderRadius : 0;
    const hasLayoutEvents = $layoutEvents.length > 0;
    const layout = hasLayoutEvents ? getLayoutState(t) : null;

    // Video inset area (static padding or layout-driven)
    let vx, vy, vWidth, vHeight;
    if (layout && layout.screenW > 0) {
      vx = layout.screenX * cw;
      vy = layout.screenY * ch;
      vWidth = layout.screenW * cw;
      vHeight = vWidth / (vw / vh); // maintain aspect ratio
      if (vy + vHeight > ch) vHeight = ch - vy;
    } else if (layout && layout.screenW === 0) {
      // Screen hidden (cam-only mode)
      vx = 0; vy = 0; vWidth = 0; vHeight = 0;
    } else {
      vx = pad * cw;
      vy = pad * ch;
      vWidth = cw - 2 * vx;
      vHeight = ch - 2 * vy;
    }

    if (hasBg || hasLayoutEvents) {
      // Draw background
      drawBackground(cw, ch);

      // Inset shadow behind the video
      if ($options.insetShadow && vWidth > 0 && vHeight > 0) {
        ctx.save();
        ctx.shadowColor = 'rgba(0,0,0,0.5)';
        ctx.shadowBlur = 30;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = 8;
        ctx.fillStyle = 'rgba(0,0,0,1)';
        ctx.beginPath();
        ctx.roundRect(vx, vy, vWidth, vHeight, radius);
        ctx.fill();
        ctx.restore();
      }

      // Clip to rounded rect for video
      if (vWidth > 0 && vHeight > 0) {
        ctx.save();
        ctx.beginPath();
        ctx.roundRect(vx, vy, vWidth, vHeight, radius);
        ctx.clip();
      }
    }

    // Draw video (zoomed or not) into the inset area — with temporal motion blur
    if (vWidth > 0 && vHeight > 0) {
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';

      const speed = state.speed || 0;
      // Smooth speed ramp (avoid flicker)
      prevSpeed += (speed - prevSpeed) * 0.3;

      // Temporal motion blur: blend current frame with accumulated previous frames
      // trailAlpha = how much of the previous frame to retain (0 = none, 0.6 = strong trail)
      const useBlur = prevSpeed > 0.3;
      // Scale trail strength with camera speed, capped for taste
      const trailAlpha = useBlur ? Math.min(0.55, prevSpeed / 18.0) : 0;

      // Ensure accumulation buffer matches video inset size
      const bw = Math.round(vWidth);
      const bh = Math.round(vHeight);
      if (!accumCanvas || accumCanvas.width !== bw || accumCanvas.height !== bh) {
        accumCanvas = document.createElement('canvas');
        accumCanvas.width = bw;
        accumCanvas.height = bh;
        accumCtx = accumCanvas.getContext('2d');
        accumCtx.imageSmoothingEnabled = true;
        accumCtx.imageSmoothingQuality = 'high';
      }

      // Draw current video frame to accum buffer
      if (trailAlpha > 0.01) {
        // Temporal blend: keep trailAlpha of previous, draw (1-trailAlpha) of current on top
        // The previous frame already contains history → exponential decay trail
        accumCtx.globalAlpha = trailAlpha;
        accumCtx.drawImage(accumCanvas, 0, 0); // re-draw previous (faded)
        accumCtx.globalAlpha = 1.0;
      }

      // Draw the sharp current frame into the accum buffer
      if (trailAlpha > 0.01) {
        // Partially transparent current frame over the trail
        accumCtx.globalCompositeOperation = 'source-over';
        accumCtx.globalAlpha = 1.0 - trailAlpha * 0.6;
      } else {
        accumCtx.globalAlpha = 1.0;
      }

      if (state.zoom > 1.02) {
        const srcW = vw / state.zoom;
        const srcH = vh / state.zoom;
        const cx = state.cx * vw;
        const cy = state.cy * vh;
        const x1 = Math.max(0, Math.min(cx - srcW / 2, vw - srcW));
        const y1 = Math.max(0, Math.min(cy - srcH / 2, vh - srcH));
        accumCtx.drawImage(videoEl, x1, y1, srcW, srcH, 0, 0, bw, bh);
      } else {
        accumCtx.drawImage(videoEl, 0, 0, vw, vh, 0, 0, bw, bh);
      }
      accumCtx.globalAlpha = 1.0;

      // Draw the accumulated (motion-blurred) result to the main canvas
      ctx.drawImage(accumCanvas, 0, 0, bw, bh, vx, vy, vWidth, vHeight);
    }

    if (hasBg || hasLayoutEvents) {
      if (vWidth > 0 && vHeight > 0) ctx.restore();
    }

    // Webcam overlay — layout-driven or static
    if ($options.webcam || hasLayoutEvents) {
      const hasCam = webcamEl?.src && webcamEl.videoWidth > 0;
      const hasLegacyCam = $webcamInfo?.nx !== undefined;
      if (hasCam) {
        drawWebcam(webcamEl, 0, 0, webcamEl.videoWidth, webcamEl.videoHeight, layout);
      } else if (hasLegacyCam) {
        drawWebcam(videoEl, $webcamInfo.nx * vw, $webcamInfo.ny * vh, $webcamInfo.nw * vw, $webcamInfo.nh * vh, layout);
      }
    }

    // Click highlight
    if ($options.clickHighlight && $cursorEvents.length > 0) {
      let lo = 0, hi = $cursorEvents.length - 1;
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; if ($cursorEvents[mid].t <= t) lo = mid; else hi = mid - 1; }
      const cp = $cursorEvents[lo];
      if (cp?.click && cp.in === true && Math.abs(cp.t - t) < 0.6) {
        // Map normalized video coords to canvas coords (accounting for padding)
        let cpx = vx + cp.nx * vWidth, cpy = vy + cp.ny * vHeight;
        if (state.zoom > 1.05) {
          const zw = vw / state.zoom, zh = vh / state.zoom;
          const sx = Math.max(0, Math.min(state.cx * vw - zw/2, vw - zw));
          const sy = Math.max(0, Math.min(state.cy * vh - zh/2, vh - zh));
          cpx = vx + (cp.nx * vw - sx) / zw * vWidth;
          cpy = vy + (cp.ny * vh - sy) / zh * vHeight;
        }
        if (cpx >= vx && cpx <= vx + vWidth && cpy >= vy && cpy <= vy + vHeight) {
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
          const px = vx + (ev.nx || 0) * vWidth, py = vy + (ev.ny || 0) * vHeight;
          const alpha = Math.max(0.05, 1 - (t - ev.t) / 2);
          ctx.strokeStyle = `rgba(139,92,246,${alpha * 0.6})`;
          if (!started) { ctx.beginPath(); ctx.moveTo(px, py); started = true; }
          else { ctx.lineTo(px, py); ctx.stroke(); ctx.beginPath(); ctx.moveTo(px, py); }
        }
        ctx.restore();
        let nearest = null, bestDt = Infinity;
        for (const ev of $cursorEvents) { const d = Math.abs(ev.t - t); if (d < bestDt) { bestDt = d; nearest = ev; } }
        if (nearest && bestDt < 0.2) {
          const px = vx + (nearest.nx || 0) * vWidth, py = vy + (nearest.ny || 0) * vHeight;
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
          const px = vx + (ev.nx || 0) * vWidth, py = vy + (ev.ny || 0) * vHeight;
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

  function drawWebcam(src, srcX, srcY, srcW, srcH, layout) {
    const shape = $options.webcamShape;
    const cw = previewCanvas.width, ch = previewCanvas.height;
    const camAspect = srcW / Math.max(srcH, 1);
    let dstX, dstY, dstW, dstH;

    if (layout) {
      // Layout-driven positioning
      dstX = Math.round(layout.camX * cw);
      dstY = Math.round(layout.camY * ch);
      dstW = Math.round(layout.camW * cw);
      dstH = Math.round(layout.camH * ch);
    } else {
      // Static positioning from options
      const pos = $options.webcamPos;
      const sizePct = $options.webcamSize / 100;
      dstW = cw * sizePct;
      dstH = dstW / camAspect;
      const margin = cw * 0.02;
      if (pos === 'top-left') { dstX = margin; dstY = margin; }
      else if (pos === 'top-right') { dstX = cw - dstW - margin; dstY = margin; }
      else if (pos === 'bottom-right') { dstX = cw - dstW - margin; dstY = ch - dstH - margin; }
      else { dstX = margin; dstY = ch - dstH - margin; }
    }
    if (dstW <= 0 || dstH <= 0) return;

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

    // Compute video inset area in display coordinates
    const padFrac = $options.bg ? $options.padding / 100 : 0;
    const vidLeft = padFrac * oW;
    const vidTop = padFrac * oH;
    const vidW = oW - 2 * vidLeft;
    const vidH = oH - 2 * vidTop;

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

      // Dot — map normalized video coords to display coords
      const dot = document.createElement('div');
      Object.assign(dot.style, {
        position: 'absolute', width: '10px', height: '10px', borderRadius: '50%',
        background: '#8b5cf6', border: '2px solid rgba(255,255,255,0.8)',
        transform: 'translate(-50%,-50%)', cursor: 'grab', pointerEvents: 'auto', zIndex: '3',
        boxShadow: '0 0 8px rgba(139,92,246,0.4)',
        left: (vidLeft + nx * vidW) + 'px', top: (vidTop + ny * vidH) + 'px',
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
        left: (vidLeft + rx*vidW)+'px', top: (vidTop + ry*vidH)+'px',
        width: (rw*vidW)+'px', height: (rh*vidH)+'px',
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
        left: (vidLeft + (rx+rw)*vidW)+'px', top: (vidTop + (ry+rh)*vidH)+'px',
      });
      handle.addEventListener('mousedown', (e) => startOverlayDrag(e, i, 'handle'));
      zoomOverlayEl.appendChild(handle);
    }
  }

  function startOverlayDrag(e, idx, type) {
    e.preventDefault(); e.stopPropagation();
    const z = $zoomEvents[idx];
    const canvasRect = previewCanvas.getBoundingClientRect();
    // Compute video inset in display space
    const padFrac = $options.bg ? $options.padding / 100 : 0;
    const vidLeft = canvasRect.left + padFrac * canvasRect.width;
    const vidTop = canvasRect.top + padFrac * canvasRect.height;
    const vidW = canvasRect.width * (1 - 2 * padFrac);
    const vidH = canvasRect.height * (1 - 2 * padFrac);
    overlayDragState = {
      type, idx,
      startNx: z.nx || 0.5, startNy: z.ny || 0.5, startZoom: z.zoom || 2.0,
      startClientX: e.clientX, startClientY: e.clientY,
      ox: vidLeft, oy: vidTop, w: vidW, h: vidH,
    };
    if (type === 'rect') {
      const mx = (e.clientX - vidLeft) / vidW;
      const my = (e.clientY - vidTop) / vidH;
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
  <video bind:this={videoEl} muted style="position:absolute;width:1px;height:1px;opacity:0;pointer-events:none"></video>
  <video bind:this={webcamEl} muted style="position:absolute;width:1px;height:1px;opacity:0;pointer-events:none"></video>
  <canvas bind:this={previewCanvas} class="max-w-full max-h-full cursor-pointer"
    on:click={() => { if (!overlayDragState) togglePlay(); }}
    on:dblclick={(e) => {
      if ($selectedZoomIdx < 0 || !$zoomEvents[$selectedZoomIdx]) return;
      const rect = previewCanvas.getBoundingClientRect();
      // Map click to normalized video coords (accounting for padding)
      const padFrac = $options.bg ? $options.padding / 100 : 0;
      const rawNx = (e.clientX - rect.left) / rect.width;
      const rawNy = (e.clientY - rect.top) / rect.height;
      const nx = Math.max(0.02, Math.min(0.98, (rawNx - padFrac) / (1 - 2 * padFrac)));
      const ny = Math.max(0.02, Math.min(0.98, (rawNy - padFrac) / (1 - 2 * padFrac)));
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
