<script>
  import { options, videoPath, apiCall, showToast, captionSegments } from '../lib/store.js';

  let collapsed = false;
  let transcribeStatus = '';

  async function startTranscribe() {
    transcribeStatus = 'Transcription...';
    const res = await apiCall('POST', '/api/transcribe', { video_path: null, model: $options.captionModel });
    if (res.success) {
      showToast('Transcription lancee...');
      pollTranscribe();
    } else {
      showToast(`Erreur: ${res.error}`);
      transcribeStatus = 'Erreur';
    }
  }

  async function pollTranscribe() {
    const res = await apiCall('GET', '/api/transcribe/status');
    if (res.state === 'running') {
      setTimeout(pollTranscribe, 2000);
    } else if (res.state === 'done') {
      $captionSegments = res.segments;
      transcribeStatus = `${$captionSegments.length} segments`;
      $options.captions = true;
      $options = $options;
      showToast(`Transcription: ${$captionSegments.length} segments`);
    } else if (res.state === 'error') {
      transcribeStatus = 'Erreur';
      showToast(`Erreur transcription: ${res.error}`);
    }
  }
</script>

<div class="rounded-lg border border-border bg-surface/50 overflow-hidden">
  <button class="w-full px-3 py-2 text-[12px] font-medium text-txt2 flex items-center gap-2 cursor-pointer select-none hover:bg-bg4/30 transition-colors" on:click={() => collapsed = !collapsed}>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="text-txt3"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
    Options
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="ml-auto text-txt3 transition-transform" class:rotate-180={!collapsed}><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  {#if !collapsed}
    <div class="p-2.5 pt-1.5">
      <!-- Background -->
      <div class="flex items-center gap-2 py-1.5">
        <input type="checkbox" bind:checked={$options.bg} />
        <label class="text-[11px] text-txt2 cursor-pointer">Background</label>
        <select bind:value={$options.bgStyle} class="ml-auto bg-bg border border-border text-txt2 rounded-md px-1.5 py-0.5 text-[10px] outline-none focus:border-accent/40">
          <option value="carbon">Carbon</option>
          <option value="gradient">Gradient</option>
          <option value="mesh">Mesh</option>
        </select>
      </div>

      <!-- Webcam -->
      <div class="mt-1.5 pt-1.5 border-t border-border">
        <div class="text-[10px] text-txt3 uppercase tracking-wider font-medium mb-1">Webcam</div>
        <div class="flex items-center gap-2 py-1">
          <input type="checkbox" bind:checked={$options.webcam} />
          <label class="text-[11px] text-txt2">Overlay</label>
        </div>
        <div class="flex items-center gap-2 py-1">
          <label class="text-[11px] text-txt3 min-w-[40px]">Forme</label>
          <select bind:value={$options.webcamShape} class="flex-1 bg-bg border border-border text-txt2 rounded-md px-1.5 py-0.5 text-[10px] outline-none focus:border-accent/40">
            <option value="circle">Cercle</option>
            <option value="rounded">Arrondi</option>
            <option value="rectangle">Rectangle</option>
          </select>
        </div>
        <div class="flex items-center gap-2 py-1">
          <label class="text-[11px] text-txt3 min-w-[40px]">Pos.</label>
          <select bind:value={$options.webcamPos} class="flex-1 bg-bg border border-border text-txt2 rounded-md px-1.5 py-0.5 text-[10px] outline-none focus:border-accent/40">
            <option value="bottom-right">Bas-droit</option>
            <option value="bottom-left">Bas-gauche</option>
            <option value="top-right">Haut-droit</option>
            <option value="top-left">Haut-gauche</option>
          </select>
        </div>
        <div class="flex items-center gap-2 py-1">
          <label class="text-[11px] text-txt3 min-w-[40px]">Taille</label>
          <input type="range" min="5" max="40" bind:value={$options.webcamSize} class="flex-1" />
          <span class="text-[10px] text-txt3 min-w-[28px] text-right font-mono">{$options.webcamSize}%</span>
        </div>
      </div>

      <!-- Captions -->
      <div class="mt-1.5 pt-1.5 border-t border-border">
        <div class="text-[10px] text-txt3 uppercase tracking-wider font-medium mb-1">Captions</div>
        <div class="flex items-center gap-2 py-1">
          <input type="checkbox" bind:checked={$options.captions} />
          <label class="text-[11px] text-txt2">Sous-titres auto</label>
        </div>
        <div class="flex items-center gap-2 py-1">
          <label class="text-[11px] text-txt3 min-w-[40px]">Style</label>
          <select bind:value={$options.captionStyle} class="flex-1 bg-bg border border-border text-txt2 rounded-md px-1.5 py-0.5 text-[10px] outline-none focus:border-accent/40">
            <option value="tiktok">TikTok</option>
            <option value="classic">Classique</option>
          </select>
        </div>
        <div class="flex items-center gap-2 py-1">
          <label class="text-[11px] text-txt3 min-w-[40px]">Model</label>
          <select bind:value={$options.captionModel} class="flex-1 bg-bg border border-border text-txt2 rounded-md px-1.5 py-0.5 text-[10px] outline-none focus:border-accent/40">
            <option value="tiny">tiny</option>
            <option value="base">base</option>
            <option value="small">small</option>
            <option value="medium">medium</option>
          </select>
        </div>
        <div class="flex gap-2 mt-1.5 items-center">
          <button class="px-2.5 py-1 bg-bg4/50 text-txt2 text-[10px] font-medium rounded-md hover:bg-bg4 transition-colors" on:click={startTranscribe}>Transcrire</button>
          {#if transcribeStatus}<span class="text-[10px] text-txt3">{transcribeStatus}</span>{/if}
        </div>
      </div>

      <!-- Cursor -->
      <div class="mt-1.5 pt-1.5 border-t border-border">
        <div class="text-[10px] text-txt3 uppercase tracking-wider font-medium mb-1">Curseur</div>
        <div class="flex items-center gap-2 py-1">
          <input type="checkbox" bind:checked={$options.clickHighlight} />
          <label class="text-[11px] text-txt2">Click highlight</label>
        </div>
      </div>

      <!-- Debug -->
      <div class="mt-1.5 pt-1.5 border-t border-border">
        <div class="text-[10px] text-txt3 uppercase tracking-wider font-medium mb-1">Debug</div>
        <div class="flex items-center gap-2 py-1">
          <input type="checkbox" bind:checked={$options.debugClicks} />
          <label class="text-[11px] text-txt2">Clics</label>
        </div>
        <div class="flex items-center gap-2 py-1">
          <input type="checkbox" bind:checked={$options.debugTrail} />
          <label class="text-[11px] text-txt2">Trail</label>
        </div>
      </div>
    </div>
  {/if}
</div>
