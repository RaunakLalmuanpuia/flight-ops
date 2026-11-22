<script setup>
import { ref } from 'vue';
import { Head, Link } from '@inertiajs/vue3';
import CaveatPanel from '../components/CaveatPanel.vue';
import DayNav from '../components/DayNav.vue';
import DayTimeline from '../components/DayTimeline.vue';
import FlightTable from '../components/FlightTable.vue';

defineProps({ day: String, range: Object, hourly: Array, weather: Array, caveats: Object, flights: Array });

const filters = ref({ direction: '', carrier: '', status: '', hour: null, caveat: '' });
const LEGEND = [
    ['bg-slate-400', 'On time'], ['bg-amber-500', 'Delayed 15+'], ['bg-violet-500', 'Diverted'], ['bg-red-600', 'Cancelled'],
    ['bg-sky-100', 'METAR'], ['bg-sky-700', 'Adverse METAR'], ['bg-slate-200', 'No METAR'],
];
</script>

<template>
    <Head :title="`ATL ${day}`" />
    <main class="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <header class="flex flex-wrap items-center gap-4">
            <h1 class="mr-auto text-xl font-semibold">ATL · {{ day }} <span class="text-sm font-normal text-slate-500">(Atlanta local time)</span></h1>
            <Link href="/live" class="text-sm text-sky-700 underline">ATL live →</Link>
            <DayNav :day="day" :range="range" base="/day" />
        </header>

        <section aria-label="Timeline" class="rounded border border-slate-200 bg-white p-3">
            <DayTimeline :hourly="hourly" :weather="weather" :selected-hour="filters.hour" @select-hour="(h) => (filters = { ...filters, hour: h })" />
            <ul class="mt-2 flex flex-wrap gap-3 text-xs text-slate-600">
                <li v-for="[color, label] in LEGEND" :key="label" class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded-sm ring-1 ring-slate-300" :class="color" />{{ label }}</li>
            </ul>
        </section>

        <CaveatPanel :caveats="caveats" :active="filters.caveat" @toggle="(c) => (filters = { ...filters, caveat: c })" />

        <FlightTable v-model:filters="filters" :flights="flights" :day="day" />
    </main>
</template>
