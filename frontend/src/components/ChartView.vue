<script setup>
import { ref, watch, onBeforeUnmount, nextTick } from 'vue'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

const props = defineProps({
    data: { type: Object, required: true },
    active: { type: Boolean, default: false },
})

const canvasEl = ref(null)
let chartInstance = null

const FLAT_COLORS = ['#28c19b', '#7e34c3', '#ffba00', '#fb7e50', '#1f9778', '#5d2691', '#cc9500']
const PIVOT_COLORS = [
    '#28c19b', '#7e34c3', '#ffba00', '#fb7e50', '#1f9778', '#5d2691', '#cc9500',
    '#cc6540', '#5feaba', '#ad6ce0', '#ffd266', '#fda58a', '#7fdcc3', '#c094e0',
]

function destroy() {
    if (chartInstance) {
        chartInstance.destroy()
        chartInstance = null
    }
}

function buildFlat(data) {
    const isNumerica = data.question.q_type === 'numerica'
    if (isNumerica) {
        const row = data.rows[0] || []
        return {
            type: 'bar',
            data: {
                labels: ['Promedio', 'Mínimo', 'Máximo'],
                datasets: [{
                    label: data.question.q_text,
                    data: [row[2], row[3], row[4]],
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
                    y: { grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { font: { family: 'DM Sans', size: 11 } } },
                },
            },
        }
    }
    return {
        type: 'bar',
        data: {
            labels: data.rows.map(r => r[0]),
            datasets: [{
                label: '%',
                data: data.rows.map(r => r[2]),
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

async function render() {
    destroy()
    if (!props.data || !props.active) return
    await nextTick()
    if (!canvasEl.value) return
    const config = props.data.format === 'pivot' ? buildPivot(props.data) : buildFlat(props.data)
    chartInstance = new Chart(canvasEl.value, config)
}

watch(() => [props.data, props.active], render, { immediate: true })

onBeforeUnmount(destroy)
</script>

<template>
    <div class="relative h-[320px]">
        <canvas ref="canvasEl"></canvas>
    </div>
</template>
