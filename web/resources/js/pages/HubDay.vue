<script setup>
import { ref } from 'vue';
import { Head, Link } from '@inertiajs/vue3';
import PageHelp from '../components/PageHelp.vue';
import TourBar from '../components/TourBar.vue';
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
    <TourBar />
    <main class="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <header class="flex flex-wrap items-center gap-4">
            <h1 class="mr-auto text-xl font-semibold">ATL · {{ day }} <span class="text-sm font-normal text-slate-500">(Atlanta local time)</span></h1>
            <Link href="/guide" class="text-sm text-sky-700 underline">Guide</Link>
            <Link href="/live" class="text-sm text-sky-700 underline">ATL live →</Link>
            <Link href="/decisions" class="text-sm text-sky-700 underline">Decisions →</Link>
            <DayNav :day="day" :range="range" base="/day" />
        </header>

        <PageHelp>
            <p><strong>What this shows:</strong> every flight that left or landed at Atlanta on this day, in Atlanta time.</p>
            <p><strong>How to read it:</strong> each column of the chart is one hour. Bars above the line are departures, bars below are arrivals. Grey is on time, amber is 15+ minutes late, red is cancelled. The strip under the chart is the weather: dark blue hours had bad weather.</p>
            <p><strong>Data warnings</strong> list flights with something unusual in the data. Click one to show only those flights.</p>
            <p><strong>What to do next:</strong> click an hour to filter the table, then click an aircraft registration (like N102DN) to follow that plane's day.</p>
        </PageHelp>

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
