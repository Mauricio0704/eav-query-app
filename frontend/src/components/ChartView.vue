<script setup>
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

const props = defineProps({
    data: { type: Object, required: true },
    active: { type: Boolean, default: false },
})

const canvasEl = ref(null)
const pieCanvases = ref([])
let chartInstance = null
let pieInstances = []

function setPieRef(el, i) {
    if (el) pieCanvases.value[i] = el
}

const FLAT_COLORS = ['#28c19b', '#7e34c3', '#ffba00', '#fb7e50', '#1f9778', '#5d2691', '#cc9500']
const PIVOT_COLORS = [
    '#28c19b', '#7e34c3', '#ffba00', '#fb7e50', '#1f9778', '#5d2691', '#cc9500',
    '#cc6540', '#5feaba', '#ad6ce0', '#ffd266', '#fda58a', '#7fdcc3', '#c094e0',
]

const pieGroupLabels = computed(() => {
    if (!props.data || props.data.format !== 'pivot') return []
    const cols = props.data.percentages?.columns || []
    return cols.slice(2, -1)
})

function destroy() {
    if (chartInstance) {
        chartInstance.destroy()
        chartInstance = null
    }
    for (const c of pieInstances) c.destroy()
    pieInstances = []
}

function buildFlat(data) {
    // Both shapes chart as a distribution (one bar per row): categorical
    // [id, label, conteo, %] and numeric [valor, conteo, %]. The % is always the
    // LAST column; the readable x label is the value (numeric → col 0) or the
    // option label (categorical → col 1).
    const isNumerica = data.question.q_type === 'numerica'
    const labelIdx = isNumerica ? 0 : 1
    return {
        type: 'bar',
        data: {
            labels: data.rows.map(r => r[labelIdx]),
            datasets: [{
                label: '%',
                data: data.rows.map(r => r[r.length - 1]),
                backgroundColor: FLAT_COLORS.map(c => c + 'CC'),
                borderColor: FLAT_COLORS,
                borderWidth: 1,
                borderRadius: 3,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { font: { family: 'DM Sans', size: 11 } } },
                y: {
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: { font: { family: 'DM Sans', size: 11 }, callback: v => v + '%' },
                },
            },
        },
    }
}

function buildPivot(data) {
    const cols = data.percentages.columns
    const rows = data.percentages.rows.filter(r => r[0] !== 'Total')
    const groupLabels = cols.slice(2, -1)
    const groupRange = groupLabels.map((_, i) => i + 2)

    const datasets = rows.map((row, ri) => {
        const label = (row[1] !== '' && row[1] != null) ? String(row[1]) : String(row[0])
        return {
            label,
            data: groupRange.map(i => Number(row[i]) || 0),
            backgroundColor: PIVOT_COLORS[ri % PIVOT_COLORS.length] + 'CC',
            borderColor: PIVOT_COLORS[ri % PIVOT_COLORS.length],
            borderWidth: 1,
        }
    })

    return {
        type: 'bar',
        data: { labels: groupLabels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { font: { family: 'DM Sans', size: 11 }, boxWidth: 12 } },
                tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y}%` } },
            },
            scales: {
                x: {
                    stacked: true,
                    grid: { display: false },
                    ticks: { font: { family: 'DM Sans', size: 10 }, autoSkip: false, maxRotation: 60, minRotation: 30 },
                },
                y: {
                    stacked: true,
                    max: 100,
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: { font: { family: 'DM Sans', size: 11 }, callback: v => v + '%' },
                },
            },
        },
    }
}

function buildPie(data, groupIdx) {
    const colIdx = groupIdx + 2
    const rows = data.percentages.rows.filter(r => r[0] !== 'Total')
    const labels = []
    const values = []
    const bg = []
    const bd = []
    rows.forEach((row, ri) => {
        const v = Number(row[colIdx]) || 0
        if (v <= 0) return
        const label = (row[1] !== '' && row[1] != null) ? String(row[1]) : String(row[0])
        labels.push(label)
        values.push(v)
        bg.push(PIVOT_COLORS[ri % PIVOT_COLORS.length] + 'CC')
        bd.push(PIVOT_COLORS[ri % PIVOT_COLORS.length])
    })
    return {
        type: 'pie',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: bg,
                borderColor: '#fff',
                borderWidth: 1,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { font: { family: 'DM Sans', size: 10 }, boxWidth: 10, padding: 8 },
                },
                tooltip: {
                    callbacks: { label: ctx => `${ctx.label}: ${ctx.parsed}%` },
                },
            },
        },
    }
}

async function render() {
    destroy()
    if (!props.data || !props.active) return
    await nextTick()
    if (canvasEl.value) {
        const config = props.data.format === 'pivot' ? buildPivot(props.data) : buildFlat(props.data)
        chartInstance = new Chart(canvasEl.value, config)
    }
    if (props.data.format === 'pivot') {
        const count = pieGroupLabels.value.length
        for (let i = 0; i < count; i++) {
            const el = pieCanvases.value[i]
            if (!el) continue
            pieInstances.push(new Chart(el, buildPie(props.data, i)))
        }
    }
}

watch(() => [props.data, props.active], render, { immediate: true })

onBeforeUnmount(destroy)
</script>

<template>
    <div class="space-y-8">
        <div class="relative h-80">
            <canvas ref="canvasEl"></canvas>
        </div>

        <div v-if="pieGroupLabels.length" class="space-y-4">
            <h3 class="font-['Manrope'] font-semibold text-sm text-[#1e293b]">
                Distribución por columna
            </h3>
            <div class="grid grid-cols-2 lg:grid-cols-3 gap-6">
                <div
                    v-for="(label, i) in pieGroupLabels"
                    :key="label"
                    class="bg-white border border-gray-300 rounded-lg p-4"
                >
                    <p class="text-xs font-bold text-[#64748b] uppercase tracking-wider mb-2 text-center">
                        {{ label }}
                    </p>
                    <div class="relative h-60">
                        <canvas :ref="el => setPieRef(el, i)"></canvas>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>
