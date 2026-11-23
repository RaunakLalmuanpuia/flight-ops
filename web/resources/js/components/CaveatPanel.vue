<script setup>
import { CAVEATS } from '../lib/flights.js';

const props = defineProps({ caveats: Object, active: String });
const emit = defineEmits(['toggle']);
const present = () => Object.keys(CAVEATS).filter((k) => props.caveats?.[k]);
</script>

<template>
    <section aria-labelledby="caveats-heading">
        <h2 id="caveats-heading" class="text-sm font-semibold text-slate-700">Data warnings for this day</h2>
        <p v-if="!present().length" class="text-sm text-slate-500">None.</p>
        <ul v-else class="mt-1 flex flex-wrap gap-2">
            <li v-for="key in present()" :key="key">
                <button
                    type="button"
                    class="rounded border px-2 py-1 text-sm"
                    :class="active === key ? 'border-slate-800 bg-slate-800 text-white' : 'border-slate-300 bg-white'"
                    :aria-pressed="active === key"
                    @click="emit('toggle', active === key ? '' : key)"
                >
                    {{ caveats[key] }} · {{ CAVEATS[key] }}
                </button>
            </li>
        </ul>
    </section>
</template>
