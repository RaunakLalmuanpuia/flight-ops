<script setup>
import { Head, Link } from '@inertiajs/vue3';
import PageHelp from '../components/PageHelp.vue';
import TourBar from '../components/TourBar.vue';
import DayNav from '../components/DayNav.vue';
import TailLegs from '../components/TailLegs.vue';
import { REASONS } from '../lib/legs.js';

defineProps({ tail: String, day: String, range: Object, aircraft: Array, legs: Array });
</script>

<template>
    <Head :title="`${tail} ${day}`" />
    <TourBar />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="flex flex-wrap items-center gap-4">
            <div class="mr-auto">
                <Link :href="`/day/${day}`" class="text-sm text-sky-700 underline">← ATL on {{ day }}</Link> · <Link href="/guide" class="text-sm text-sky-700 underline">Guide</Link>
                <h1 class="text-xl font-semibold">{{ tail }} · {{ day }}</h1>
            </div>
            <DayNav :day="day" :range="range" :base="`/tail/${tail}`" />
        </header>

        <PageHelp>
            <p><strong>What this shows:</strong> every flight one aircraft flew around this day, in order.</p>
            <p><strong>How to read it:</strong> the grey bar is when the flight was planned, the dark bar is when it really flew (amber when 15+ minutes late). The shaded band is this day in Atlanta. Each flight should start where the last one landed. If it doesn't, a gap is labelled, usually flying the US data doesn't cover.</p>
            <p><strong>What to do next:</strong> click a flight to see how its delay spreads to the aircraft's later flights.</p>
        </PageHelp>

        <section aria-label="Aircraft" class="text-sm">
            <p v-if="!aircraft.length" class="text-slate-500">No flights for this tail on this day.</p>
            <p v-for="(a, i) in aircraft" :key="i">
                <template v-if="a.confidence">{{ a.manufacturer }} {{ a.model }} · {{ a.confidence }} confidence ({{ a.method }}) · {{ a.flights }} flights in July</template>
                <template v-else>Aircraft not resolved: {{ REASONS[a.unresolved_reason] ?? a.unresolved_reason ?? 'no reason recorded' }} · {{ a.flights }} flights</template>
            </p>
        </section>

        <p class="text-xs text-slate-500">Grey bar: scheduled. Dark bar: actual (amber when 15+ minutes late). The shaded band is this day in Atlanta time. A leg belongs to the ATL date of its scheduled departure. Row dates are local at the origin. Faded rows are the legs either side of this day.</p>

        <TailLegs v-if="legs.length" :legs="legs" :day="day" />
        <p v-else class="text-slate-500">No legs on this day.</p>
    </main>
</template>
