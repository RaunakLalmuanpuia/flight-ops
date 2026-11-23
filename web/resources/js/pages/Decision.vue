<script setup>
import { computed } from 'vue';
import Term from '../components/Term.vue';
import { Head, Link } from '@inertiajs/vue3';
import PageHelp from '../components/PageHelp.vue';
import TourBar from '../components/TourBar.vue';
import { ATL_TZ, localDate, localTime, utcTitle } from '../lib/time.js';
import { ACTIONS, HINDSIGHT, outcome } from '../lib/decisions.js';
import { CANCEL_RISK_CAVEAT, cancelRisk } from '../lib/risk.js';

const props = defineProps({ decision: Object, legs: Array, cancelThreshold: Number });
const risk = (l) => cancelRisk(l, props.cancelThreshold);
const d = props.decision;
const flightHref = computed(() => `/flights/${d.current_flight_id}${d.what_if ? `?delay=${d.arr_delay_min}` : ''}`);
// A leg no longer found after a rebuild has no timezone, so it shows UTC
const sched = (l) => (l.origin_tz ? `${localDate(l.sched_dep_utc, l.origin_tz)} ${localTime(l.sched_dep_utc, l.origin_tz)}` : utcTitle(l.sched_dep_utc));
const minutes = (n) => (n === null || n === undefined ? '—' : `${n} min`);
const cell = 'px-2 py-1';
</script>

<template>
    <Head :title="`Decision ${d.decision_id}`" />
    <TourBar />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="space-y-1">
            <Link href="/decisions" class="text-sm text-sky-700 underline">← Decision log</Link> · <Link href="/guide" class="text-sm text-sky-700 underline">Guide</Link>
            <h1 class="text-xl font-semibold">{{ ACTIONS[d.action] }} · {{ d.carrier }} {{ d.flight_number }} {{ d.origin }} → {{ d.dest }}</h1>
            <p class="text-sm text-slate-600">
                {{ d.author }}, {{ localDate(d.recorded_at, ATL_TZ) }} {{ localTime(d.recorded_at, ATL_TZ) }} Atlanta time.
                <template v-if="d.what_if">Logged against a {{ d.arr_delay_min }}-min what-if arrival delay.</template>
                <template v-else-if="d.arr_delay_min !== null">Logged against the actual {{ d.arr_delay_min }}-min arrival delay.</template>
                <template v-else>Logged against the actual landing of a diversion.</template>
                Minimum turnaround set at the {{ d.percentile }}th percentile of July turnarounds.
            </p>
            <Link v-if="d.flight_found" :href="flightHref" class="text-sm text-sky-700 underline">Open the flight's impact page →</Link>
        </header>

        <PageHelp>
            <p><strong>What this shows:</strong> one logged decision, with the delay chain exactly as it looked when the decision was made.</p>
            <p><strong>How to read it:</strong> the chain is frozen, so later data changes don't rewrite history. Compare the predicted columns with the actual ones to see whether the decision helped.</p>
        </PageHelp>

        <blockquote class="border-l-4 border-slate-300 pl-3 text-sm">{{ d.reason }}</blockquote>

        <section class="rounded border border-slate-200 bg-white p-3 text-sm">
            <h2 class="font-semibold">Outcome</h2>
            <p v-if="d.target_flight_number">Target {{ d.target_carrier }} {{ d.target_flight_number }} {{ d.target_origin }} → {{ d.target_dest }}: {{ outcome(d) }}.</p>
            <p v-else-if="!d.flight_found">{{ outcome(d) }}.</p>
            <p>
                Chain: {{ d.predicted_at_risk }} predicted at risk · {{ d.actually_late }} left 15+ min late · {{ d.cancelled }} cancelled
                · <template v-if="d.cancel_risk_recorded">{{ d.flagged_cancel_risk }} flagged high chance of cancellation</template><template v-else>logged before the cancellation score existed</template>.
            </p>
        </section>

        <p class="text-xs text-slate-500">{{ HINDSIGHT }}</p>
        <p class="text-xs text-slate-500">{{ CANCEL_RISK_CAVEAT }} Risks here are kept as the decision saw them. The badge uses today's threshold.</p>

        <div class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full whitespace-nowrap text-left text-sm">
                <thead class="whitespace-normal bg-slate-100 align-bottom text-xs uppercase text-slate-600">
                    <tr>
                        <th :class="cell">Order</th><th :class="cell">Flight</th><th :class="cell">Route</th><th :class="cell">Scheduled departure (local)</th>
                        <th :class="cell">Predicted departure delay (as decided)</th><th :class="cell"><Term k="cancel_risk" label="Chance of cancellation" /> (as decided)</th><th :class="cell">Actual departure delay</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="l in legs" :key="`${l.kind}-${l.flight_id}`" class="border-t border-slate-100" :class="[l.is_target && 'bg-sky-50', l.actual_cancelled && 'text-slate-500']">
                        <td :class="cell">{{ l.depth ?? '—' }}</td>
                        <td :class="cell">{{ l.carrier }} {{ l.flight_number }} <span v-if="l.is_target" class="badge bg-sky-100 text-sky-900">target</span></td>
                        <td :class="cell">{{ l.origin }} → {{ l.dest }}</td>
                        <td :class="cell" :title="utcTitle(l.sched_dep_utc)">{{ sched(l) }}</td>
                        <td :class="cell">
                            <template v-if="l.kind === 'selected'">decided on</template>
                            <template v-else-if="l.kind === 'cancelled'">cancelled that day, not predicted</template>
                            <template v-else-if="l.kind === 'scheduled'">outside the delay chain, not predicted</template>
                            <span v-else-if="l.at_risk" class="badge bg-amber-100 text-amber-900">{{ l.predicted_dep_delay }} min · at risk</span>
                            <template v-else-if="l.predicted_dep_delay !== null">{{ l.predicted_dep_delay }} min</template>
                            <span v-else class="text-slate-500">not predicted ({{ l.stop_reason }})</span>
                        </td>
                        <td :class="cell">
                            <template v-if="l.kind === 'selected'">—</template>
                            <span v-else-if="!d.cancel_risk_recorded" class="text-slate-500">logged before this score existed</span>
                            <template v-else>
                                <span v-if="risk(l).flagged" class="badge bg-red-100 text-red-800">{{ risk(l).text }} · high</span>
                                <span v-else :class="!risk(l).basis && 'text-slate-500'">{{ risk(l).text }}</span>
                                <div v-if="risk(l).basis" class="text-xs text-slate-500">{{ risk(l).basis }}</div>
                            </template>
                        </td>
                        <td :class="cell">
                            <template v-if="l.current_flight_id === null">flight not found after the data was rebuilt</template>
                            <template v-else-if="l.actual_cancelled">cancelled</template>
                            <template v-else>{{ minutes(l.actual_dep_delay) }}</template>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
        <p v-if="d.what_if" class="text-xs text-slate-500">Actual delays followed the real arrival, not the what-if.</p>
    </main>
</template>
