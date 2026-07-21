<script setup>
import { computed } from 'vue'
import { Calendar } from 'lucide-vue-next'
import { state, selectedQuestion, setWave } from '../store.js'

const questionText = computed(() =>
  state.queryMode === 'ai'
    ? 'Haz una pregunta'
    : selectedQuestion.value?.q_text ||
      'Selecciona una pregunta en el panel izquierdo',
)

function onWaveChange(e) {
  setWave(e.target.value)
}
</script>

<template>
  <header
    class="bg-white border-b border-[#e2e8f0] px-8 py-4 flex items-center justify-between gap-6"
  >
    <div class="flex items-center gap-2 min-w-0">
      <div class="rounded-full shrink-0">
        <img src="/minilogo.webp" class="size-8 max-w-none" />
      </div>
      <h2
        class="font-['Poppins'] text-lg whitespace-nowrap overflow-x-auto min-w-0 uppercase text-[#fb7e50] font-extrabold"
      >
        {{ questionText }}
      </h2>
    </div>

    <div
      v-if="state.waves.length > 1"
      class="flex items-center gap-2 shrink-0"
      title="Levantamiento de la encuesta"
    >
      <Calendar class="size-4 text-[#94a3b8]" />
      <label class="text-xs font-medium text-[#64748b] uppercase tracking-wide">
        Encuesta
      </label>
      <select
        :value="state.waveId"
        :disabled="state.loading"
        @change="onWaveChange"
        class="font-['Poppins'] text-sm font-semibold text-[#334155] bg-[#f8fafc] border border-[#e2e8f0] rounded-lg px-3 py-1.5 cursor-pointer hover:border-[#fb7e50] focus:outline-none focus:border-[#fb7e50] focus:ring-1 focus:ring-[#fb7e50] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <option v-for="w in state.waves" :key="w.wave_id" :value="w.wave_id">
          {{ w.label || w.year }}
        </option>
      </select>
    </div>
  </header>
</template>
