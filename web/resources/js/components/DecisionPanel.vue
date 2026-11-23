<script setup>
import { watch } from 'vue';
import { Link, useForm } from '@inertiajs/vue3';
import { ATL_TZ, localDate, localTime } from '../lib/time.js';
import { ACTIONS, rememberAuthor, rememberedAuthor, targetLabel } from '../lib/decisions.js';

const props = defineProps({ flightId: Number, legs: Array, whatIfDelay: Number, decisions: Array });

const form = useForm({ action: 'accept_delay', target: null, reason: '', author: rememberedAuthor() });
watch(() => form.action, (action) => {
    if (action === 'accept_delay') form.target = null;
});

const submit = () => {
    rememberAuthor(form.author);
    form
        // Read at submit time: the page's what-if can change while the form keeps its state
        .transform((data) => ({ ...data, delay: props.whatIfDelay }))
        .post(`/flights/${props.flightId}/decisions`, { preserveScroll: true, onSuccess: () => form.reset('reason', 'target') });
};
const recorded = (d) => `${localDate(d.recorded_at, ATL_TZ)} ${localTime(d.recorded_at, ATL_TZ)}`;
const field = 'rounded border border-slate-300 bg-white px-1 py-0.5';
</script>

<template>
    <section class="space-y-3 rounded border border-slate-200 bg-white p-3 text-sm">
        <h2 class="font-semibold">Log a decision</h2>
        <form class="grid gap-2 sm:grid-cols-2" @submit.prevent="submit">
            <label class="flex flex-col gap-1">Action
                <select v-model="form.action" :class="field">
                    <option v-for="(label, value) in ACTIONS" :key="value" :value="value">{{ label }}</option>
                </select>
            </label>
            <label v-if="form.action !== 'accept_delay'" class="flex flex-col gap-1">Target leg (optional)
                <select v-model="form.target" :class="field">
                    <option :value="null">None</option>
                    <option v-for="l in legs" :key="`${l.kind}-${l.flight_id}`" :value="l.flight_id">{{ targetLabel(l) }}</option>
                </select>
            </label>
            <label class="flex flex-col gap-1 sm:col-span-2">Reason
                <textarea v-model="form.reason" required rows="2" maxlength="2000" :class="field"></textarea>
            </label>
            <label class="flex flex-col gap-1">Your name
                <input v-model="form.author" required maxlength="100" autocomplete="name" :class="field" />
            </label>
            <div class="flex items-end">
                <button type="submit" :disabled="form.processing" class="rounded border border-slate-300 bg-white px-2 py-0.5">Log decision</button>
            </div>
            <p v-for="(message, key) in form.errors" :key="key" class="text-red-700 sm:col-span-2" role="alert">{{ message }}</p>
        </form>
        <p v-if="whatIfDelay !== null" class="text-xs text-slate-500">Logged against the {{ whatIfDelay }}-min what-if, with the chain shown above.</p>

        <div v-if="decisions.length" class="space-y-1">
            <h3 class="font-semibold">Earlier decisions on this flight</h3>
            <ul class="divide-y divide-slate-100">
                <li v-for="d in decisions" :key="d.decision_id" class="py-1">
                    <Link :href="`/decisions/${d.decision_id}`" class="text-sky-700 underline">{{ recorded(d) }}</Link> · {{ d.author }} · {{ ACTIONS[d.action] }}<template v-if="d.target_flight_number">: {{ d.target_carrier }} {{ d.target_flight_number }} {{ d.target_origin }} → {{ d.target_dest }}</template><template v-if="d.match_label"> · {{ d.match_label }}</template>
                </li>
            </ul>
        </div>
    </section>
</template>
