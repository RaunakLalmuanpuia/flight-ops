<script setup>
import { computed } from 'vue';
import { usePage } from '@inertiajs/vue3';
import { stepFromQuery } from '../lib/tour.js';

const page = usePage();
const touring = computed(() => stepFromQuery(page.url.split('?')[1] ?? '') !== null);
</script>

<template>
    <details :open="touring" class="rounded border border-sky-200 bg-sky-50 p-3 text-sm">
        <summary class="cursor-pointer font-semibold text-sky-900">How to read this page</summary>
        <div class="mt-2 space-y-2 text-slate-700"><slot /></div>
    </details>
</template>
