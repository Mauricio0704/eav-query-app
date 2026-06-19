<script setup>
import { ref } from 'vue'
import { Eye, Copy, Check, Play, X, SlidersHorizontal, Sparkles, Plus, MessageSquare, Trash2 } from 'lucide-vue-next'
import {
    state,
    sqlPreview,
    canRun,
    runCurrentQuery,
    applyPreset,
    clearPreset,
    removeFilter,
    filterValueLabel,
    questionsBySection,
    setQueryMode,
    newConversation,
    loadConversation,
    deleteConversation,
} from '../store.js'

function relativeTime(ts) {
    const diff = Date.now() - ts
    const min = Math.floor(diff / 60000)
    if (min < 1) return 'ahora'
    if (min < 60) return `hace ${min} min`
    const h = Math.floor(min / 60)
    if (h < 24) return `hace ${h} h`
    const d = Math.floor(h / 24)
    if (d === 1) return 'ayer'
    return `hace ${d} d`
}

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

function onPresetChange(e) {
    applyPreset(e.target.value)
}

function onGroupByChange(e) {
    state.groupBy = e.target.value
    state.appliedPreset = ''
}
</script>

<template>
    <aside class="w-70 shrink-0 bg-white border-r border-[#e2e8f0] flex flex-col">
        <!-- Logo -->
        <div class="p-4 border-b border-[#e2e8f0]">
            <div class="flex items-center gap-3 px-2 py-2">
                <img src="/logo.webp" alt="Logo" class="size-22 object-contain" />
                <div>
                    <h1 class="font-['Manrope'] font-extrabold text-[#7e34c3] text-center text-[20px] tracking-tight">
                        Encuesta
                    </h1>
                    <p class="text-[10px] text-[#94a3b8] font-bold tracking-wider uppercase">
                        Así Vamos · 2025
                    </p>
                </div>
            </div>
        </div>

        <!-- Query Controls -->
        <div class="flex-1 p-4 space-y-6 overflow-y-auto">
            <!-- Modo de Consulta -->
            <div>
                <label class="text-xs font-medium text-[#64748b] uppercase tracking-wide mb-2 block">
                    Modo de Consulta
                </label>
                <div class="grid grid-cols-2 gap-2 bg-[#f1f5f9] p-1 rounded-2xl">
                    <button
                        @click="setQueryMode('manual')"
                        class="flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-bold transition-colors"
                        :class="state.queryMode === 'manual'
                            ? 'bg-white text-[#0d9488] shadow-sm'
                            : 'text-[#94a3b8] hover:text-[#64748b]'"
                    >
                        <SlidersHorizontal class="size-4" />
                        Manual
                    </button>
                    <button
                        @click="setQueryMode('ai')"
                        class="flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-bold transition-colors"
                        :class="state.queryMode === 'ai'
                            ? 'bg-white text-[#7e34c3] shadow-sm'
                            : 'text-[#94a3b8] hover:text-[#64748b]'"
                    >
                        <Sparkles class="size-4" />
                        IA
                    </button>
                </div>
            </div>

            <!-- Manual query builder controls -->
            <template v-if="state.queryMode === 'manual'">
            <!-- Pregunta -->
            <div>
                <label class="text-xs font-medium text-[#64748b] uppercase tracking-wide mb-2 block">
                    Pregunta
                </label>
                <div class="relative">
                    <select
                        v-model="state.questionId"
                        class="w-full bg-[#f1f5f9] border border-gray-300 rounded-4xl px-3 py-2.5 text-sm text-[#334155] font-medium appearance-none cursor-pointer"
                    >
                        <option value="">— Selecciona una pregunta —</option>
                        <optgroup
                            v-for="g in questionsBySection"
                            :key="g.key"
                            :label="g.label"
                        >
                            <option v-for="q in g.questions" :key="q.q_id" :value="q.q_id">
                                {{ q.q_id }} — {{ truncate(q.q_text, 60) }}
                            </option>
                        </optgroup>
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

            <!-- Análisis predefinido -->
            <div>
                <label class="text-xs font-medium text-[#64748b] uppercase tracking-wide mb-2 block">
                    Análisis predefinido
                </label>
                <div class="relative">
                    <select
                        :value="state.appliedPreset"
                        @change="onPresetChange"
                        class="w-full bg-[#f1f5f9] border border-gray-300 rounded-4xl px-3 py-2.5 text-sm text-[#334155] font-medium appearance-none cursor-pointer"
                    >
                        <option value="">— Ninguno (configura manualmente) —</option>
                        <option v-for="p in state.presets" :key="p.key" :value="p.key">
                            {{ p.label }}
                        </option>
                    </select>
                    <svg
                        class="absolute right-3 top-1/2 -translate-y-1/2 w-3 h-2 pointer-events-none"
                        fill="none"
                        viewBox="0 0 12 7.4"
                    >
                        <path d="M1 1L6 6L11 1" stroke="#94A3B8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
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
                        :value="state.groupBy"
                        @change="onGroupByChange"
                        class="w-full bg-[#f1f5f9] border border-gray-300 rounded-4xl px-3 py-2.5 text-sm text-[#334155] font-medium appearance-none cursor-pointer"
                    >
                        <option value="answer">Respuesta</option>
                        <option value="city_id">Ciudad</option>
                        <optgroup label="Atributos">
                            <option v-for="a in state.attributes" :key="a.attribute" :value="a.attribute">
                                {{ a.attribute }}
                            </option>
                        </optgroup>
                        <optgroup v-if="state.recodes.length" label="Recodes">
                            <option v-for="r in state.recodes" :key="r.key" :value="r.key">
                                {{ r.label }}
                            </option>
                        </optgroup>
                    </select>
                    <svg
                        class="absolute right-3 top-1/2 -translate-y-1/2 w-3 h-2 pointer-events-none"
                        fill="none"
                        viewBox="0 0 12 7.4"
                    >
                        <path d="M1 1L6 6L11 1" stroke="#94A3B8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                    </svg>
                </div>
            </div>

            <!-- Filtros aplicados -->
            <div v-if="state.filters.length">
                <div class="flex items-center justify-between mb-2">
                    <label class="text-xs font-medium text-[#64748b] uppercase tracking-wide">
                        Filtros
                    </label>
                    <button
                        @click="clearPreset"
                        class="text-xs text-[#94a3b8] hover:text-[#0d9488] font-medium"
                    >
                        Limpiar
                    </button>
                </div>
                <div class="flex flex-wrap gap-1.5">
                    <span
                        v-for="(f, i) in state.filters"
                        :key="i"
                        class="inline-flex items-center gap-1 bg-[#f0fdfa] text-[#0d9488] text-xs font-medium px-2 py-1 rounded"
                    >
                        <span>{{ f.attribute }}: {{ filterValueLabel(f) }}</span>
                        <button
                            @click="removeFilter(i)"
                            class="hover:text-[#00685f]"
                            aria-label="Quitar filtro"
                        >
                            <X class="size-3" />
                        </button>
                    </span>
                </div>
            </div>

            <!-- Initial only toggle -->
            <div>
                <label class="flex items-start gap-3 cursor-pointer">
                    <input
                        type="checkbox"
                        v-model="state.initialOnly"
                        class="mt-0.5 size-4 accent-[#0d9488] cursor-pointer"
                    />
                    <span class="flex-1">
                        <span class="text-sm font-medium text-[#1e293b] block">
                            Proyectar a la población
                        </span>
                        <span class="text-xs text-[#64748b] block leading-snug mt-0.5">
                            Restringe a respondientes iniciales y aplica
                            <code class="text-[10px]">factor_cvnl</code>.
                            Apaga para ver conteos crudos del muestreo.
                        </span>
                    </span>
                </label>
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
                        <pre class="text-xs font-mono leading-relaxed text-code-fg whitespace-pre-wrap break-all m-0 text-[rgba(45,212,191,0.9)]">{{ sqlPreview }}</pre>
                    </div>
                </div>
            </div>
            </template>

            <!-- AI mode: conversation history -->
            <template v-else>
                <button
                    @click="newConversation"
                    class="w-full flex items-center justify-center gap-2 bg-[#7e34c3] hover:bg-[#5e2494] text-white rounded-2xl px-4 py-2.5 text-sm font-bold shadow-sm transition-colors"
                >
                    <Plus class="size-4" />
                    Nueva conversación
                </button>

                <div>
                    <label class="text-xs font-medium text-[#64748b] uppercase tracking-wide mb-2 block">
                        Conversaciones recientes
                    </label>

                    <p
                        v-if="!state.conversations.length"
                        class="text-xs text-[#94a3b8] leading-snug"
                    >
                        Tus conversaciones aparecerán aquí. Se guardan las 5 más
                        recientes en este navegador.
                    </p>

                    <div v-else class="space-y-1">
                        <div
                            v-for="c in state.conversations"
                            :key="c.id"
                            @click="loadConversation(c.id)"
                            class="group flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer transition-colors"
                            :class="c.id === state.currentConversationId
                                ? 'bg-[#7e34c3]/10 text-[#7e34c3]'
                                : 'text-[#475569] hover:bg-[#f1f5f9]'"
                        >
                            <MessageSquare class="size-4 shrink-0" />
                            <div class="flex-1 min-w-0">
                                <p class="text-sm font-medium truncate">{{ c.title }}</p>
                                <p class="text-[10px] text-[#94a3b8]">{{ relativeTime(c.updatedAt) }}</p>
                            </div>
                            <button
                                @click.stop="deleteConversation(c.id)"
                                class="opacity-0 group-hover:opacity-100 text-[#94a3b8] hover:text-[#b91c1c] transition-opacity shrink-0"
                                aria-label="Eliminar conversación"
                            >
                                <Trash2 class="size-3.5" />
                            </button>
                        </div>
                    </div>
                </div>
            </template>
        </div>

        <!-- Execute Button (manual mode only) -->
        <div v-if="state.queryMode === 'manual'" class="p-4 border-t border-[#e2e8f0]">
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
