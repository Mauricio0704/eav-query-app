<script setup>
import { ref } from 'vue'
import { Database, Eye, Copy, Check, Play } from 'lucide-vue-next'
import { state, sqlPreview, canRun, runCurrentQuery } from '../store.js'

const sqlCopied = ref(false)
const showSQL = ref(false)

async function copySQL() {
    try {
        await navigator.clipboard.writeText(sqlPreview.value)
        sqlCopied.value = true
        setTimeout(() => { sqlCopied.value = false }, 2000)
    } catch (e) {
        console.error('Clipboard write failed:', e)
    }
}

function truncate(text, n) {
    return text.length > n ? text.slice(0, n) + '…' : text
}
</script>

<template>
    <aside class="w-[280px] shrink-0 bg-white border-r border-[#e2e8f0] flex flex-col">
        <!-- Logo -->
        <div class="p-4 border-b border-[#e2e8f0]">
            <div class="flex items-center gap-3 px-2 py-2">
                <div class="bg-[#008378] rounded-lg size-10 flex items-center justify-center">
                    <Database class="size-4 text-white" />
                </div>
                <div>
                    <h1 class="font-['Manrope'] font-extrabold text-[#0d9488] text-lg tracking-tight">
                        Encuesta NL
                    </h1>
                    <p class="text-[10px] text-[#94a3b8] font-bold tracking-wider uppercase">
                        Así Vamos · 2025
                    </p>
                </div>
            </div>
        </div>

        <!-- Query Controls -->
        <div class="flex-1 p-4 space-y-6 overflow-y-auto">
            <!-- Pregunta -->
            <div>
                <label class="text-xs font-medium text-[#64748b] uppercase tracking-wide mb-2 block">
                    Pregunta
                </label>
                <div class="relative">
                    <select
                        v-model="state.questionId"
                        class="w-full bg-[#f1f5f9] border-0 rounded px-3 py-2.5 text-sm text-[#334155] font-medium appearance-none cursor-pointer"
                    >
                        <option value="">— Selecciona una pregunta —</option>
                        <option v-for="q in state.questions" :key="q.q_id" :value="q.q_id">
                            {{ q.q_id }} — {{ truncate(q.q_text, 60) }}
                        </option>
                    </select>
                    <svg
                        class="absolute right-3 top-1/2 -translate-y-1/2 w-3 h-2 pointer-events-none"
                        fill="none"
                        viewBox="0 0 12 7.4"
                    >
                        <path
                            d="M1 1L6 6L11 1"
                            stroke="#94A3B8"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                        />
                    </svg>
                </div>
            </div>

            <!-- Group By -->
            <div>
                <label class="text-xs font-medium text-[#64748b] uppercase tracking-wide mb-2 block">
                    Agrupar resultados por
                </label>
                <div class="relative">
                    <select
                        v-model="state.groupBy"
                        class="w-full bg-[#f1f5f9] border-0 rounded px-3 py-2.5 text-sm text-[#334155] font-medium appearance-none cursor-pointer"
                    >
                        <option value="answer">Respuesta</option>
                        <option value="city_id">Ciudad</option>
                        <option v-for="a in state.attributes" :key="a.attribute" :value="a.attribute">
                            {{ a.attribute }}
                        </option>
                    </select>
                    <svg
                        class="absolute right-3 top-1/2 -translate-y-1/2 w-3 h-2 pointer-events-none"
                        fill="none"
                        viewBox="0 0 12 7.4"
                    >
                        <path
                            d="M1 1L6 6L11 1"
                            stroke="#94A3B8"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                        />
                    </svg>
                </div>
            </div>

            <!-- SQL Preview Toggle -->
            <div>
                <button
                    @click="showSQL = !showSQL"
                    class="w-full flex items-center justify-between p-3 bg-[#f8fafc] hover:bg-[#f1f5f9] rounded-lg transition-colors"
                >
                    <span class="text-xs font-medium text-[#64748b] uppercase tracking-wide">
                        SQL Generado
                    </span>
                    <Eye :class="['size-4', showSQL ? 'text-[#0d9488]' : 'text-[#94a3b8]']" />
                </button>

                <div v-if="showSQL" class="mt-2">
                    <div class="flex items-center justify-end mb-2">
                        <button
                            @click="copySQL"
                            class="flex items-center gap-1 text-[#0d9488] hover:text-[#00685f] transition-colors"
                        >
                            <template v-if="sqlCopied">
                                <Check class="size-3" />
                                <span class="text-xs font-bold">Copiado</span>
                            </template>
                            <template v-else>
                                <Copy class="size-3" />
                                <span class="text-xs font-bold">Copiar</span>
                            </template>
                        </button>
                    </div>
                    <div class="bg-[#0f172a] rounded-lg p-4 border border-[#1e293b] shadow-inner">
                        <pre class="text-xs font-mono leading-relaxed text-[#5feaba] whitespace-pre-wrap break-all m-0">{{ sqlPreview }}</pre>
                    </div>
                </div>
            </div>
        </div>

        <!-- Execute Button -->
        <div class="p-4 border-t border-[#e2e8f0]">
            <button
                @click="runCurrentQuery"
                :disabled="!canRun"
                class="w-full bg-[#0d9488] hover:bg-[#00685f] disabled:opacity-45 disabled:cursor-not-allowed text-white rounded px-4 py-3 flex items-center justify-center gap-2 font-bold shadow-lg shadow-[#0d9488]/20 transition-colors"
            >
                <Play class="size-4 fill-white" />
                Ejecutar consulta
            </button>
        </div>
    </aside>
</template>
