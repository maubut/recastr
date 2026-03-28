<script>
  import Header from './components/Header.svelte';
  import Sidebar from './components/Sidebar.svelte';
  import Preview from './components/Preview.svelte';
  import Timeline from './components/Timeline.svelte';
  import BottomBar from './components/BottomBar.svelte';
  import RenderModal from './components/RenderModal.svelte';
  import Toast from './components/Toast.svelte';
  import { videoDuration } from './lib/store.js';
</script>

<Header />
<div class="grid grid-cols-[280px_1fr] h-[calc(100vh-49px)]">
  <Sidebar />
  <div class="flex flex-col overflow-hidden">
    <Preview />
    {#if $videoDuration > 0}
      <Timeline />
    {/if}
    <BottomBar />
  </div>
</div>
<RenderModal />
<Toast />
