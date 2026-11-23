<script setup>
import { computed } from 'vue';
import { Head, Link } from '@inertiajs/vue3';
import { ATL_TZ, localDate, localTime, utcTitle } from '../lib/time.js';
import { ACTIONS, HINDSIGHT, outcome } from '../lib/decisions.js';

const props = defineProps({ decision: Object, legs: Array });
const d = props.decision;
const flightHref = computed(() => `/flights/${d.current_flight_id}${d.what_if ? `?delay=${d.arr_delay_min}` : ''}`);
// A leg no longer found after a rebuild has no timezone, so it shows UTC
const sched = (l) => (l.origin_tz ? `${localDate(l.sched_dep_utc, l.origin_tz)} ${localTime(l.sched_dep_utc, l.origin_tz)}` : utcTitle(l.sched_dep_utc));
const minutes = (n) => (n === null || n === undefined ? '—' : `${n} min`);
const cell = 'px-2 py-1';
</script>

<template>
    <Head :title="`Decision ${d.decision_id}`" />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="space-y-1">
            <Link href="/decisions" class="text-sm text-sky-700 underline">← Decision log</Link>
            <h1 class="text-xl font-semibold">{{ ACTIONS[d.action] }} · {{ d.carrier }} {{ d.flight_number }} {{ d.origin }} → {{ d.dest }}</h1>
            <p class="text-sm text-slate-600">
                {{ d.author }}, {{ localDate(d.recorded_at, ATL_TZ) }} {{ localTime(d.recorded_at, ATL_TZ) }} Atlanta time.
                <template v-if="d.what_if">Logged against a {{ d.arr_delay_min }}-min what-if arrival delay.</template>
                <template v-else-if="d.arr_delay_min !== null">Logged against the actual {{ d.arr_delay_min }}-min arrival delay.</template>
                <template v-else>Logged against the actual landing of a diversion.</template>
                Min turn at p{{ d.percentile }}.
            </p>
            <Link v-if="d.flight_found" :href="flightHref" class="text-sm text-sky-700 underline">Open the flight's impact page →</Link>
        </header>

        <blockquote class="border-l-4 border-slate-300 pl-3 text-sm">{{ d.reason }}</blockquote>

        <section class="rounded border border-slate-200 bg-white p-3 text-sm">
            <h2 class="font-semibold">Outcome</h2>
            <p v-if="d.target_flight_number">Target {{ d.target_carrier }} {{ d.target_flight_number }} {{ d.target_origin }} → {{ d.target_dest }}: {{ outcome(d) }}.</p>
            <p v-else-if="!d.flight_found">{{ outcome(d) }}.</p>
            <p>Chain: {{ d.predicted_at_risk }} predicted at risk · {{ d.actually_late }} left 15+ min late · {{ d.cancelled }} cancelled.</p>
        </section>

        <p class="text-xs text-slate-500">{{ HINDSIGHT }}</p>

        <div class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full whitespace-nowrap text-left text-sm">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600">
                    <tr>
                        <th :class="cell">Leg</th><th :class="cell">Flight</th><th :class="cell">Route</th><th :class="cell">Sched dep (local)</th>
                        <th :class="cell">Predicted dep delay (frozen)</th><th :class="cell">Actual dep delay</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="l in legs" :key="`${l.kind}-${l.flight_id}`" class="border-t border-slate-100" :class="[l.is_target && 'bg-sky-50', l.kind === 'cancelled' && 'text-slate-500']">
                        <td :class="cell">{{ l.depth }}</td>
                        <td :class="cell">{{ l.carrier }} {{ l.flight_number }} <span v-if="l.is_target" class="badge bg-sky-100 text-sky-900">target</span></td>
                        <td :class="cell">{{ l.origin }} → {{ l.dest }}</td>
                        <td :class="cell" :title="utcTitle(l.sched_dep_utc)">{{ sched(l) }}</td>
                        <td :class="cell">
                            <template v-if="l.kind === 'selected'">decided on</template>
                            <template v-else-if="l.kind === 'cancelled'">cancelled in the gap, not predicted</template>
                            <span v-else-if="l.at_risk" class="badge bg-amber-100 text-amber-900">{{ l.predicted_dep_delay }} min · at risk</span>
                            <template v-else-if="l.predicted_dep_delay !== null">{{ l.predicted_dep_delay }} min</template>
                            <span v-else class="text-slate-500">not predicted ({{ l.stop_reason }})</span>
                        </td>
                        <td :class="cell">
                            <template v-if="l.current_flight_id === null">flight not found after rebuild</template>
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
