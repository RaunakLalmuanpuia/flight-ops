<script setup>
import { computed, ref } from 'vue';
import { Head, Link, router, usePage } from '@inertiajs/vue3';
import { localDate, localTime, utcTitle } from '../lib/time.js';
import { CANCEL_RISK_CAVEAT, cancelRisk } from '../lib/risk.js';
import DecisionPanel from '../components/DecisionPanel.vue';

const props = defineProps({ flight: Object, legs: Array, delay: Number, whatIf: Boolean, stop: String, decisions: Array, cancelThreshold: Number });
const page = usePage();

const STOPS = {
    absorbed: 'Delay absorbed: every later leg is predicted on time.',
    break: "Rotation break: the next leg doesn't start where this one landed, so the chain stops unpredicted.",
    limit: 'The next leg is scheduled more than 24 hours after this arrival, so the chain stops unpredicted.',
    end: "End of this tail's data while the delay was still being carried.",
};
const OUTSIDE = {
    cancelled: 'Cancelled in the gap, delay not predicted',
    scheduled: 'Later on the schedule, outside the propagated chain',
};

const input = ref(Math.max(0, props.delay ?? 0));
const submit = () => router.get(`/flights/${props.flight.flight_id}`, { delay: input.value });
const dim = computed(() => (props.whatIf ? 'opacity-40' : ''));
const minutes = (n) => (n === null || n === undefined ? '—' : `${n} min`);
const arrival = (n) => (n > 0 ? `${n} min late` : n < 0 ? `${-n} min early` : 'on time');
const risk = (l) => cancelRisk(l, props.cancelThreshold);
</script>

<template>
    <Head :title="`${flight.carrier} ${flight.flight_number} impact`" />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="space-y-1">
            <Link :href="`/tail/${flight.tail_number}/${flight.leg_day}`" class="text-sm text-sky-700 underline">← {{ flight.tail_number }} on {{ flight.leg_day }}</Link>
            <h1 class="text-xl font-semibold">
                {{ flight.carrier }} {{ flight.flight_number }} · {{ flight.origin }} → {{ flight.dest }} · {{ localDate(flight.sched_dep_utc, flight.origin_tz) }} · {{ flight.tail_number }}
            </h1>
            <p v-if="flight.diverted" class="text-sm text-violet-800">
                Diverted, landed {{ flight.landed ?? '?' }}. BTS gives no arrival delay for a diversion, so the chain starts from the actual landing time and there is no delay to change.
            </p>
            <p v-else class="text-sm">Arrived {{ arrival(flight.actual_arr_delay) }}.<template v-if="whatIf"> Showing what a {{ delay }}-min arrival delay would do instead.</template></p>
        </header>

        <form v-if="!flight.diverted" class="flex flex-wrap items-end gap-2 text-sm" @submit.prevent="submit">
            <label>Arrival delay to propagate (min)
                <input v-model.number="input" type="number" min="0" max="1440" step="1" required class="ml-1 w-24 rounded border border-slate-300 bg-white px-1 py-0.5" />
            </label>
            <button type="submit" class="rounded border border-slate-300 bg-white px-2 py-0.5">Propagate</button>
            <Link v-if="whatIf" :href="`/flights/${flight.flight_id}`" class="text-sky-700 underline">Back to the actual delay</Link>
            <p v-if="page.props.errors?.delay" class="w-full text-red-700" role="alert">{{ page.props.errors.delay }}</p>
        </form>

        <p class="text-xs text-slate-500">
            Aircraft-driven delay only: no crew or passenger connections. Each leg is predicted from the previous predicted arrival, the carrier's minimum turn measured from July, and the schedule, with no time made up in the air. At risk means a predicted departure delay of 15 min or more.
        </p>
        <p class="text-xs text-slate-500">{{ CANCEL_RISK_CAVEAT }}</p>

        <p v-if="!legs.length" class="text-slate-500">No later flights on this tail in the loaded data.</p>
        <div v-else class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full whitespace-nowrap text-left text-sm">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600">
                    <tr>
                        <th class="px-2 py-1">Leg</th><th class="px-2 py-1">Flight</th><th class="px-2 py-1">Route</th>
                        <th class="px-2 py-1">Sched dep (local)</th><th class="px-2 py-1">Min turn</th><th class="px-2 py-1">Slack</th>
                        <th class="px-2 py-1">Predicted dep delay</th><th class="px-2 py-1">Cancel risk</th>
                        <th class="px-2 py-1" :class="dim">Actual dep delay</th><th class="px-2 py-1" :class="dim">Actual arr delay</th>
                        <th class="px-2 py-1" :class="dim">Actual late-aircraft</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="l in legs" :key="`${l.kind}-${l.flight_id}`" class="border-t border-slate-100 align-top" :class="l.cancelled && 'bg-slate-50 text-slate-500'">
                        <td class="px-2 py-1">{{ l.depth ?? '—' }}</td>
                        <td class="px-2 py-1 whitespace-nowrap">{{ l.carrier }} {{ l.flight_number }}</td>
                        <td class="px-2 py-1 whitespace-nowrap">{{ l.origin }} → {{ l.dest }}</td>
                        <td class="px-2 py-1 whitespace-nowrap" :title="utcTitle(l.sched_dep_utc)">{{ localDate(l.sched_dep_utc, l.origin_tz) }} {{ localTime(l.sched_dep_utc, l.origin_tz) }}</td>
                        <template v-if="l.kind === 'flown'">
                            <td class="px-2 py-1">{{ minutes(l.min_turn) }}</td>
                            <td class="px-2 py-1">{{ minutes(l.slack_min) }}</td>
                            <td class="px-2 py-1">
                                <span v-if="l.at_risk" class="badge bg-amber-100 text-amber-900">{{ l.predicted_dep_delay }} min · at risk</span>
                                <template v-else-if="l.predicted_dep_delay !== null">{{ l.predicted_dep_delay }} min</template>
                                <span v-else class="text-slate-500">not predicted ({{ l.stop_reason }})</span>
                            </td>
                        </template>
                        <td v-else colspan="3" class="px-2 py-1 italic">{{ OUTSIDE[l.kind] }}</td>
                        <td class="px-2 py-1">
                            <span v-if="risk(l).flagged" class="badge bg-red-100 text-red-800">{{ risk(l).text }} · cancel risk</span>
                            <span v-else :class="!risk(l).basis && 'text-slate-500'">{{ risk(l).text }}</span>
                            <div v-if="risk(l).basis" class="text-xs text-slate-500">{{ risk(l).basis }}</div>
                        </td>
                        <td v-if="l.cancelled" colspan="3" class="px-2 py-1" :class="dim">cancelled</td>
                        <template v-else>
                            <td class="px-2 py-1" :class="dim">{{ minutes(l.actual_dep_delay) }}</td>
                            <td class="px-2 py-1" :class="dim">{{ minutes(l.actual_arr_delay) }}</td>
                            <td class="px-2 py-1" :class="dim">{{ l.actual_late_aircraft === null ? 'not reported' : `${l.actual_late_aircraft} min` }}</td>
                        </template>
                    </tr>
                </tbody>
            </table>
        </div>

        <p v-if="stop" class="text-sm text-slate-700">{{ STOPS[stop] ?? stop }}</p>
        <p v-if="whatIf" class="text-xs text-slate-500">Actual columns are dimmed and not comparable: they record what followed the real {{ flight.actual_arr_delay }}-min delay, not this one.</p>
        <DecisionPanel :flight-id="flight.flight_id" :legs="legs" :what-if-delay="whatIf ? delay : null" :decisions="decisions" />
    </main>
</template>
