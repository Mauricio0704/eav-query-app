<script setup>
import { ref, nextTick, watch } from "vue";
import { Send, Sparkles } from "lucide-vue-next";
import { state, sendChatMessage } from "../store.js";
import DataTable from "./DataTable.vue";
import PivotTables from "./PivotTables.vue";

const input = ref("");
const scroller = ref(null);

const suggestions = [
    "¿Qué porcentaje de personas se siente segura en su colonia?",
    "Compara la percepción de inseguridad entre hombres y mujeres",
    "Satisfacción con los servicios de salud por municipio",
];

async function submit() {
    const text = input.value;
    if (!text.trim() || state.chatLoading) return;
    input.value = "";
    await sendChatMessage(text);
}

function useSuggestion(s) {
    if (state.chatLoading) return;
    input.value = s;
    submit();
}

function toolSummary(calls) {
    if (!calls || !calls.length) return "";
    return calls
        .map((c) => {
            const g =
                !c.group_by || c.group_by === "answer"
                    ? ""
                    : ` · agrupado por ${c.group_by}`;
            return `${c.question_id}${g}`;
        })
        .join("  |  ");
}

// Autoscroll on new messages / loading state.
watch(
    () => [state.chatMessages.length, state.chatLoading],
    async () => {
        await nextTick();
        if (scroller.value)
            scroller.value.scrollTop = scroller.value.scrollHeight;
    },
);
</script>

<template>
    <div
        class="flex-1 flex flex-col overflow-hidden bg-linear-to-r from-[#fcf0e4] to-[#7e34c35a]"
    >
        <!-- Messages -->
        <div ref="scroller" class="flex-1 overflow-auto p-8">
            <div class="max-w-4xl mx-auto space-y-6">
                <!-- Empty state -->
                <div
                    v-if="!state.chatMessages.length"
                    class="flex flex-col items-center justify-center text-center gap-4 mt-16"
                >
                    <div class="bg-[#7e34c3]/10 rounded-full p-4">
                        <Sparkles class="size-8 text-[#7e34c3]" />
                    </div>
                    <h3
                        class="font-['Manrope'] font-bold text-xl text-[#1e293b]"
                    >
                        Pregúntale a la encuesta
                    </h3>
                    <p class="text-sm text-[#64748b] max-w-md">
                        Escribe tu pregunta en lenguaje natural. La IA elige la
                        pregunta de la encuesta, aplica filtros y agrupaciones,
                        y te responde con cifras reales.
                    </p>
                    <div class="flex flex-col gap-2 mt-2 w-full max-w-md">
                        <button
                            v-for="s in suggestions"
                            :key="s"
                            @click="useSuggestion(s)"
                            class="text-left text-sm text-[#475569] bg-white border border-[#e2e8f0] rounded-xl px-4 py-3 hover:border-[#7e34c3] hover:text-[#7e34c3] transition-colors"
                        >
                            {{ s }}
                        </button>
                    </div>
                </div>

                <!-- Conversation -->
                <template v-for="(m, i) in state.chatMessages" :key="i">
                    <!-- User bubble -->
                    <div v-if="m.role === 'user'" class="flex justify-end">
                        <div
                            class="max-w-[80%] bg-[#7e34c3] text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm font-medium shadow-sm"
                        >
                            {{ m.text }}
                        </div>
                    </div>

                    <!-- Assistant bubble -->
                    <div v-else class="flex flex-col gap-3">
                        <div
                            class="max-w-[90%] bg-white border border-[#e2e8f0] rounded-2xl rounded-bl-sm px-4 py-3 text-sm leading-relaxed shadow-sm"
                            :class="
                                m.error ? 'text-[#b91c1c]' : 'text-[#1e293b]'
                            "
                        >
                            <p class="whitespace-pre-wrap">{{ m.text }}</p>
                            <p
                                v-if="m.toolCalls && m.toolCalls.length"
                                class="mt-2 pt-2 border-t border-[#f1f5f9] text-[11px] text-[#94a3b8] font-mono"
                            >
                                {{ toolSummary(m.toolCalls) }}
                            </p>
                        </div>

                        <!-- Result table for this answer -->
                        <div
                            v-if="m.data"
                            class="bg-white rounded-lg border border-[#e2e8f0] shadow-sm p-5 space-y-6 overflow-hidden"
                        >
                            <PivotTables
                                v-if="m.data.format === 'pivot'"
                                :data="m.data"
                            />
                            <DataTable v-else :data="m.data" />
                        </div>
                    </div>
                </template>

                <!-- Loading -->
                <div
                    v-if="state.chatLoading"
                    class="flex items-center gap-2.5 text-[#64748b]"
                >
                    <div class="spinner"></div>
                    Analizando…
                </div>
            </div>
        </div>

        <!-- Composer -->
        <div
            class="border-t border-[#e2e8f0] bg-white/70 backdrop-blur px-8 py-4"
        >
            <form
                @submit.prevent="submit"
                class="max-w-4xl mx-auto flex items-end gap-3"
            >
                <textarea
                    v-model="input"
                    rows="1"
                    placeholder="Escribe tu pregunta…"
                    @keydown.enter.exact.prevent="submit"
                    class="flex-1 resize-none bg-[#f1f5f9] border border-gray-300 rounded-2xl px-4 py-3 text-sm text-[#334155] focus:outline-none focus:border-[#7e34c3] max-h-40"
                ></textarea>
                <button
                    type="submit"
                    :disabled="!input.trim() || state.chatLoading"
                    class="bg-[#7e34c3] hover:bg-[#5e2494] disabled:opacity-45 disabled:cursor-not-allowed text-white rounded-2xl px-5 py-3 flex items-center gap-2 font-bold shadow-lg shadow-[#7e34c3]/20 transition-colors shrink-0"
                >
                    <Send class="size-4" />
                </button>
            </form>
        </div>
    </div>
</template>
