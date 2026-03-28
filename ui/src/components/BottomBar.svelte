<script>
  import { videoDuration, fmt } from '../lib/store.js';
  import { togglePlay, setSpeed, seekTo, getVideoEl } from '../lib/actions.js';

  let timeDisplay = '00:00.0 / 00:00.0';
  let currentSpeed = 1;

  function tick() {
    const vid = getVideoEl();
    if (vid) timeDisplay = `${fmt(vid.currentTime)} / ${fmt($videoDuration)}`;
    requestAnimationFrame(tick);
  }
  tick();

  function changeSpeed(s) {
    currentSpeed = s;
    setSpeed(s);
  }
</script>

<div class="flex items-center gap-3 px-4 py-2 bg-bg2 border-t border-border shrink-0">
  <button class="w-7 h-7 flex items-center justify-center rounded-md text-txt3 hover:text-txt hover:bg-bg4/50 transition-colors" on:click={togglePlay}>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
  </button>
  <div class="font-mono text-[12px] text-txt2 min-w-[120px] tracking-tight">{timeDisplay}</div>
  <div class="ml-auto flex gap-0.5">
    {#each [0.5, 1, 2] as s}
      <button
        class="px-2 py-1 text-[10px] font-medium rounded-md transition-colors {currentSpeed === s ? 'bg-accent/15 text-accent' : 'text-txt3 hover:text-txt2 hover:bg-bg4/30'}"
        on:click={() => changeSpeed(s)}
      >{s}x</button>
    {/each}
  </div>
</div>
