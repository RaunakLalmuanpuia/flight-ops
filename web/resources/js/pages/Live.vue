<script setup>
import { computed } from 'vue';
import Term from '../components/Term.vue';
import { Head, Link } from '@inertiajs/vue3';
import PageHelp from '../components/PageHelp.vue';
import TourBar from '../components/TourBar.vue';
import { ATL_TZ, localTime } from '../lib/time.js';
import { freshness, motion, LIVE_REASONS } from '../lib/live.js';

const props = defineProps({ status: Object, aircraft: Array, weather: Array, taf: Object });
const fresh = computed(() => freshness(props.status.states_loaded_at, props.status.checked_at));
const latest = computed(() => props.weather[0] ?? null);
const reason = (r) => LIVE_REASONS[r] ?? r;
const CAVEATS = [
    'No schedule: US flight records (BTS) are published months late, so there are no flight numbers, delays or predictions here.',
    'The airline comes from the start of the radio name (callsign). Regional flights sold as Delta fly as Endeavor (EDV) or SkyWest (SKW).',
    'Positions come from aircraft broadcasts (ADS-B) collected by OpenSky, and can lag by a few seconds to minutes. Each row shows how old its position is.',
];
</script>

<template>
    <Head title="ATL live" />
    <TourBar />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="flex flex-wrap items-center gap-4">
            <h1 class="mr-auto text-xl font-semibold">ATL · live <span class="text-sm font-normal text-slate-500">(Atlanta local time)</span></h1>
            <Link href="/guide" class="text-sm text-sky-700 underline">Guide</Link>
            <Link href="/day/2024-07-19" class="text-sm text-sky-700 underline">July–August 2024 history →</Link>
        </header>

        <PageHelp>
            <p><strong>What this shows:</strong> aircraft near Atlanta right now, from their own position broadcasts, plus the latest airport weather report.</p>
            <p><strong>How to read it:</strong> each row is one aircraft within about 90 nautical miles. A registration links to that plane's last day in the July 2024 data. Grey text explains why an aircraft or operator could not be identified.</p>
            <p><strong>Limits:</strong> there is no schedule here, because US flight records are published months late. So this page has no delays or predictions.</p>
        </PageHelp>

        <p v-if="fresh.state === 'never'" role="status" class="rounded border border-slate-300 bg-slate-50 p-3 text-sm">
            No live data yet. Start the loop from <code>pipelines/</code>:
            <code class="ml-1 rounded bg-white px-1">uv run --env-file ../.env python -m flightops live</code>
        </p>
        <p v-else-if="fresh.state === 'stale'" role="status" class="rounded border border-amber-400 bg-amber-50 p-3 text-sm">
            Live updates have stopped: data is {{ fresh.minutes }} min old (last update {{ localTime(status.states_loaded_at, ATL_TZ) }}).
        </p>
        <p v-else role="status" class="text-sm text-slate-600">
            Last update {{ localTime(status.states_loaded_at, ATL_TZ) }} · {{ aircraft.length }} aircraft within about 90 nautical miles
        </p>

        <section aria-label="Weather" class="space-y-1 rounded border border-slate-200 bg-white p-3 text-sm">
            <h2 class="font-semibold text-slate-700">Weather at Atlanta: <Term k="metar" /> and <Term k="taf" /></h2>
            <p v-if="!latest" class="text-slate-500">No weather report loaded yet.</p>
            <template v-else>
                <p>
                    <span class="mr-2 rounded px-1.5 py-0.5 text-xs" :class="latest.adverse ? 'bg-sky-700 text-white' : 'bg-sky-100'">{{ latest.adverse ? 'Bad weather' : 'No bad weather' }}</span>
                    <span v-if="latest.stale" class="mr-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs">Over 90 min old</span>
                    {{ localTime(latest.observed_at, ATL_TZ) }} {{ latest.metar_type }}
                </p>
                <p class="font-mono text-xs">{{ latest.raw_text }}</p>
            </template>
            <p v-if="taf" class="whitespace-pre-line font-mono text-xs text-slate-600">{{ taf.raw_text }}</p>
        </section>

        <section aria-labelledby="live-caveats" class="text-xs text-slate-600">
            <h2 id="live-caveats" class="text-sm font-semibold text-slate-700">What this page can't show</h2>
            <ul class="mt-1 list-disc pl-5">
                <li v-for="c in CAVEATS" :key="c">{{ c }}</li>
            </ul>
        </section>

        <section aria-label="Aircraft" class="overflow-x-auto">
            <p v-if="!aircraft.length" class="text-sm text-slate-500">No aircraft in the last snapshot.</p>
            <table v-else class="w-full text-left text-sm">
                <thead class="text-xs text-slate-500">
                    <tr>
                        <th class="py-1 pr-3"><Term k="tail" label="Aircraft" /></th><th class="pr-3">Type</th><th class="pr-3">Airline</th><th class="pr-3"><Term k="callsign" label="Radio name" /></th>
                        <th class="pr-3 text-right">Distance</th><th class="pr-3 text-right">Direction</th><th class="pr-3 text-right">Altitude</th>
                        <th class="pr-3">Climbing or descending</th><th class="text-right">Position age</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="a in aircraft" :key="a.hex" class="border-t border-slate-100">
                        <td class="py-1 pr-3">
                            <Link v-if="a.july_day" :href="`/tail/${a.tail_number}/${a.july_day}`" class="text-sky-700 underline" :title="`Last July 2024 day: ${a.july_day}`">{{ a.tail_number }}</Link>
                            <span v-else-if="a.tail_number">{{ a.tail_number }}</span>
                            <span v-else class="text-slate-500" :title="a.hex">{{ reason(a.unresolved_reason) }}</span>
                        </td>
                        <td class="pr-3">{{ a.manufacturer }} {{ a.model }}</td>
                        <td class="pr-3">
                            <span v-if="a.operator">{{ a.operator }}</span>
                            <span v-else class="text-slate-500">{{ reason(a.operator_reason) }}</span>
                        </td>
                        <td class="pr-3 font-mono">{{ a.callsign }}</td>
                        <td class="pr-3 text-right">{{ a.distance_nm === null ? '—' : `${a.distance_nm} nm` }}</td>
                        <td class="pr-3 text-right">{{ a.bearing_deg === null ? '—' : `${a.bearing_deg}°` }}</td>
                        <td class="pr-3 text-right">{{ a.on_ground || a.altitude_ft === null ? '—' : `${a.altitude_ft.toLocaleString('en-US')} ft` }}</td>
                        <td class="pr-3">{{ motion(a) }}</td>
                        <td class="text-right">{{ a.position_age_s === null ? '—' : `${a.position_age_s} s` }}</td>
                    </tr>
                </tbody>
            </table>
        </section>
    </main>
</template>
