<script setup>
import { computed } from 'vue'
import { Database } from 'lucide-vue-next'
import { state, selectedQuestion } from '../store.js'

const questionText = computed(
    () => selectedQuestion.value?.q_text || 'Selecciona una pregunta en el panel izquierdo'
)
const isEmpty = computed(() => !selectedQuestion.value)
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
    </header>
</template>
