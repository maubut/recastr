<script>
  import { zoomEvents, selectedZoomIdx, videoDuration, fmt, showToast } from '../lib/store.js';
  import { seekTo } from '../lib/actions.js';

  let collapsed = false;

  function selectZoom(idx) {
    // Click always selects (never deselects) — click elsewhere or another zoom to deselect
    $selectedZoomIdx = idx;
    seekTo($zoomEvents[idx].time);
  }

  function updateProp(idx, prop, val) {
    $zoomEvents[idx][prop] = val;
    $zoomEvents = $zoomEvents;
    if (prop === 'time') seekTo(val);
  }

  function duplicateZoom(idx) {
    const orig = $zoomEvents[idx];
    const copy = JSON.parse(JSON.stringify(orig));
    copy.time = orig.time + (orig.hold || 1.5) + (orig.ease_out || 0.5) + 0.5;
    $zoomEvents = [...$zoomEvents.slice(0, idx + 1), copy, ...$zoomEvents.slice(idx + 1)];
    $selectedZoomIdx = idx + 1;
  }

  function deleteZoom(idx) {
    $zoomEvents = $zoomEvents.filter((_, i) => i !== idx);
    $selectedZoomIdx = -1;
  }

  function applyBatch(prop, val) {
    $zoomEvents = $zoomEvents.map(z => ({ ...z, [prop]: val }));
  }

  const typeColor = { click: 'text-accent', arrive: 'text-blue', still: 'text-yellow' };
  const typeBg = { click: 'bg-accent/10', arrive: 'bg-blue/10', still: 'bg-yellow/10' };

  $: enabledCount = $zoomEvents.filter(z => z.enabled).length;
</script>

<div class="rounded-lg border border-border bg-surface/50 overflow-hidden">
  <button class="w-full px-3 py-2 text-[12px] font-medium text-txt2 flex items-center gap-2 cursor-pointer select-none hover:bg-bg4/30 transition-colors" on:click={() => collapsed = !collapsed}>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="text-txt3"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M11 8v6"/><path d="M8 11h6"/></svg>
    Zooms
    <span class="ml-auto text-[10px] px-1.5 py-0.5 rounded-md bg-accent/10 text-accent font-mono font-medium">{enabledCount}</span>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-txt3 transition-transform" class:rotate-180={!collapsed}><polyline points="6 9 12 15 18 9"/></svg>
  </button>

  {#if !collapsed}
    <!-- Batch controls -->
    {#if $zoomEvents.length > 0}
      <div class="px-2.5 py-2 border-b border-border">
        <div class="text-[10px] text-txt3 uppercase tracking-wider font-medium mb-1.5">Batch</div>
        {#each [
          { label: 'Zoom', prop: 'zoom', min: 1.2, max: 4, step: 0.1, fmt: v => v.toFixed(1) + 'x' },
          { label: 'Hold', prop: 'hold', min: 0.3, max: 10, step: 0.1, fmt: v => v.toFixed(1) + 's' },
          { label: 'In', prop: 'ease_in', min: 0.1, max: 2, step: 0.05, fmt: v => v.toFixed(2) + 's' },
          { label: 'Out', prop: 'ease_out', min: 0.1, max: 2, step: 0.05, fmt: v => v.toFixed(2) + 's' },
        ] as slider}
          <div class="flex items-center gap-1.5 mb-0.5">
            <label class="w-[32px] text-[10px] text-txt3">{slider.label}</label>
            <input type="range" min={slider.min} max={slider.max} step={slider.step}
                   value={$zoomEvents[0]?.[slider.prop] || slider.min}
                   on:input={(e) => applyBatch(slider.prop, +e.target.value)}
                   class="flex-1" />
            <span class="w-[34px] text-[10px] text-accent font-mono text-right">{slider.fmt($zoomEvents[0]?.[slider.prop] || slider.min)}</span>
          </div>
        {/each}
      </div>
    {/if}

    <!-- Zoom list -->
    <div class="max-h-[240px] overflow-y-auto">
      {#if $zoomEvents.length === 0}
        <div class="text-txt3 text-[11px] p-3">Aucun zoom detecte</div>
      {:else}
        <div class="p-1">
          {#each $zoomEvents as z, i}
            {@const selected = i === $selectedZoomIdx}
            {@const typeCls = z.type === 'click' ? 'text-accent bg-accent/10' : z.type === 'arrive' ? 'text-blue bg-blue/10' : z.type === 'still' ? 'text-yellow bg-yellow/10' : 'text-txt3 bg-bg4'}
            <div class="flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer text-[11px] transition-all duration-100 hover:bg-bg4"
                 class:selected
                 class:disabled={!z.enabled}
                 on:click={() => selectZoom(i)}>
              <input type="checkbox" checked={z.enabled}
                     on:click|stopPropagation={() => { $zoomEvents[i].enabled = !z.enabled; $zoomEvents = $zoomEvents; }} />
              <span class="font-mono text-txt3 text-[10px]">{fmt(z.time)}</span>
              <span class="text-[9px] px-1 py-0.5 rounded font-medium {typeCls}">{z.type}</span>
              <span class="ml-auto text-txt font-mono text-[11px] font-medium">{z.zoom.toFixed(1)}x</span>
            </div>

            {#if i === $selectedZoomIdx}
              <div class="mx-1 mb-1 p-2 bg-bg rounded-md border border-border">
                {#each [
                  { label: 'Zoom', prop: 'zoom', min: 1.2, max: 4, step: 0.1, fmt: v => v.toFixed(1) + 'x' },
                  { label: 'Time', prop: 'time', min: 0, max: $videoDuration || 60, step: 0.1, fmt: v => fmt(v) },
                  { label: 'Hold', prop: 'hold', min: 0.3, max: 10, step: 0.1, fmt: v => v.toFixed(1) + 's' },
                  { label: 'In', prop: 'ease_in', min: 0.1, max: 2, step: 0.05, fmt: v => v.toFixed(2) + 's' },
                  { label: 'Out', prop: 'ease_out', min: 0.1, max: 2, step: 0.05, fmt: v => v.toFixed(2) + 's' },
                ] as s}
                  <div class="flex items-center gap-1.5 mb-1">
                    <label class="text-txt3 min-w-[32px] text-[10px] font-medium">{s.label}</label>
                    <input type="range" min={s.min} max={s.max} step={s.step} value={z[s.prop] || s.min}
                           on:input={(e) => updateProp(i, s.prop, +e.target.value)}
                           class="flex-1" />
                    <span class="text-txt2 font-mono min-w-[38px] text-right text-[10px]">{s.fmt(z[s.prop] || s.min)}</span>
                  </div>
                {/each}
                <div class="flex gap-1.5 mt-2 pt-1.5 border-t border-border">
                  <button class="px-2 py-1 rounded-md text-[10px] text-txt3 font-medium hover:bg-bg4/50 hover:text-txt2 transition-colors" on:click={() => duplicateZoom(i)}>Dupliquer</button>
                  <button class="px-2 py-1 rounded-md text-[10px] text-red/70 font-medium hover:bg-red/10 hover:text-red transition-colors" on:click={() => deleteZoom(i)}>Supprimer</button>
                </div>
              </div>
            {/if}
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .selected { background: rgba(38, 39, 43, 0.6); }
  .disabled { opacity: 0.25; }
</style>
