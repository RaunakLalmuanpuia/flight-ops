<script setup>
import { computed } from 'vue';
import { Link } from '@inertiajs/vue3';
import { CANCELLATION, delayText } from '../lib/flights.js';
import { axis, bar, dayBand, dayMarks, gapLabel, hoursMinutes, lateText } from '../lib/legs.js';
import { ATL_TZ, localDate, localTime, shortDate, utcTitle } from '../lib/time.js';

const props = defineProps({ legs: Array, day: String });

const span = computed(() => axis(props.legs));
const marks = computed(() => dayMarks(span.value, ATL_TZ));
const band = computed(() => dayBand(props.day, span.value, ATL_TZ));

const rows = computed(() => {
    return props.legs.map((leg) => ({
        leg,
        gap: gapLabel(leg),
        sched: bar(leg.sched_dep_utc, leg.sched_arr_utc, span.value),
        actual: leg.cancelled ? null : bar(leg.actual_dep_utc, leg.actual_arr_utc, span.value),
        late: lateText(leg),
        arrTz: leg.landed_tz ?? leg.dest_tz,
    }));
});
const place = (b) => ({ left: `${b.left}%`, width: `${b.width}%` });
</script>

<template>
    <div class="grid grid-cols-1 gap-2 px-3 md:grid-cols-[22rem_1fr]" aria-hidden="true">
        <div class="hidden md:block" />
        <div class="relative h-5">
            <div v-for="m in marks" :key="m.day" class="absolute top-0 h-full text-xs text-slate-500" :style="{ left: `${m.left}%` }">
                <span class="absolute bottom-0 left-0 h-2 w-px bg-slate-400" /><span class="pl-1">{{ shortDate(m.day) }}</span>
            </div>
        </div>
    </div>
    <ol class="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
        <template v-for="r in rows" :key="r.leg.flight_id">
            <li v-if="r.gap" class="bg-amber-50 px-3 py-2 text-sm text-amber-900">
                {{ r.gap }}<template v-if="r.leg.gap_minutes !== null"> · {{ hoursMinutes(r.leg.gap_minutes) }} between legs</template>
            </li>
            <li class="grid grid-cols-1 gap-2 px-3 py-2 md:grid-cols-[22rem_1fr]" :class="[{ 'opacity-60': r.leg.leg_day !== day }, r.leg.cancelled && 'bg-slate-50 text-slate-500']">
                <div class="space-y-1 text-sm">
                    <div class="font-medium">
                        {{ localDate(r.leg.sched_dep_utc, r.leg.origin_tz) }} ·
                        <Link v-if="!r.leg.cancelled" :href="`/flights/${r.leg.flight_id}`" class="text-sky-700 underline" title="What a delay here puts at risk downstream">{{ r.leg.carrier }} {{ r.leg.flight_number }}</Link>
                        <template v-else>{{ r.leg.carrier }} {{ r.leg.flight_number }}</template>
                        · {{ r.leg.origin }} → {{ r.leg.dest }}
                        <span v-if="r.leg.diverted" class="text-violet-700">(landed {{ r.leg.landed ?? '?' }})</span>
                    </div>
                    <div class="text-slate-600">
                        <span :title="utcTitle(r.leg.sched_dep_utc)">{{ localTime(r.leg.sched_dep_utc, r.leg.origin_tz) }}</span>–<span :title="utcTitle(r.leg.sched_arr_utc)">{{ localTime(r.leg.sched_arr_utc, r.leg.dest_tz) }}</span> scheduled
                        <template v-if="!r.leg.cancelled">
                            · <span :title="utcTitle(r.leg.actual_dep_utc)">{{ localTime(r.leg.actual_dep_utc, r.leg.origin_tz) }}</span>–<span :title="utcTitle(r.leg.actual_arr_utc)">{{ localTime(r.leg.actual_arr_utc, r.arrTz) }}</span> actual
                        </template>
                        <span class="text-xs text-slate-400">(local)</span>
                    </div>
                    <div class="flex flex-wrap gap-1">
                        <span v-if="r.leg.cancelled" class="badge bg-red-100 text-red-800" :title="`BTS cancellation code ${r.leg.cancellation_code}`">Cancelled · {{ CANCELLATION[r.leg.cancellation_code] ?? r.leg.cancellation_code }} · unflown</span>
                        <span v-else-if="r.late" class="badge bg-amber-100 text-amber-900">Late: {{ r.late }}</span>
                        <span v-if="r.leg.leg_day !== day" class="badge bg-slate-100 text-slate-600">Outside this day · ATL date {{ shortDate(r.leg.leg_day) }}</span>
                        <span v-if="r.leg.aircraft_link_confidence === 'medium'" class="badge bg-amber-50 text-amber-900">Medium-confidence aircraft</span>
                        <span v-if="!r.leg.aircraft_id" class="badge bg-amber-50 text-amber-900">Aircraft not resolved</span>
                    </div>
                    <div v-if="delayText(r.leg.delays)" class="text-slate-600">Delay causes: {{ delayText(r.leg.delays) }}</div>
                    <details v-if="r.leg.metar_raw_text" class="text-xs text-slate-500">
                        <summary class="cursor-pointer">ATL METAR, {{ r.leg.metar_staleness_min }} min old<template v-if="r.leg.metar_adverse"> · adverse</template></summary>
                        <code class="break-words">{{ r.leg.metar_raw_text }}</code>
                    </details>
                </div>
                <div class="relative h-10" aria-hidden="true">
                    <div v-if="band" class="absolute inset-y-0 bg-sky-50" :style="place(band)" />
                    <div v-for="m in marks" :key="m.day" class="absolute inset-y-0 w-px bg-slate-200" :style="{ left: `${m.left}%` }" />
                    <div v-if="r.sched" class="absolute top-1 h-2.5 rounded bg-slate-300" :style="place(r.sched)" />
                    <div v-if="r.actual" class="absolute top-4 h-2.5 rounded" :class="r.late ? 'bg-amber-500' : 'bg-slate-600'" :style="place(r.actual)" />
                </div>
            </li>
        </template>
    </ol>
</template>
