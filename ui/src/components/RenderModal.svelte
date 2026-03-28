<script>
  import { onMount, onDestroy } from 'svelte';
  import { apiCall } from '../lib/store.js';

  let show = false;
  let title = 'Render en cours...';
  let progressPct = 0;
  let progressText = 'Preparation...';
  let showClose = false;

  function onRenderStart(e) {
    show = true; title = 'Render en cours...'; progressPct = 0; progressText = 'Preparation...'; showClose = false;
    doRender(e.detail);
  }

  async function doRender(config) {
    const res = await apiCall('POST', '/api/render', config);
    if (res.success) {
      pollRender();
    } else {
      title = 'Erreur'; progressText = res.error; showClose = true;
    }
  }

  async function pollRender() {
    const res = await apiCall('GET', '/api/render/status');
    progressPct = res.total_frames > 0 ? (res.frames_done / res.total_frames * 100) : 0;
    progressText = `${res.frames_done} / ${res.total_frames} frames (${progressPct.toFixed(0)}%)`;
    if (res.state === 'running') { setTimeout(pollRender, 1000); }
    else if (res.state === 'done') { title = 'Render termine!'; progressPct = 100; progressText = `Sortie: ${res.output_path}`; showClose = true; }
    else if (res.state === 'error') { title = 'Erreur render'; progressText = res.error; showClose = true; }
  }

  onMount(() => window.addEventListener('render-start', onRenderStart));
  onDestroy(() => window.removeEventListener('render-start', onRenderStart));
</script>

{#if show}
  <div class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
    <div class="bg-bg2 border border-border rounded-xl p-6 min-w-[400px] max-w-[500px] shadow-2xl shadow-black/50">
      <h3 class="mb-1 text-[15px] font-medium text-txt">{title}</h3>
      <p class="text-[12px] text-txt3 mb-4">{progressText}</p>
      <div class="h-1 bg-bg4/50 rounded-full overflow-hidden">
        <div class="h-full bg-accent rounded-full transition-[width] duration-500 ease-out" style="width:{progressPct}%"></div>
      </div>
      {#if showClose}
        <div class="mt-5 flex justify-end">
          <button class="px-4 py-1.5 text-[12px] font-medium text-txt2 rounded-lg hover:bg-bg4/50 border border-border transition-colors" on:click={() => show = false}>Fermer</button>
        </div>
      {/if}
    </div>
  </div>
{/if}
