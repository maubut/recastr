<script>
  import { obsStatus } from '../lib/store.js';
</script>

<div class="flex items-center gap-3 px-5 py-3 border-b border-border bg-bg2/80 backdrop-blur-sm">
  <div class="flex items-center gap-2">
    <span class="text-accent font-semibold text-[15px] tracking-tight">Recastr</span>
    <span class="text-[10px] text-txt3 font-medium px-1.5 py-0.5 rounded bg-bg4/50 tracking-wide">beta</span>
  </div>
  <div class="ml-auto flex items-center gap-2.5">
    <div class="w-1.5 h-1.5 rounded-full"
      class:bg-red={$obsStatus.recording}
      class:animate-pulse={$obsStatus.recording}
      class:bg-green={$obsStatus.connected && !$obsStatus.recording}
      class:bg-txt3={!$obsStatus.connected}
    ></div>
    <span class="text-[11px] text-txt3 font-medium">{$obsStatus.label}</span>
  </div>
</div>
