<script setup>
import { computed, ref } from 'vue';
import Term from '../components/Term.vue';
import { Head, Link, router, usePage } from '@inertiajs/vue3';
import PageHelp from '../components/PageHelp.vue';
import TourBar from '../components/TourBar.vue';
import { localDate, localTime, utcTitle } from '../lib/time.js';
import { stepFromQuery } from '../lib/tour.js';
import { CANCEL_RISK_CAVEAT, cancelRisk } from '../lib/risk.js';
import DecisionPanel from '../components/DecisionPanel.vue';

const props = defineProps({ flight: Object, legs: Array, delay: Number, whatIf: Boolean, stop: String, decisions: Array, cancelThreshold: Number });
const page = usePage();

const STOPS = {
    absorbed: 'Delay absorbed: every later flight is predicted on time.',
    break: "Gap in the aircraft's route: the next flight doesn't start where this one landed, so the chain stops here.",
    limit: 'The next flight is scheduled more than 24 hours after this arrival, so the chain stops here.',
    end: "The data for this aircraft ends while the delay was still being carried.",
};
const OUTSIDE = {
    cancelled: 'Cancelled that day, so no delay predicted',
    scheduled: 'Later in the schedule, outside the delay chain',
};

const input = ref(Math.max(0, props.delay ?? 0));
// Keep the tour step through a what-if so the tour bar stays
const tour = computed(() => stepFromQuery(page.url.split('?')[1] ?? ''));
const submit = () => router.get(`/flights/${props.flight.flight_id}`, { delay: input.value, ...(tour.value && { tour: tour.value }) });
const dim = computed(() => (props.whatIf ? 'opacity-40' : ''));
const minutes = (n) => (n === null || n === undefined ? '—' : `${n} min`);
const arrival = (n) => (n > 0 ? `${n} min late` : n < 0 ? `${-n} min early` : 'on time');
const risk = (l) => cancelRisk(l, props.cancelThreshold);
</script>

<template>
    <Head :title="`${flight.carrier} ${flight.flight_number} impact`" />
    <TourBar />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="space-y-1">
            <Link :href="`/tail/${flight.tail_number}/${flight.leg_day}`" class="text-sm text-sky-700 underline">← {{ flight.tail_number }} on {{ flight.leg_day }}</Link> · <Link href="/guide" class="text-sm text-sky-700 underline">Guide</Link>
            <h1 class="text-xl font-semibold">
                {{ flight.carrier }} {{ flight.flight_number }} · {{ flight.origin }} → {{ flight.dest }} · {{ localDate(flight.sched_dep_utc, flight.origin_tz) }} · {{ flight.tail_number }}
            </h1>
            <p v-if="flight.diverted" class="text-sm text-violet-800">
                Diverted, landed {{ flight.landed ?? '?' }}. US flight records give no arrival delay for a diverted flight, so the chain starts from the actual landing time and there is no delay to change.
            </p>
            <p v-else class="text-sm">Arrived {{ arrival(flight.actual_arr_delay) }}.<template v-if="whatIf"> Showing what a {{ delay }}-min arrival delay would do instead.</template></p>
        </header>

        <PageHelp>
            <p><strong>What this shows:</strong> what this flight's late arrival does to the same aircraft's later flights.</p>
            <p><strong>How to read it:</strong> each row is a later flight. <em>Minimum turnaround</em> is the fastest the airline can get the plane ready again. <em>Spare time</em> is how much delay the schedule can soak up. When the spare time runs out, the next flight is predicted late, and 15+ minutes is marked <em>at risk</em>. The <em>Actual</em> columns show what really happened, so you can judge the prediction.</p>
            <p><strong>Chance of cancellation</strong> is how often flights like that one were cancelled in July 2024. A red badge means it is high.</p>
            <p><strong>What to do next:</strong> try a different delay in the box, or log what you would do in "Log a decision" at the bottom.</p>
        </PageHelp>

        <form v-if="!flight.diverted" class="flex flex-wrap items-end gap-2 text-sm" @submit.prevent="submit">
            <label><Term k="what_if" label="Try a different arrival delay" /> (minutes)
                <input v-model.number="input" type="number" min="0" max="1440" step="1" required class="ml-1 w-24 rounded border border-slate-300 bg-white px-1 py-0.5" />
            </label>
            <button type="submit" class="rounded border border-slate-300 bg-white px-2 py-0.5">Try it</button>
            <Link v-if="whatIf" :href="`/flights/${flight.flight_id}${tour ? `?tour=${tour}` : ''}`" class="text-sky-700 underline">Back to the actual delay</Link>
            <p v-if="page.props.errors?.delay" class="w-full text-red-700" role="alert">{{ page.props.errors.delay }}</p>
        </form>

        <p class="text-xs text-slate-500">
            Counts aircraft delay only: no crew or passenger connections. Each later flight is predicted from the previous predicted arrival, the airline's minimum turnaround measured in July, and the schedule, with no time made up in the air. At risk means predicted to leave 15 minutes or more late.
        </p>
        <p class="text-xs text-slate-500">{{ CANCEL_RISK_CAVEAT }}</p>

        <p v-if="!legs.length" class="text-slate-500">No later flights for this aircraft in the loaded data.</p>
        <div v-else class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full whitespace-nowrap text-left text-sm">
                <thead class="whitespace-normal bg-slate-100 align-bottom text-xs uppercase text-slate-600">
                    <tr>
                        <th class="px-2 py-1">Order</th><th class="px-2 py-1">Flight</th><th class="px-2 py-1">Route</th>
                        <th class="px-2 py-1">Scheduled departure (local)</th><th class="px-2 py-1"><Term k="min_turn" label="Min. turnaround" /></th><th class="px-2 py-1"><Term k="slack" label="Spare time" /></th>
                        <th class="px-2 py-1"><Term k="propagation" label="Predicted departure delay" /></th><th class="px-2 py-1"><Term k="cancel_risk" label="Chance of cancellation" /></th>
                        <th class="px-2 py-1" :class="dim">Actual departure delay</th><th class="px-2 py-1" :class="dim">Actual arrival delay</th>
                        <th class="px-2 py-1" :class="dim"><Term k="late_aircraft" label="Actual late-inbound delay" /></th>
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
                            <span v-if="risk(l).flagged" class="badge bg-red-100 text-red-800">{{ risk(l).text }} · high</span>
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
