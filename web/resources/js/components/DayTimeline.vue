<script setup>
import { computed } from 'vue';
import { hourBuckets, maxScheduled, stack, total, weatherByHour } from '../lib/timeline.js';

const props = defineProps({ hourly: Array, weather: Array, selectedHour: { type: Number, default: null } });
const emit = defineEmits(['select-hour']);

const COL = 40;
const HALF = 110;
const STRIP = 22;
const WIDTH = COL * 24;
const HEIGHT = HALF * 2 + STRIP + 24;
const FILL = { on_time: 'fill-slate-400', delayed: 'fill-amber-500', diverted: 'fill-violet-500', cancelled: 'fill-red-600' };

const hours = computed(() => hourBuckets(props.hourly));
const scale = computed(() => (HALF - 8) / maxScheduled(hours.value));
const metars = computed(() => weatherByHour(props.weather));
const pad = (h) => String(h).padStart(2, '0');
</script>

<template>
    <div class="overflow-x-auto">
    <svg :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" class="w-full min-w-[640px]" role="img" aria-label="ATL departures and arrivals by local hour, with weather reports below. The table that follows gives the same counts.">
        <g v-for="h in hours" :key="h.hour" :transform="`translate(${h.hour * COL},0)`" class="cursor-pointer" @click="emit('select-hour', selectedHour === h.hour ? null : h.hour)">
            <title>{{ pad(h.hour) }}:00 local · {{ total(h.dep) }} departures · {{ total(h.arr) }} arrivals</title>
            <rect :width="COL" :height="HALF * 2" :class="selectedHour === h.hour ? 'fill-slate-100 stroke-slate-400' : 'fill-transparent'" />
            <rect v-for="s in stack(h.dep, scale)" :key="`d${s.status}`" x="4" :width="COL - 8" :y="HALF - s.offset - s.length" :height="s.length" :class="FILL[s.status]" />
            <rect v-for="s in stack(h.arr, scale)" :key="`a${s.status}`" x="4" :width="COL - 8" :y="HALF + s.offset" :height="s.length" :class="FILL[s.status]" />
        </g>
        <line x1="0" :x2="WIDTH" :y1="HALF" :y2="HALF" class="stroke-slate-700" />
        <text x="4" y="12" class="fill-slate-500 text-[10px]">Departures ↑</text>
        <text x="4" :y="HALF * 2 - 4" class="fill-slate-500 text-[10px]">Arrivals ↓</text>
        <g v-for="m in metars" :key="`w${m.hour}`" :transform="`translate(${m.hour * COL},${HALF * 2 + 4})`">
            <title>{{ m.reports.length ? m.reports.join('\n') : 'No weather report this hour' }}</title>
            <rect :width="COL - 1" :height="STRIP" :class="m.adverse ? 'fill-sky-700' : m.reports.length ? 'fill-sky-100' : 'fill-slate-200'" />
        </g>
        <text v-for="h in hours" :key="`l${h.hour}`" :x="h.hour * COL + COL / 2" :y="HEIGHT - 4" text-anchor="middle" class="fill-slate-500 text-[10px]">{{ pad(h.hour) }}</text>
    </svg>
    </div>
    <table class="sr-only">
        <caption>Flights by Atlanta hour</caption>
        <thead>
            <tr><th scope="col">Hour</th><th scope="col">Departures</th><th scope="col">Arrivals</th><th scope="col">Cancelled</th><th scope="col">Bad weather</th></tr>
        </thead>
        <tbody>
            <tr v-for="h in hours" :key="`s${h.hour}`">
                <th scope="row">{{ pad(h.hour) }}:00</th>
                <td>{{ total(h.dep) }}</td>
                <td>{{ total(h.arr) }}</td>
                <td>{{ h.dep.cancelled + h.arr.cancelled }}</td>
                <td>{{ metars[h.hour].adverse ? 'yes' : 'no' }}</td>
            </tr>
        </tbody>
    </table>
</template>
