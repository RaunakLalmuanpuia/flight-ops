<script setup>
import { computed } from 'vue';
import { Link, usePage } from '@inertiajs/vue3';
import { STEPS, stepFromQuery, stepHref } from '../lib/tour.js';

const page = usePage();
const n = computed(() => stepFromQuery(page.url.split('?')[1] ?? ''));
const step = computed(() => (n.value ? STEPS[n.value - 1] : null));
const here = computed(() => page.url.split('?')[0]);
const btn = 'rounded border border-sky-300 bg-white px-2 py-0.5 text-sky-900';
</script>

<template>
    <aside v-if="step" aria-label="Guided tour" class="sticky top-0 z-30 border-b border-sky-300 bg-sky-100 px-4 py-3 text-sm text-sky-950">
        <div class="mx-auto flex max-w-7xl flex-wrap items-start gap-x-6 gap-y-2">
            <div class="min-w-0 flex-1 space-y-1">
                <p class="font-semibold">Tour · step {{ n }} of {{ STEPS.length }}: {{ step.title }}</p>
                <p>{{ step.look }}</p>
                <p><span class="font-semibold">Try:</span> {{ step.click }}</p>
            </div>
            <nav class="flex items-center gap-2" aria-label="Tour steps">
                <Link v-if="stepHref(n - 1)" :href="stepHref(n - 1)" :class="btn">← Back</Link>
                <Link v-if="stepHref(n + 1)" :href="stepHref(n + 1)" :class="btn" class="font-semibold">Next →</Link>
                <Link v-else href="/guide" :class="btn" class="font-semibold">Finish</Link>
                <Link :href="here" class="text-sky-800 underline">Exit tour</Link>
            </nav>
        </div>
    </aside>
</template>
