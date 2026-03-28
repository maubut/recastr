<script>
  import { videoW, videoH, videoDuration, cursorEvents, webcamInfo, zoomEvents, analysisReady, showToast, fmt, videoPath, webcamPath, logPath } from '../lib/store.js';
  import { getVideoEl, getWebcamEl, analyzeLocal } from '../lib/actions.js';

  let collapsed = false;
  let videoName = '';
  let webcamName = '';
  let logName = '';

  $: if ($videoPath) videoName = $videoPath.split(/[\\/]/).pop();
  $: if ($webcamPath) webcamName = $webcamPath.split(/[\\/]/).pop();
  $: if ($logPath) logName = $logPath.split(/[\\/]/).pop();

  $: videoInfo = ($videoW > 0 && $videoDuration > 0) ? `${$videoW}x${$videoH}, ${$videoDuration.toFixed(1)}s` : '';
  $: logInfo = ($cursorEvents.length > 0) ? `${$cursorEvents.length} events` : '';

  function handleDrop(e, type) {
    e.preventDefault();
    if (e.dataTransfer?.files?.length > 0) handleFile(e.dataTransfer.files[0], type);
  }

  async function handleFile(file, type) {
    if (type === 'video') {
      videoName = file.name;
      const url = URL.createObjectURL(file);
      const vid = getVideoEl();
      if (!vid) return;
      vid.src = url;
      vid.load();
      vid.addEventListener('loadedmetadata', () => {
        $videoW = vid.videoWidth;
        $videoH = vid.videoHeight;
        $videoDuration = vid.duration;
      }, { once: true });
    } else if (type === 'webcam') {
      webcamName = file.name;
      const url = URL.createObjectURL(file);
      const cam = getWebcamEl();
      if (!cam) return;
      cam.src = url;
      cam.load();
    } else if (type === 'log') {
      logName = file.name;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        $cursorEvents = data.events || [];
        const meta = data.metadata || {};
        $webcamInfo = meta.webcam || null;
        if ($cursorEvents.length > 0) analyzeLocal();
      } catch (err) {
        showToast(`Erreur: ${err.message}`);
      }
    }
  }

  function pickFile(type) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = type === 'log' ? '.json' : 'video/*,.mp4,.mkv,.avi,.mov,.webm';
    input.onchange = (e) => { if (e.target.files.length > 0) handleFile(e.target.files[0], type); };
    input.click();
  }

  $: fileCount = (videoName ? 1 : 0) + (webcamName ? 1 : 0) + (logName ? 1 : 0);
</script>

<div class="rounded-lg border border-border bg-surface/50 overflow-hidden">
  <button class="w-full px-3 py-2 text-[12px] font-medium text-txt2 flex items-center gap-2 cursor-pointer select-none hover:bg-bg4/30 transition-colors" on:click={() => collapsed = !collapsed}>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="text-txt3"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
    Fichiers
    <span class="ml-auto text-[10px] px-1.5 py-0.5 rounded-md bg-bg4 text-txt3 font-mono">{fileCount}/3</span>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-txt3 transition-transform" class:rotate-180={!collapsed}><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  {#if !collapsed}
    <div class="p-2.5 pt-1 flex flex-col gap-1.5">
      <div class="drop-zone" class:has-file={videoName}
           on:click={() => pickFile('video')} on:drop={(e) => handleDrop(e, 'video')} on:dragover|preventDefault>
        <div class="text-[10px] text-txt3 uppercase tracking-wider mb-0.5 font-medium">Video ecran</div>
        <div class="text-[12px] text-txt2 truncate">{videoName || 'Glisse ou clique...'}</div>
        {#if videoInfo}<div class="text-[10px] text-txt3 mt-0.5 font-mono">{videoInfo}</div>{/if}
      </div>
      <div class="drop-zone" class:has-file={webcamName}
           on:click={() => pickFile('webcam')} on:drop={(e) => handleDrop(e, 'webcam')} on:dragover|preventDefault>
        <div class="text-[10px] text-txt3 uppercase tracking-wider mb-0.5 font-medium">Webcam (opt.)</div>
        <div class="text-[12px] text-txt2 truncate">{webcamName || 'Glisse ou clique...'}</div>
      </div>
      <div class="drop-zone" class:has-file={logName}
           on:click={() => pickFile('log')} on:drop={(e) => handleDrop(e, 'log')} on:dragover|preventDefault>
        <div class="text-[10px] text-txt3 uppercase tracking-wider mb-0.5 font-medium">Cursor log</div>
        <div class="text-[12px] text-txt2 truncate">{logName || 'Glisse ou clique...'}</div>
        {#if logInfo}<div class="text-[10px] text-txt3 mt-0.5 font-mono">{logInfo}</div>{/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .drop-zone {
    border: 1px dashed rgba(255,255,255,0.1);
    border-radius: 0.375rem;
    padding: 0.625rem 0.75rem;
    cursor: pointer;
    transition: all 0.15s;
  }
  .drop-zone:hover {
    border-color: rgba(139,92,246,0.4);
    background: rgba(139,92,246,0.02);
  }
  .drop-zone.has-file {
    border-style: solid;
    border-color: rgba(34,197,94,0.2);
    background: rgba(34,197,94,0.03);
  }
</style>
