<script>
  import { toastMessage } from '../lib/store.js';
</script>

{#if $toastMessage}
  <div class="fixed bottom-5 left-1/2 -translate-x-1/2 bg-bg3 text-txt2 px-4 py-2 rounded-lg text-[12px] font-medium shadow-lg shadow-black/30 border border-border z-50" style="animation: slideUp 0.2s ease-out">
    {$toastMessage}
  </div>
{/if}
