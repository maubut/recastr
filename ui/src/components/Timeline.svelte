<script>
  import { onMount } from 'svelte';
  import { zoomEvents, videoDuration, selectedZoomIdx, cursorEvents, layoutEvents, selectedLayoutIdx, LAYOUT_PRESETS, fmt } from '../lib/store.js';
  import { seekTo } from '../lib/actions.js';
  import { getVideoEl } from '../lib/actions.js';

  const LAYOUT_ROW_Y = 80; // y position for layout event row
  const LAYOUT_ROW_H = 16;
  const LAYOUT_COLORS = { intro: '#f59e0b', demo: '#3b82f6', split: '#10b981', 'cam-only': '#ec4899' };
  const LAYOUT_LABELS = { intro: 'Intro', demo: 'Demo', split: 'Split', 'cam-only': 'Cam' };

  let canvas;
  let ctx;
  let tlDrag = null;
  let dragOutIdx = -1;       // index of zoom being dragged out (visual ghost)
  let dragOutOpacity = 1;    // fades as user drags further away
  const EDGE_PX = 8;
  const DRAG_OUT_THRESHOLD = 50; // px above/below timeline to trigger delete

  onMount(() => {
    ctx = canvas.getContext('2d');
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 100;
    renderTimeline();
  });

  $: if (ctx && $zoomEvents) { syncCanvasSize(); renderTimeline(); }
  $: if (ctx && $selectedZoomIdx !== undefined) renderTimeline();
  $: if (ctx && $layoutEvents) { syncCanvasSize(); renderTimeline(); }
  $: if (ctx && $selectedLayoutIdx !== undefined) renderTimeline();
  $: if (ctx && $videoDuration > 0) { syncCanvasSize(); renderTimeline(); }

  function renderTimeline() {
    if (!ctx) return;
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#111113'; ctx.fillRect(0, 0, w, h);
    if ($videoDuration <= 0) return;

    // Time markers
    const step = $videoDuration > 120 ? 30 : $videoDuration > 30 ? 10 : 5;
    ctx.fillStyle = 'rgba(255,255,255,0.04)'; ctx.font = '9px monospace';
    for (let t = 0; t <= $videoDuration; t += step) {
      const x = (t / $videoDuration) * w;
      ctx.fillRect(x, 0, 1, h);
      ctx.fillStyle = 'rgba(255,255,255,0.2)';
      ctx.fillText(fmt(t), x + 4, 12);
      ctx.fillStyle = 'rgba(255,255,255,0.04)';
    }

    // Zoom events
    const colors = { click: [139,92,246], arrive: [59,130,246], still: [234,179,8], manual: [34,197,94] };
    for (let i = 0; i < $zoomEvents.length; i++) {
      const z = $zoomEvents[i];
      if (!z.enabled) continue;
      const dur = (z.ease_in || 0.3) + (z.hold || 1.5) + (z.ease_out || 0.5);
      const x1 = (z.time / $videoDuration) * w;
      const x2 = ((z.time + dur) / $videoDuration) * w;
      const c = colors[z.type] || [139,92,246];
      const isSel = (i === $selectedZoomIdx);
      const isDragOut = (i === dragOutIdx);

      // Bar (fades + turns red when being dragged out)
      const barAlpha = isDragOut ? dragOutOpacity * 0.15 : (isSel ? 0.25 : 0.12);
      const bc = isDragOut ? [239,68,68] : c;
      ctx.fillStyle = `rgba(${bc[0]},${bc[1]},${bc[2]},${barAlpha})`;
      const r = 3;
      ctx.beginPath(); ctx.roundRect(x1, 18, Math.max(x2-x1, 4), h-36, r); ctx.fill();

      // Border for selected
      if (isSel && !isDragOut) {
        ctx.strokeStyle = `rgba(${c[0]},${c[1]},${c[2]},0.5)`;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.roundRect(x1, 18, x2-x1, h-36, r); ctx.stroke();
      }
      // Dashed red border when dragging out
      if (isDragOut) {
        ctx.strokeStyle = `rgba(239,68,68,${dragOutOpacity * 0.6})`;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.roundRect(x1, 18, x2-x1, h-36, r); ctx.stroke();
        ctx.setLineDash([]);
      }

      // Left edge marker
      ctx.fillStyle = `rgba(${bc[0]},${bc[1]},${bc[2]},${isDragOut ? dragOutOpacity * 0.5 : (isSel ? 0.8 : 0.5)})`;
      ctx.beginPath(); ctx.roundRect(x1, 18, 2, h-36, 1); ctx.fill();

      // Resize handles for selected
      if (isSel) {
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.beginPath(); ctx.roundRect(x1-1, 22, 3, h-44, 1); ctx.fill();
        ctx.beginPath(); ctx.roundRect(x2-2, 22, 3, h-44, 1); ctx.fill();
      }

      // Label
      if (x2-x1 > 28) {
        ctx.fillStyle = `rgba(255,255,255,${isSel ? 0.7 : 0.4})`;
        ctx.font = '9px monospace';
        ctx.fillText(z.zoom.toFixed(1) + 'x', x1 + 6, 32);
      }
    }

    // Layout events row
    if ($layoutEvents.length > 0) {
      // Row background
      ctx.fillStyle = 'rgba(255,255,255,0.02)';
      ctx.fillRect(0, LAYOUT_ROW_Y, w, LAYOUT_ROW_H);
      // Label
      ctx.fillStyle = 'rgba(255,255,255,0.15)';
      ctx.font = '8px monospace';
      ctx.fillText('LAYOUT', 4, LAYOUT_ROW_Y + 11);

      for (let i = 0; i < $layoutEvents.length; i++) {
        const le = $layoutEvents[i];
        const x = (le.time / $videoDuration) * w;
        const nextTime = $layoutEvents[i + 1]?.time ?? $videoDuration;
        const x2 = (nextTime / $videoDuration) * w;
        const color = LAYOUT_COLORS[le.preset] || '#8b5cf6';
        const isSel = (i === $selectedLayoutIdx);

        // Bar spanning until next keyframe
        ctx.fillStyle = color + (isSel ? '30' : '18');
        ctx.beginPath(); ctx.roundRect(x, LAYOUT_ROW_Y + 1, Math.max(x2 - x, 4), LAYOUT_ROW_H - 2, 2); ctx.fill();

        // Diamond marker at keyframe time
        ctx.fillStyle = color;
        const dy = LAYOUT_ROW_Y + LAYOUT_ROW_H / 2;
        ctx.beginPath();
        ctx.moveTo(x, dy - 5); ctx.lineTo(x + 5, dy); ctx.lineTo(x, dy + 5); ctx.lineTo(x - 5, dy); ctx.closePath();
        ctx.fill();
        if (isSel) {
          ctx.strokeStyle = '#fff'; ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(x, dy - 5); ctx.lineTo(x + 5, dy); ctx.lineTo(x, dy + 5); ctx.lineTo(x - 5, dy); ctx.closePath();
          ctx.stroke();
        }

        // Label
        if (x2 - x > 30) {
          ctx.fillStyle = 'rgba(255,255,255,0.5)';
          ctx.font = '8px monospace';
          ctx.fillText(LAYOUT_LABELS[le.preset] || le.preset, x + 8, LAYOUT_ROW_Y + 11);
        }
      }
    }

    // Playhead
    const vid = getVideoEl();
    if (vid) {
      const x = (vid.currentTime / Math.max($videoDuration, 0.1)) * w;
      ctx.strokeStyle = 'rgba(255,255,255,0.6)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      // Playhead triangle
      ctx.fillStyle = 'rgba(255,255,255,0.8)';
      ctx.beginPath(); ctx.moveTo(x-4, 0); ctx.lineTo(x+4, 0); ctx.lineTo(x, 6); ctx.closePath(); ctx.fill();
    }
  }

  let rafId;
  onMount(() => {
    const tick = () => { renderTimeline(); rafId = requestAnimationFrame(tick); };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  });

  function hitTest(px, py) {
    const w = canvas.width;
    for (let i = $zoomEvents.length - 1; i >= 0; i--) {
      const z = $zoomEvents[i];
      if (!z.enabled) continue;
      const dur = (z.ease_in || 0.3) + (z.hold || 1.5) + (z.ease_out || 0.5);
      const x1 = (z.time / $videoDuration) * w;
      const x2 = ((z.time + dur) / $videoDuration) * w;
      if (px >= x1-2 && px <= x2+2 && py >= 18 && py <= LAYOUT_ROW_Y) {
        if (px <= x1 + EDGE_PX) return { idx: i, zone: 'left' };
        if (px >= x2 - EDGE_PX) return { idx: i, zone: 'right' };
        return { idx: i, zone: 'body' };
      }
    }
    return null;
  }

  function layoutHitTest(px, py) {
    if (py < LAYOUT_ROW_Y || py > LAYOUT_ROW_Y + LAYOUT_ROW_H) return null;
    const w = canvas.width;
    for (let i = $layoutEvents.length - 1; i >= 0; i--) {
      const le = $layoutEvents[i];
      const x = (le.time / $videoDuration) * w;
      if (px >= x - 8 && px <= x + 8) return { idx: i };
    }
    return null;
  }

  // Scrub drag state: click+drag on empty area = scrub
  let scrubDrag = null; // { wasPlaying: bool }

  // Sync internal canvas resolution with displayed size (prevents seek offset bugs)
  function syncCanvasSize() {
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth;
    if (w > 0 && canvas.width !== w) {
      canvas.width = w;
      canvas.height = 100;
      renderTimeline();
    }
  }

  function onMouseDown(e) {
    if ($videoDuration <= 0) return;
    syncCanvasSize(); // ensure canvas.width matches display before computing positions
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    // Use display width (rect.width) for time calculation — always accurate
    const w = rect.width;
    const hit = hitTest(px, py);
    // Check layout events first
    const layoutHit = layoutHitTest(px, py);
    if (layoutHit) {
      $selectedLayoutIdx = layoutHit.idx;
      $selectedZoomIdx = -1;
      tlDrag = { type: 'layout-move', idx: layoutHit.idx, startX: px, startTime: $layoutEvents[layoutHit.idx].time, moved: false };
      seekTo($layoutEvents[layoutHit.idx].time);
      e.preventDefault();
      return;
    }

    if (hit) {
      const z = $zoomEvents[hit.idx];
      if (hit.zone === 'body') tlDrag = { type: 'move', idx: hit.idx, startX: px, startTime: z.time, moved: false };
      else if (hit.zone === 'left') tlDrag = { type: 'resize-left', idx: hit.idx, startX: px, startTime: z.time, startEaseIn: z.ease_in || 0.3, moved: false };
      else tlDrag = { type: 'resize-right', idx: hit.idx, startX: px, startHold: z.hold || 1.5, moved: false };
      $selectedZoomIdx = hit.idx;
      $selectedLayoutIdx = -1;
      e.preventDefault();
    } else {
      // Click on empty area: start scrub drag
      const vid = getVideoEl();
      const wasPlaying = vid ? !vid.paused : false;
      if (vid && wasPlaying) vid.pause();
      scrubDrag = { wasPlaying };
      const clickTime = Math.max(0, Math.min($videoDuration, (px / w) * $videoDuration));
      seekTo(clickTime);
      $selectedZoomIdx = -1;
      $selectedLayoutIdx = -1;
      e.preventDefault();
    }
  }

  function onDblClick(e) {
    if ($videoDuration <= 0) return;
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const w = rect.width;

    // Double-click in layout row → add layout keyframe
    if (py >= LAYOUT_ROW_Y && py <= LAYOUT_ROW_Y + LAYOUT_ROW_H) {
      const layoutHit = layoutHitTest(px, py);
      if (layoutHit) return; // don't create on top of existing
      const time = Math.round((px / w) * $videoDuration * 100) / 100;
      const newLayout = { time, preset: 'demo', transition: 0.8, ...LAYOUT_PRESETS['demo'] };
      $layoutEvents = [...$layoutEvents, newLayout].sort((a, b) => a.time - b.time);
      const newIdx = $layoutEvents.findIndex(l => l === newLayout);
      $selectedLayoutIdx = newIdx;
      $selectedZoomIdx = -1;
      seekTo(time);
      return;
    }

    // Don't create if double-clicking on an existing zoom
    const hit = hitTest(px, py);
    if (hit) return;
    // Create manual zoom at click position
    const time = Math.round((px / w) * $videoDuration * 100) / 100;
    // Find cursor position at this time (if cursor log is loaded)
    let nx = 0.5, ny = 0.5;
    if ($cursorEvents.length > 0) {
      let lo = 0, hi = $cursorEvents.length - 1;
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; if ($cursorEvents[mid].t <= time) lo = mid; else hi = mid - 1; }
      const ev = $cursorEvents[lo];
      if (ev && Math.abs(ev.t - time) < 2.0) {
        nx = ev.nx || 0.5;
        ny = ev.ny || 0.5;
      }
    }
    const newZoom = {
      time, nx, ny, zoom: 2.0,
      hold: 1.5, ease_in: 0.3, ease_out: 0.5,
      type: 'manual', enabled: true,
    };
    $zoomEvents = [...$zoomEvents, newZoom].sort((a, b) => a.time - b.time);
    // Select the newly created zoom
    const newIdx = $zoomEvents.findIndex(z => z === newZoom);
    $selectedZoomIdx = newIdx;
    seekTo(time);
  }

  function onMouseMove(e) {
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    const w = rect.width; // use display width for accurate time mapping

    // Scrub drag: click+drag on empty area scrubs through video
    if (scrubDrag) {
      const scrubTime = Math.max(0, Math.min($videoDuration, (px / w) * $videoDuration));
      seekTo(scrubTime);
      return;
    }

    if (tlDrag) {
      const dx = px - tlDrag.startX;
      const dt = (dx / w) * $videoDuration;
      const z = $zoomEvents[tlDrag.idx];
      tlDrag.moved = true;

      // Check vertical drag-out distance
      const distOut = py < 0 ? -py : (py > canvas.height ? py - canvas.height : 0);
      if (tlDrag.type === 'move' && distOut > 15) {
        dragOutIdx = tlDrag.idx;
        dragOutOpacity = Math.max(0.15, 1 - distOut / (DRAG_OUT_THRESHOLD * 1.5));
      } else {
        dragOutIdx = -1;
        dragOutOpacity = 1;
      }

      if (tlDrag.type === 'layout-move') {
        const le = $layoutEvents[tlDrag.idx];
        le.time = Math.max(0, Math.min($videoDuration - 0.1, Math.round((tlDrag.startTime + dt) * 100) / 100));
        $layoutEvents = $layoutEvents;
        seekTo(le.time);
      } else if (tlDrag.type === 'move') { z.time = Math.max(0, Math.min($videoDuration-1, Math.round((tlDrag.startTime+dt)*100)/100)); seekTo(z.time); }
      else if (tlDrag.type === 'resize-left') { const nt = Math.max(0, tlDrag.startTime+dt); z.time = Math.round(nt*100)/100; z.ease_in = Math.max(0.1, Math.round((tlDrag.startEaseIn-(nt-tlDrag.startTime))*100)/100); seekTo(nt); }
      else { z.hold = Math.max(0.3, Math.round((tlDrag.startHold+dt)*100)/100); }
      if (tlDrag.type !== 'layout-move') $zoomEvents = $zoomEvents;
    } else {
      // No drag: just update cursor style
      const hit = hitTest(px, py);
      const layoutHit = layoutHitTest(px, py);
      canvas.style.cursor = layoutHit ? 'grab' : (!hit ? 'default' : (hit.zone === 'body' ? 'grab' : 'ew-resize'));
    }
  }

  function onMouseUp(e) {
    // End scrub drag: restore playback if was playing
    if (scrubDrag) {
      if (scrubDrag.wasPlaying) {
        const vid = getVideoEl();
        if (vid) vid.play().catch(() => {});
      }
      scrubDrag = null;
      return;
    }

    if (tlDrag) {
      const rect = canvas.getBoundingClientRect();
      const py = e.clientY - rect.top;
      const distOut = py < 0 ? -py : (py > canvas.height ? py - canvas.height : 0);

      // Drag-out delete: if moved far enough vertically during a body drag
      if (tlDrag.type === 'move' && distOut >= DRAG_OUT_THRESHOLD) {
        $zoomEvents = $zoomEvents.filter((_, i) => i !== tlDrag.idx);
        $selectedZoomIdx = -1;
      } else if (!tlDrag.moved) {
        // Click without drag on zoom event: select and seek
        $selectedZoomIdx = tlDrag.idx;
        seekTo($zoomEvents[tlDrag.idx].time);
      }

      dragOutIdx = -1;
      dragOutOpacity = 1;
      tlDrag = null; canvas.style.cursor = 'default';
      return;
    }
  }
</script>

<svelte:window on:resize={() => { if (canvas?.parentElement) { canvas.width = canvas.parentElement.clientWidth; renderTimeline(); } }} />

<div class="h-[100px] bg-bg2 border-t border-border relative shrink-0">
  <canvas bind:this={canvas} class="w-full h-full cursor-crosshair"
    on:mousedown={onMouseDown} on:mousemove={onMouseMove} on:mouseup={onMouseUp}
    on:dblclick={onDblClick}
    on:mouseleave={() => {
      if (tlDrag) { tlDrag = null; dragOutIdx = -1; dragOutOpacity = 1; canvas.style.cursor = 'default'; }
      if (scrubDrag) {
        if (scrubDrag.wasPlaying) { const vid = getVideoEl(); if (vid) vid.play().catch(() => {}); }
        scrubDrag = null;
      }
    }}></canvas>
</div>
