<script>
  import { obsStatus, apiCall, showToast } from '../lib/store.js';
  import { handleObsStop } from '../lib/actions.js';

  let host = 'localhost';
  let port = 4455;
  let password = '';
  let collapsed = true;

  $: badgeCls = $obsStatus.recording ? 'badge-rec' : $obsStatus.connected ? 'badge-on' : 'badge-off';
  $: badgeText = $obsStatus.recording ? 'REC' : $obsStatus.connected ? 'ON' : 'OFF';

  async function connect() {
    showToast('Connexion a OBS...');
    const res = await apiCall('POST', '/api/obs/connect', { host, port, password });
    if (res.success) {
      $obsStatus = { connected: true, recording: false, label: res.message };
      showToast(res.message);
    } else {
      showToast(`Erreur: ${res.error}`);
    }
  }

  async function start() {
    const res = await apiCall('POST', '/api/obs/start', {});
    if (res.success) {
      $obsStatus = { ...$obsStatus, recording: true, label: 'Enregistrement...' };
      showToast('Enregistrement lance!');
    } else {
      showToast(`Erreur: ${res.error}`);
    }
  }

  async function stop() {
    showToast('Arret en cours...');
    await handleObsStop();
  }
</script>

<div class="rounded-lg border border-border bg-surface/50 overflow-hidden">
  <button class="w-full px-3 py-2 text-[12px] font-medium text-txt2 flex items-center gap-2 cursor-pointer select-none hover:bg-bg4/30 transition-colors" on:click={() => collapsed = !collapsed}>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="text-txt3"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
    OBS
    <span class="ml-auto text-[10px] px-1.5 py-0.5 rounded-md font-medium obs-badge {badgeCls}">{badgeText}</span>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-txt3 transition-transform" class:rotate-180={!collapsed}><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  {#if !collapsed}
    <div class="p-2.5 pt-1">
      {#each [
        { label: 'Host', type: 'text', value: host, set: v => host = v },
        { label: 'Port', type: 'number', value: port, set: v => port = v },
        { label: 'Pass', type: 'password', value: password, set: v => password = v },
      ] as field}
        <div class="flex items-center gap-2 mb-1.5">
          <label class="text-[11px] text-txt3 min-w-[38px] font-medium">{field.label}</label>
          <input type={field.type} value={field.value} on:input={(e) => field.set(e.target.value)}
            class="flex-1 px-2 py-1 bg-bg border border-border text-txt rounded-md text-[11px] outline-none transition-colors" />
        </div>
      {/each}
      <div class="flex gap-1.5 mt-2.5">
        <button class="flex-1 px-2 py-1.5 bg-bg4 text-txt2 text-[11px] font-medium rounded-md hover:brightness-125 transition-all" on:click={connect}>Connecter</button>
        <button class="obs-btn-rec flex-1 px-2 py-1.5 text-[11px] font-medium rounded-md transition-all disabled:opacity-30" disabled={!$obsStatus.connected || $obsStatus.recording} on:click={start}>Rec</button>
        <button class="obs-btn-stop flex-1 px-2 py-1.5 text-[11px] font-medium rounded-md transition-all disabled:opacity-30" disabled={!$obsStatus.recording} on:click={stop}>Stop</button>
      </div>
    </div>
  {/if}
</div>

<style>
  .obs-badge { background: rgba(38,39,43,0.4); color: #63636e; }
  .badge-rec { background: rgba(239,68,68,0.15); color: #ef4444; }
  .badge-on { background: rgba(34,197,94,0.15); color: #22c55e; }
  .badge-off { background: rgba(38,39,43,0.4); color: #63636e; }
  .obs-btn-rec { background: rgba(34,197,94,0.1); color: #22c55e; }
  .obs-btn-rec:hover:not(:disabled) { background: rgba(34,197,94,0.2); }
  .obs-btn-stop { background: rgba(239,68,68,0.1); color: #ef4444; }
  .obs-btn-stop:hover:not(:disabled) { background: rgba(239,68,68,0.2); }
</style>
