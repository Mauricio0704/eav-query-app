<script setup>
import { computed } from 'vue'
import { Database, Download } from 'lucide-vue-next'
import { state, selectedQuestion, exportCurrentCSV } from '../store.js'

const questionText = computed(
    () => selectedQuestion.value?.q_text || 'Selecciona una pregunta en el panel izquierdo'
)
const isEmpty = computed(() => !selectedQuestion.value)
const exportDisabled = computed(() => !state.lastResult)
</script>

<template>
    <header class="bg-white border-b border-[#e2e8f0] px-8 py-4 flex items-center justify-between gap-6">
        <div class="flex items-center gap-2 min-w-0">
            <div class="rounded-full">
                <img src="/minilogo.webp" class="size-8">
            </div>
            <h2
                class="font-['Poppins'] text-lg truncate uppercase text-[#fb7e50] font-extrabold"
            >
                {{ questionText }}
            </h2>
        </div>
        <button
            @click="exportCurrentCSV"
            :disabled="exportDisabled"
            class="flex items-center gap-2 px-4 py-2 border border-[#e2e8f0] rounded hover:bg-[#f8fafc] transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
        >
            <Download class="size-4 text-[#475569]" />
            <span class="font-semibold text-sm text-[#475569]">Descargar CSV</span>
        </button>
    </header>
</template>
