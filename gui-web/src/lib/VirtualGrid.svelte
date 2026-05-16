<script lang="ts" generics="T">
  import { onMount } from 'svelte';

  export let items: T[];
  export let itemHeight: number;
  export let itemWidth: number;
  export let gap = 12;

  let container: HTMLDivElement;
  let scrollY = 0;
  let viewportH = 0;
  let viewportW = 0;

  $: cols = Math.max(1, Math.floor((viewportW + gap) / (itemWidth + gap)));
  $: cellH = itemHeight + gap;
  $: cellW = itemWidth + gap;
  $: rows = Math.ceil(items.length / cols);
  $: totalH = rows * cellH + gap;

  $: firstRow = Math.max(0, Math.floor((scrollY - cellH) / cellH));
  $: lastRow = Math.min(rows, Math.ceil((scrollY + viewportH + cellH) / cellH));

  $: visible = (() => {
    const out: { item: T; x: number; y: number; key: number }[] = [];
    for (let r = firstRow; r < lastRow; r++) {
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c;
        if (i >= items.length) break;
        out.push({
          item: items[i],
          x: c * cellW + gap,
          y: r * cellH + gap,
          key: i,
        });
      }
    }
    return out;
  })();

  function onScroll() {
    scrollY = container.scrollTop;
  }
  function measure() {
    viewportH = container.clientHeight;
    viewportW = container.clientWidth;
  }

  onMount(() => {
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(container);
    return () => ro.disconnect();
  });
</script>

<div class="vgrid-viewport" bind:this={container} on:scroll={onScroll}>
  <div class="vgrid-canvas" style="height:{totalH}px">
    {#each visible as v (v.key)}
      <div
        class="vgrid-cell"
        style="transform: translate({v.x}px, {v.y}px);
               width:{itemWidth}px; height:{itemHeight}px;"
      >
        <slot item={v.item} />
      </div>
    {/each}
  </div>
</div>

<style>
  .vgrid-viewport {
    width: 100%;
    height: calc(100vh - 110px);
    overflow-y: auto;
    overflow-x: hidden;
  }
  .vgrid-canvas { position: relative; width: 100%; }
  .vgrid-cell { position: absolute; top: 0; left: 0; will-change: transform; }
</style>
