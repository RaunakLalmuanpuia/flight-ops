<script setup>
import { onBeforeUnmount, ref, useId, watch } from 'vue';
import { GLOSSARY } from '../lib/glossary.js';

const props = defineProps({ k: String, label: String });
const entry = GLOSSARY[props.k];
if (!entry && import.meta.env.DEV) console.warn(`Term: no glossary entry "${props.k}"`);

const open = ref(false);
const id = useId();
const root = ref(null);
const pos = ref({});
// Fixed to the viewport so scrolling tables (overflow-x-auto) don't clip it; closes on scroll instead of following
const toggle = (e) => {
    if (!open.value) {
        const r = e.currentTarget.getBoundingClientRect();
        pos.value = { top: `${r.bottom + 4}px`, left: `${Math.max(8, Math.min(r.left, window.innerWidth - 272))}px` };
    }
    open.value = !open.value;
};
const close = () => (open.value = false);
const outside = (e) => {
    if (!root.value?.contains(e.target)) close();
};
const listen = (on) => {
    const m = on ? 'addEventListener' : 'removeEventListener';
    document[m]('click', outside);
    window[m]('scroll', close, true);
    window[m]('resize', close);
};
watch(open, listen);
onBeforeUnmount(() => listen(false));
</script>

<template>
    <span ref="root" class="relative inline-flex items-baseline gap-1" @keydown.esc="open = false">
        <span>{{ label ?? entry?.plain ?? k }}</span>
        <span v-if="entry?.term" class="text-[0.85em] font-normal normal-case text-slate-500">({{ entry.term }})</span>
        <button
            v-if="entry"
            type="button"
            class="rounded-full px-0.5 text-sky-700 hover:bg-sky-100 focus-visible:outline-2 focus-visible:outline-sky-600"
            :aria-expanded="open"
            :aria-controls="id"
            :aria-label="`What is ${entry.plain}?`"
            @click="toggle"
        >ⓘ</button>
        <span v-if="open" :id="id" role="note" :style="pos" class="fixed z-50 w-64 rounded border border-slate-200 bg-white p-2 text-left text-xs font-normal whitespace-normal normal-case text-slate-700 shadow-lg">
            {{ entry.short }}
            <a :href="`/guide#${k}`" class="ml-1 text-sky-700 underline">Glossary</a>
        </span>
    </span>
</template>
