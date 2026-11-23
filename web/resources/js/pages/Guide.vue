<script setup>
import { Head, Link } from '@inertiajs/vue3';
import { GLOSSARY, GROUPS } from '../lib/glossary.js';
import { stepHref } from '../lib/tour.js';

const inGroup = (g) => Object.entries(GLOSSARY).filter(([, e]) => e.group === g);
</script>

<template>
    <Head title="Welcome" />
    <main class="mx-auto max-w-3xl space-y-8 px-4 py-10">
        <header class="space-y-3">
            <h1 class="text-2xl font-semibold">Flight operations console · Atlanta</h1>
            <p>
                Every airline has an operations control team that watches its flights and decides what to do when things go wrong.
                When one flight is late, the same aircraft's later flights are late too, unless someone acts.
            </p>
            <p>
                This console answers one question for Atlanta (ATL), using real US flight records from July and August 2024:
                <strong>a flight is late, so which later flights does that hurt, and should one of them be cancelled?</strong>
            </p>
            <div class="flex flex-wrap items-center gap-3 pt-2">
                <Link :href="stepHref(1)" class="rounded bg-sky-700 px-4 py-2 font-semibold text-white hover:bg-sky-800">Start the tour (5 steps, about 5 minutes)</Link>
                <Link href="/day/2024-07-19" class="text-sky-700 underline">Skip, go to the console</Link>
            </div>
            <p class="text-sm text-slate-600">
                The tour follows 19 July 2024, when a software outage grounded Delta's fleet. You can leave it any time and come back here from the "Guide" link on every page.
            </p>
        </header>

        <section aria-labelledby="glossary-heading" class="space-y-6">
            <div>
                <h2 id="glossary-heading" class="text-xl font-semibold">Glossary</h2>
                <p class="text-sm text-slate-600">Every term the console uses, in plain words. Press ⓘ next to a term on any page to jump here.</p>
            </div>
            <section v-for="[g, title] in GROUPS" :key="g" :aria-labelledby="`g-${g}`" class="space-y-3">
                <h3 :id="`g-${g}`" class="font-semibold text-slate-700">{{ title }}</h3>
                <dl class="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
                    <div v-for="[k, e] in inGroup(g)" :id="k" :key="k" class="scroll-mt-4 p-3 target:bg-amber-50">
                        <dt class="font-semibold">{{ e.plain }} <span v-if="e.term" class="font-normal text-slate-500">({{ e.term }})</span></dt>
                        <dd class="text-sm">{{ e.short }}</dd>
                        <dd class="mt-1 text-xs text-slate-600"><span class="font-semibold">Go deeper:</span> {{ e.deeper }}</dd>
                    </div>
                </dl>
            </section>
        </section>
    </main>
</template>
