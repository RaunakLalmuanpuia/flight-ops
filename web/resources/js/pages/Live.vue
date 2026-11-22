<script setup>
import { computed } from 'vue';
import { Head, Link } from '@inertiajs/vue3';
import { ATL_TZ, localTime } from '../lib/time.js';
import { freshness, motion, LIVE_REASONS } from '../lib/live.js';

const props = defineProps({ status: Object, aircraft: Array, weather: Array, taf: Object });
const fresh = computed(() => freshness(props.status.states_loaded_at, props.status.checked_at));
const latest = computed(() => props.weather[0] ?? null);
const reason = (r) => LIVE_REASONS[r] ?? r;
const CAVEATS = [
    'No schedule: BTS is published months late, so there are no flight numbers, delays or propagation here.',
    'Operators come from the callsign prefix. Regional flights sold as Delta fly as Endeavor (EDV) or SkyWest (SKW).',
    'Positions are OpenSky ADS-B and can lag by a few seconds to minutes. Each row shows how old its position is.',
];
</script>

<template>
    <Head title="ATL live" />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="flex flex-wrap items-center gap-4">
            <h1 class="mr-auto text-xl font-semibold">ATL · live <span class="text-sm font-normal text-slate-500">(Atlanta local time)</span></h1>
            <Link href="/day/2024-07-19" class="text-sm text-sky-700 underline">July 2024 history →</Link>
        </header>

        <p v-if="fresh.state === 'never'" role="status" class="rounded border border-slate-300 bg-slate-50 p-3 text-sm">
            No live data yet. Start the loop from <code>pipelines/</code>:
            <code class="ml-1 rounded bg-white px-1">uv run --env-file ../.env python -m flightops live</code>
        </p>
        <p v-else-if="fresh.state === 'stale'" role="status" class="rounded border border-amber-400 bg-amber-50 p-3 text-sm">
            Live loop not running: data is {{ fresh.minutes }} min old (last poll {{ localTime(status.states_loaded_at, ATL_TZ) }}).
        </p>
        <p v-else role="status" class="text-sm text-slate-600">
            Last poll {{ localTime(status.states_loaded_at, ATL_TZ) }} · {{ aircraft.length }} aircraft within about 90 nm
        </p>

        <section aria-label="Weather" class="space-y-1 rounded border border-slate-200 bg-white p-3 text-sm">
            <h2 class="font-semibold text-slate-700">Weather at ATL</h2>
            <p v-if="!latest" class="text-slate-500">No METAR loaded yet.</p>
            <template v-else>
                <p>
                    <span class="mr-2 rounded px-1.5 py-0.5 text-xs" :class="latest.adverse ? 'bg-sky-700 text-white' : 'bg-sky-100'">{{ latest.adverse ? 'Adverse' : 'Not adverse' }}</span>
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
                        <th class="py-1 pr-3">Tail</th><th class="pr-3">Type</th><th class="pr-3">Operator</th><th class="pr-3">Callsign</th>
                        <th class="pr-3 text-right">Distance</th><th class="pr-3 text-right">Bearing</th><th class="pr-3 text-right">Altitude</th>
                        <th class="pr-3">Motion</th><th class="text-right">Position age</th>
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
