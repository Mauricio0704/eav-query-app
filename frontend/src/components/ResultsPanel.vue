<script setup>
import { computed } from "vue";
import { Table2, BarChart3 } from "lucide-vue-next";
import { state } from "../store.js";
import DataTable from "./DataTable.vue";
import PivotTables from "./PivotTables.vue";
import ChartView from "./ChartView.vue";

const isPivot = computed(() => state.lastResult?.format === "pivot");
const totalRespondents = computed(
    () => state.lastResult?.total_respondents?.toLocaleString("es-MX") ?? "—",
);
const groupByLabel = computed(() => {
    const g = state.lastResult?.group_by;
    return !g || g === "answer" ? "Respuesta" : g;
});

function setTab(t) {
    state.activeTab = t;
}
</script>

<template>
    <div class="flex-1 overflow-auto p-8">
        <!-- Loading -->
        <div
            v-if="state.loading"
            class="flex items-center justify-center h-full gap-2.5 text-[#64748b]"
        >
            <div class="spinner"></div>
            Consultando…
        </div>

        <!-- Error -->
        <div
            v-else-if="state.error"
            class="flex flex-col items-center justify-center h-full text-[#94a3b8] text-center gap-3"
        >
            <div class="text-[42px]">⚠</div>
            <div class="font-['Manrope'] font-semibold text-lg text-[#1e293b]">
                Error al consultar
            </div>
            <div class="text-sm">{{ state.error }}</div>
        </div>

        <!-- Empty -->
        <div
            v-else-if="!state.lastResult"
            class="flex flex-col items-center justify-center h-full text-[#94a3b8] text-center gap-3"
        >
            <div class="text-[42px] opacity-80">◈</div>
            <div class="font-['Manrope'] font-semibold text-lg text-[#1e293b]">
                Sin resultados aún
            </div>
            <div class="text-sm">
                Configura los filtros y presiona "Ejecutar consulta"
            </div>
        </div>

        <!-- Results -->
        <div v-else class="max-w-[1280px] mx-auto space-y-8">
            <!-- Summary Cards -->
            <div class="grid grid-cols-3 gap-6">
                <div
                    class="col-span-2 bg-white rounded-lg border border-[#e2e8f0] shadow-sm p-8 relative overflow-hidden"
                >
                    <div class="relative">
                        <p
                            class="text-xs font-bold text-[#64748b] uppercase tracking-wider mb-2"
                        >
                            Total Muestra
                        </p>
                        <h3
                            class="font-['Manrope'] font-bold text-[32px] text-[#0f172a] tracking-tight mb-2"
                        >
                            {{ totalRespondents }} Respondentes
                        </h3>
                        <span
                            class="inline-block bg-[#f0fdfa] text-[#0d9488] px-2 py-1 rounded text-xs font-bold"
                        >
                            {{ state.lastResult.question.q_id }} ·
                            {{ state.lastResult.question.q_type }}
                        </span>
                    </div>
                </div>

                <div
                    class="bg-[#00685f] rounded-lg shadow-lg p-8 flex flex-col justify-between"
                >
                    <p
                        class="text-xs font-bold text-white/80 uppercase tracking-wide"
                    >
                        Agrupado por
                    </p>
                    <div>
                        <p
                            class="font-['Manrope'] font-semibold text-[24px] text-white mb-1"
                        >
                            {{ groupByLabel }}
                        </p>
                        <p class="text-xs font-medium text-[#ccfbf1]">
                            Modo: {{ state.lastResult.format }}
                        </p>
                    </div>
                </div>
            </div>

            <!-- Data Visualization Card -->
            <div
                class="bg-white rounded-lg border border-[#e2e8f0] shadow-sm overflow-hidden"
            >
                <div
                    class="border-b border-[#f1f5f9] px-6 py-3 flex items-center justify-between"
                >
                    <div class="flex gap-8">
                        <button
                            @click="setTab('table')"
                            class="flex items-center gap-2 pb-3 border-b-2 transition-colors"
                            :class="
                                state.activeTab === 'table'
                                    ? 'border-[#0d9488] text-[#0d9488]'
                                    : 'border-transparent text-[#94a3b8]'
                            "
                        >
                            <Table2 class="size-3.5" />
                            <span class="font-bold text-sm">Tabla</span>
                        </button>
                        <button
                            @click="setTab('chart')"
                            class="flex items-center gap-2 pb-3 border-b-2 transition-colors"
                            :class="
                                state.activeTab === 'chart'
                                    ? 'border-[#0d9488] text-[#0d9488]'
                                    : 'border-transparent text-[#94a3b8]'
                            "
                        >
                            <BarChart3 class="size-3.5" />
                            <span class="font-bold text-sm">Gráfica</span>
                        </button>
                    </div>
                </div>

                <div
                    v-show="state.activeTab === 'table'"
                    class="p-6 space-y-8"
                >
                    <PivotTables v-if="isPivot" :data="state.lastResult" />
                    <DataTable v-else :data="state.lastResult" />
                </div>
                <div v-show="state.activeTab === 'chart'" class="p-8">
                    <ChartView
                        :data="state.lastResult"
                        :active="state.activeTab === 'chart'"
                    />
                </div>
            </div>
        </div>
    </div>
</template>
