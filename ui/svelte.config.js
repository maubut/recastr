/** @type {import("@sveltejs/vite-plugin-svelte").SvelteConfig} */
export default {
  onwarn: (warning, handler) => {
    if (warning.code.startsWith('a11y_')) return;
    handler(warning);
  }
}
