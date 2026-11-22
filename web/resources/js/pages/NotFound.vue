<script setup>
import { Link } from '@inertiajs/vue3';
defineProps({ message: String, range: Object });
</script>
<template>
    <main class="mx-auto max-w-xl p-8">
        <h1 class="text-xl font-semibold">Not found</h1>
        <p class="mt-2">{{ message }}</p>
        <p class="mt-2 text-slate-600">Loaded days: {{ range.first_day }} to {{ range.last_day }}.</p>
        <Link :href="`/day/${range.first_day}`" class="mt-4 inline-block text-sky-700 underline">Go to {{ range.first_day }}</Link>
    </main>
</template>
