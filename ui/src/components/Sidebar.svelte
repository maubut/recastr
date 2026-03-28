<script>
  import FilePanel from './FilePanel.svelte';
  import ObsPanel from './ObsPanel.svelte';
  import ZoomPanel from './ZoomPanel.svelte';
  import OptionsPanel from './OptionsPanel.svelte';
  import { videoW, showToast } from '../lib/store.js';
  import { startRender } from '../lib/actions.js';

  $: canRender = $videoW > 0;
</script>

<div class="bg-bg2 border-r border-border overflow-y-auto flex flex-col">
  <div class="p-3 flex flex-col gap-2 flex-1">
    <FilePanel />
    <ObsPanel />
    <ZoomPanel />
    <OptionsPanel />
  </div>
  <div class="p-3 pt-0">
    <button
      class="w-full py-2.5 bg-accent text-white font-medium rounded-lg text-[13px] disabled:opacity-30 disabled:cursor-not-allowed hover:bg-accent2 transition-colors duration-150 flex items-center justify-center gap-2"
      disabled={!canRender}
      on:click={startRender}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      Render
    </button>
  </div>
</div>
