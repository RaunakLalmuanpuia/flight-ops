<script setup>
import { Head, Link } from '@inertiajs/vue3';
import PageHelp from '../components/PageHelp.vue';
import TourBar from '../components/TourBar.vue';
import { ATL_TZ, localDate, localTime, utcTitle } from '../lib/time.js';
import { ACTIONS, HINDSIGHT, outcome } from '../lib/decisions.js';

defineProps({ decisions: Array });
const logged = (v) => `${localDate(v, ATL_TZ)} ${localTime(v, ATL_TZ)}`;
const cell = 'px-2 py-1';
</script>

<template>
    <Head title="Decisions" />
    <TourBar />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="flex flex-wrap items-center gap-4">
            <h1 class="mr-auto text-xl font-semibold">Decision log</h1>
            <Link href="/guide" class="text-sm text-sky-700 underline">Guide</Link>
            <Link href="/day/2024-07-19" class="text-sm text-sky-700 underline">July–August 2024 history →</Link>
        </header>

        <PageHelp>
            <p><strong>What this shows:</strong> every decision logged from a flight page: who, when, what they chose and why.</p>
            <p><strong>How to read it:</strong> <em>Outcome</em> compares the decision with what really happened in 2024. <em>Chance of cancellation</em> says how many later flights were flagged high-risk when the decision was logged. Older decisions were logged before that score existed.</p>
            <p><strong>What to do next:</strong> open a decision to see its full record.</p>
        </PageHelp>
        <p class="text-xs text-slate-500">{{ HINDSIGHT }}</p>

        <p v-if="!decisions.length" class="text-slate-500">No decisions yet. Log one from any flight's impact page.</p>
        <div v-else class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full text-left text-sm">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600">
                    <tr>
                        <th :class="cell">Logged (Atlanta)</th><th :class="cell">Author</th><th :class="cell">Flight</th>
                        <th :class="cell">Action</th><th :class="cell">Target</th><th :class="cell">Outcome</th><th :class="cell">Cancel risk</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="d in decisions" :key="d.decision_id" class="border-t border-slate-100 align-top">
                        <td :class="cell" class="whitespace-nowrap">{{ logged(d.recorded_at) }}</td>
                        <td :class="cell">{{ d.author }}</td>
                        <td :class="cell" class="whitespace-nowrap">
                            <Link :href="`/decisions/${d.decision_id}`" class="text-sky-700 underline">{{ d.carrier }} {{ d.flight_number }} {{ d.origin }} → {{ d.dest }}</Link>
                            <span class="ml-1 text-slate-500">{{ utcTitle(d.sched_dep_utc) }}</span>
                            <span v-if="d.what_if" class="text-slate-500"> · what-if {{ d.arr_delay_min }} min</span>
                        </td>
                        <td :class="cell">{{ ACTIONS[d.action] }}</td>
                        <td :class="cell" class="whitespace-nowrap">
                            <template v-if="d.target_flight_number">{{ d.target_carrier }} {{ d.target_flight_number }} {{ d.target_origin }} → {{ d.target_dest }}</template>
                            <span v-else class="text-slate-500">none</span>
                        </td>
                        <td :class="cell">{{ outcome(d) }}</td>
                        <td :class="cell">
                            <template v-if="d.cancel_risk_recorded">{{ d.flagged_cancel_risk }} flagged</template>
                            <span v-else class="text-slate-500">recorded before cancellation risk</span>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </main>
</template>
