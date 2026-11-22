<script setup>
import { computed } from 'vue';
import { Link } from '@inertiajs/vue3';
import { atlEvent, byAtlTime, CANCELLATION, CAVEATS, caveatsOf, delayText, filterFlights } from '../lib/flights.js';
import { ATL_TZ, localTime, utcTitle } from '../lib/time.js';

const props = defineProps({ flights: Array, day: String, filters: Object });
const emit = defineEmits(['update:filters']);

const STATUS = { on_time: 'On time', delayed: 'Delayed 15+', diverted: 'Diverted', cancelled: 'Cancelled' };
const BADGE = { on_time: 'bg-slate-100 text-slate-700', delayed: 'bg-amber-100 text-amber-900', diverted: 'bg-violet-100 text-violet-900', cancelled: 'bg-red-100 text-red-800' };

const carriers = computed(() => [...new Set(props.flights.map((f) => f.carrier))].sort());
const ordered = computed(() => byAtlTime(props.flights));
const shown = computed(() => filterFlights(ordered.value, props.filters));
const set = (key, value) => emit('update:filters', { ...props.filters, [key]: value });
const clear = () => emit('update:filters', { direction: '', carrier: '', status: '', hour: null, caveat: '' });
const pad = (h) => String(h).padStart(2, '0');
</script>

<template>
    <section aria-labelledby="flights-heading">
        <div class="flex flex-wrap items-end gap-3">
            <h2 id="flights-heading" class="mr-auto text-sm font-semibold text-slate-700">Flights · showing {{ shown.length }} of {{ flights.length }}</h2>
            <label class="text-sm">Direction
                <select class="ml-1 rounded border border-slate-300 bg-white px-1 py-0.5" :value="filters.direction" @change="set('direction', $event.target.value)">
                    <option value="">All</option><option value="dep">Departures</option><option value="arr">Arrivals</option>
                </select>
            </label>
            <label class="text-sm">Carrier
                <select class="ml-1 rounded border border-slate-300 bg-white px-1 py-0.5" :value="filters.carrier" @change="set('carrier', $event.target.value)">
                    <option value="">All</option><option v-for="c in carriers" :key="c" :value="c">{{ c }}</option>
                </select>
            </label>
            <label class="text-sm">Status
                <select class="ml-1 rounded border border-slate-300 bg-white px-1 py-0.5" :value="filters.status" @change="set('status', $event.target.value)">
                    <option value="">All</option><option v-for="(label, key) in STATUS" :key="key" :value="key">{{ label }}</option>
                </select>
            </label>
            <label class="text-sm">Hour
                <select class="ml-1 rounded border border-slate-300 bg-white px-1 py-0.5" :value="filters.hour ?? ''" @change="set('hour', $event.target.value === '' ? null : Number($event.target.value))">
                    <option value="">All</option><option v-for="h in 24" :key="h" :value="h - 1">{{ pad(h - 1) }}:00</option>
                </select>
            </label>
            <label class="text-sm">Caveat
                <select class="ml-1 rounded border border-slate-300 bg-white px-1 py-0.5" :value="filters.caveat" @change="set('caveat', $event.target.value)">
                    <option value="">Any</option><option v-for="(label, key) in CAVEATS" :key="key" :value="key">{{ label }}</option>
                </select>
            </label>
            <button type="button" class="rounded border border-slate-300 bg-white px-2 py-0.5 text-sm" @click="clear">Clear filters</button>
        </div>

        <div class="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full text-left text-sm">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600">
                    <tr>
                        <th class="px-2 py-1">ATL time</th><th class="px-2 py-1">Flight</th><th class="px-2 py-1">From / to</th>
                        <th class="px-2 py-1">Tail</th><th class="px-2 py-1">Status</th><th class="px-2 py-1">Delay</th>
                        <th class="px-2 py-1">METAR age</th><th class="px-2 py-1">Caveats</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="f in shown" :key="f.flight_id" class="border-t border-slate-100 align-top">
                        <td class="px-2 py-1 whitespace-nowrap">
                            <span :title="utcTitle(atlEvent(f).sched)">{{ localTime(atlEvent(f).sched, ATL_TZ) }}</span>
                            <span v-if="atlEvent(f).actual" class="text-slate-500" :title="utcTitle(atlEvent(f).actual)"> → {{ localTime(atlEvent(f).actual, ATL_TZ) }}</span>
                        </td>
                        <td class="px-2 py-1 whitespace-nowrap">{{ f.carrier }} {{ f.flight_number }}</td>
                        <td class="px-2 py-1 whitespace-nowrap">
                            {{ f.direction === 'dep' ? `to ${f.other_station}` : `from ${f.other_station}` }}
                            <span v-if="f.status === 'diverted'" class="text-violet-700"> (landed {{ f.landed_station ?? '?' }})</span>
                        </td>
                        <td class="px-2 py-1">
                            <Link v-if="f.tail_number" :href="`/tail/${f.tail_number}/${day}`" class="text-sky-700 underline">{{ f.tail_number }}</Link>
                            <span v-else class="text-slate-400">—</span>
                        </td>
                        <td class="px-2 py-1"><span class="badge" :class="BADGE[f.status]" :title="f.cancellation_code ? `BTS cancellation code ${f.cancellation_code}` : null">{{ STATUS[f.status] }}<template v-if="f.cancellation_code"> · {{ CANCELLATION[f.cancellation_code] ?? f.cancellation_code }}</template></span></td>
                        <td class="px-2 py-1">
                            <span v-if="atlEvent(f).delay !== null">{{ atlEvent(f).delay }} min</span>
                            <div v-if="delayText(f.delays)" class="text-xs text-slate-500">{{ delayText(f.delays) }}</div>
                        </td>
                        <td class="px-2 py-1">
                            <span v-if="f.metar_staleness_min !== null">{{ f.metar_staleness_min }} min</span><span v-else class="text-slate-400">none</span>
                            <span v-if="f.metar_adverse" class="badge ml-1 bg-sky-100 text-sky-900">adverse</span>
                        </td>
                        <td class="px-2 py-1">
                            <span v-for="c in caveatsOf(f)" :key="c" class="badge mr-1 bg-amber-50 text-amber-900">{{ CAVEATS[c] }}</span>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </section>
</template>
