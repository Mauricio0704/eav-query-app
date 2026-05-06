<script setup>
import { computed } from "vue";
import { Table2, BarChart3, Database } from "lucide-vue-next";
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
            <div class="flex-1 overflow-auto p-8">
                <div class="max-w-225 mx-auto">
                    <div class="grid grid-cols-2 gap-6 mb-8">
                        <div
                            class="bg-white rounded-lg border border-[#e2e8f0] p-6"
                        >
                            <div class="flex items-start gap-4">
                                <div
                                    class="bg-[#0d9488]/10 rounded-lg p-3 shrink-0"
                                >
                                    <svg
                                        class="size-6 text-[#0d9488]"
                                        fill="none"
                                        viewBox="0 0 24 24"
                                        stroke="currentColor"
                                    >
                                        <path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                                        />
                                    </svg>
                                </div>
                                <div>
                                    <h3
                                        class="font-semibold text-[#1e293b] mb-2"
                                    >
                                        Sobre los Datos
                                    </h3>
                                    <p
                                        class="text-sm text-[#64748b] leading-relaxed mb-3"
                                    >
                                        Los datos provienen de la encuesta de
                                        percepción ciudadana realizada por
                                        <span
                                            class="font-medium text-[#0d9488]"
                                        >
                                            Cómo Vamos Nuevo León</span
                                        >.
                                    </p>
                                    <p class="text-xs text-[#64748b]">
                                        Edición 2025: Datos recolectados de
                                        Agosto 2025 - Septiembre 2025
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div
                            class="bg-white rounded-lg border border-[#e2e8f0] p-6"
                        >
                            <div class="flex items-start gap-4">
                                <div
                                    class="bg-[#0d9488]/10 rounded-lg p-3 shrink-0"
                                >
                                    <svg
                                        class="size-6 text-[#0d9488]"
                                        fill="none"
                                        viewBox="0 0 24 24"
                                        stroke="currentColor"
                                    >
                                        <path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"
                                        />
                                    </svg>
                                </div>
                                <div>
                                    <h3
                                        class="font-semibold text-[#1e293b] mb-2"
                                    >
                                        Metodología
                                    </h3>
                                    <p
                                        class="text-sm text-[#64748b] leading-relaxed mb-3"
                                    >
                                        Encuestas aplicadas mediante metodología
                                        probabilística con muestreo
                                        estratificado por nivel socioeconómico,
                                        edad y zona geográfica.
                                    </p>
                                    <ul
                                        class="text-xs text-[#64748b] space-y-1"
                                    >
                                        <li>
                                            • Tamaño de muestra: 4,955
                                            respondientes
                                        </li>
                                        <li>• Margen de error: ±2.5%</li>
                                        <li>• Nivel de confianza: 95%</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div
                        class="bg-linear-to-r from-[#0d9488] to-[#14b8a6] rounded-lg p-8 text-white"
                    >
                        <div class="flex items-start justify-between">
                            <div class="flex-1">
                                <h3
                                    class="font-['Manrope'] font-bold text-xl mb-2"
                                >
                                    Acceso a Base de Datos Completa
                                </h3>
                                <p class="text-white/90 mb-4 max-w-150">
                                    ¿Necesitas acceso a los datos en bruto o
                                    realizar análisis personalizados? Aquí
                                    puedes descargar la base de datos.
                                </p>
                                <div class="flex gap-3 justify-center">
                                    <a
                                        href="https://drive.google.com/drive/folders/1_Ksr-u7sE1SrwrEGRbYUG1Pe_8yEmLqo?usp=sharing"
                                        target="_blank"
                                    >
                                        <button
                                            class="bg-white text-[#0d9488] px-4 py-2 rounded-lg font-medium hover:bg-white/90 hover:cursor-pointer transition-colors text-sm"
                                        >
                                            Descargar BD
                                        </button>
                                    </a>
                                </div>
                            </div>
                            <div class="hidden lg:block">
                                <svg
                                    class="size-32 opacity-20"
                                    fill="none"
                                    viewBox="0 0 24 24"
                                    stroke="currentColor"
                                >
                                    <path
                                        stroke-linecap="round"
                                        stroke-linejoin="round"
                                        stroke-width="1"
                                        d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
                                    />
                                </svg>
                            </div>
                        </div>
                    </div>

                    <div
                        class="mt-8 bg-[#f8fafc] rounded-lg p-6 border border-[#e2e8f0]"
                    >
                        <h3
                            class="font-semibold text-[#1e293b] mb-3 flex items-center gap-2"
                        >
                            <svg
                                class="size-5 text-[#0d9488]"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                            >
                                <path
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    stroke-width="2"
                                    d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                                />
                            </svg>
                            ¿Cómo usar esta herramienta?
                        </h3>
                        <ol class="space-y-2 text-sm text-[#64748b]">
                            <li class="flex gap-3">
                                <span class="font-bold text-[#0d9488] shrink-0"
                                    >1.</span
                                >
                                <span
                                    >Selecciona una pregunta de la encuesta en
                                    el panel izquierdo</span
                                >
                            </li>
                            <li class="flex gap-3">
                                <span class="font-bold text-[#0d9488] shrink-0"
                                    >2.</span
                                >
                                <span
                                    >Elige cómo agrupar los resultados (por
                                    edad, zona, nivel socioeconómico,
                                    etc.)</span
                                >
                            </li>
                            <li class="flex gap-3">
                                <span class="font-bold text-[#0d9488] shrink-0"
                                    >3.</span
                                >
                                <span
                                    >Haz clic en "Ejecutar consulta" para ver
                                    los resultados</span
                                >
                            </li>
                            <li class="flex gap-3">
                                <span class="font-bold text-[#0d9488] shrink-0"
                                    >4.</span
                                >
                                <span
                                    >Visualiza los datos en formato de tabla o
                                    gráfica y descarga en CSV si lo
                                    necesitas</span
                                >
                            </li>
                        </ol>
                    </div>
                </div>
            </div>
        </div>

        <!-- Results -->
        <div v-else class="max-w-7xl mx-auto space-y-8">
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
                            {{ totalRespondents }} Respondientes
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

                <div v-show="state.activeTab === 'table'" class="p-6 space-y-8">
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
