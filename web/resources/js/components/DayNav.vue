<script setup>
import { Link, router } from '@inertiajs/vue3';
import { shiftDay } from '../lib/time.js';

const props = defineProps({ day: String, range: Object, base: String });

function go(event) {
    const v = event.target.value;
    if (v && v !== props.day && v >= props.range.first_day && v <= props.range.last_day) router.visit(`${props.base}/${v}`);
    else event.target.value = props.day;
}
</script>

<template>
    <nav class="flex items-center gap-2" aria-label="Choose a day">
        <Link v-if="day > range.first_day" :href="`${base}/${shiftDay(day, -1)}`" class="rounded border border-slate-300 bg-white px-2 py-1 text-sm">← Previous day</Link>
        <label class="text-sm">
            <span class="sr-only">Day</span>
            <input type="date" :value="day" :min="range.first_day" :max="range.last_day" class="rounded border border-slate-300 bg-white px-2 py-1" @keydown.enter="go" @blur="go" />
        </label>
        <Link v-if="day < range.last_day" :href="`${base}/${shiftDay(day, 1)}`" class="rounded border border-slate-300 bg-white px-2 py-1 text-sm">Next day →</Link>
    </nav>
</template>
