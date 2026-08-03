<script setup>
import { computed, ref } from 'vue'
import InfoTooltip from './InfoTooltip.vue'

const props = defineProps({
  data: { type: Object, required: true },
})

// Absolutos y relativos son la MISMA tabla con otra presentación, así que se
// muestra una sola y se alterna. Abre en relativos: es la lectura habitual de
// una encuesta. 'abs' | 'pct'.
const mode = ref('pct')

// Vista "Año": redactado exacto de la pregunta por ola (nota al pie).
const isYear = computed(() => props.data.group_by === 'year')

// Columnas de etiqueta antes de los datos: en la vista Año hay 1 (Respuesta);
// en los demás pivotes hay 2 (id_respuesta + Respuesta).
const labelCols = computed(() => (isYear.value ? 1 : 2))

const columns = computed(() => props.data.counts.columns)

// Filas que SÓLO existen en la tabla de conteos (Promedio, Base ponderada): son
// magnitudes en unidades originales, no porcentajes. Se muestran también en modo
// relativo —formateadas como conteo— para no perder el promedio al alternar.
const statRows = computed(() => {
  const pct = new Set(props.data.percentages.rows.map((r) => r[0]))
  return props.data.counts.rows.filter((r) => !pct.has(r[0]))
})

const statLabels = computed(() => new Set(statRows.value.map((r) => r[0])))

// Filas a pintar. En 'abs' los estadísticos ya vienen dentro de counts.rows, así
// que se marcan igual en ambos modos (mismo formato y mismo estilo de fila).
const displayRows = computed(() => {
  const base =
    mode.value === 'abs' ? props.data.counts.rows : props.data.percentages.rows
  const out = base.map((cells) => ({
    cells,
    stat: statLabels.value.has(cells[0]),
  }))
  if (mode.value === 'pct') {
    for (const cells of statRows.value) out.push({ cells, stat: true })
  }
  return out
})

// Etiquetas distintas que tuvo esta opción a lo largo de los años (dedup, en
// orden de aparición). p. ej. ["Hombre", "Masculino"].
function distinctLabels(entry) {
  const seen = []
  for (const v of Object.values(entry.years)) {
    if (v && v.label && !seen.includes(v.label)) seen.push(v.label)
  }
  return seen
}
// Tooltip: solo los distintos tipos de respuesta, p. ej. "Hombre / Masculino".
function rawTooltip(entry) {
  return distinctLabels(entry).join(' / ')
}
// Marcador en la columna Respuesta (col 0 en la vista Año), solo cuando la
// etiqueta varió entre años (>1 tipo de respuesta). year_option_map está
// alineado EN ORDEN con las filas de datos (Total al final).
function diffEntry(ri, row, ci) {
  if (!isYear.value || ci !== 0 || isTotalRow(row)) return null
  const e = (props.data.year_option_map ?? [])[ri]
  return e && distinctLabels(e).length > 1 ? e : null
}

function isNumeric(cell, ci) {
  return ci >= labelCols.value
}

function isTotalRow(row) {
  return row[0] === 'Total'
}

function formatCount(cell, row, ci) {
  if (ci < labelCols.value) return cell ?? ''
  if (typeof cell === 'number') return cell.toLocaleString('en-US')
  if (row[0] === 'Promedio') return cell ?? ''
  return cell === '' || cell == null ? '0' : cell
}

function formatPercent(cell, ci) {
  if (ci < labelCols.value) return cell ?? ''
  if (cell === '' || cell == null) return ''
  return `${cell}%`
}

// Los estadísticos se formatean siempre como conteo, aunque estemos en relativo.
function formatCell(cell, row, ci, stat) {
  return mode.value === 'abs' || stat
    ? formatCount(cell, row, ci)
    : formatPercent(cell, ci)
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-3 px-2 gap-4">
      <h3 class="text-sm font-bold text-[#1e293b]">Resultados</h3>
      <div class="flex gap-1 bg-[#f1f5f9] p-1 rounded-2xl shrink-0">
        <button
          @click="mode = 'abs'"
          class="px-3 py-1 rounded-xl text-xs font-bold transition-colors"
          :class="
            mode === 'abs'
              ? 'bg-white text-[#0d9488] shadow-sm'
              : 'text-[#94a3b8] hover:text-[#64748b]'
          "
        >
          Absolutos
        </button>
        <button
          @click="mode = 'pct'"
          class="px-3 py-1 rounded-xl text-xs font-bold transition-colors"
          :class="
            mode === 'pct'
              ? 'bg-white text-[#0d9488] shadow-sm'
              : 'text-[#94a3b8] hover:text-[#64748b]'
          "
        >
          Relativos
        </button>
      </div>
    </div>

    <div class="overflow-x-auto border border-[#e2e8f0] rounded-lg">
      <table class="w-full">
        <thead>
          <tr class="bg-[rgba(248,250,252,0.5)]">
            <th
              v-for="c in columns"
              :key="c"
              class="px-6 py-4 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
            >
              {{ c }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="({ cells, stat }, ri) in displayRows"
            :key="ri"
            :class="
              isTotalRow(cells) || stat
                ? 'bg-[rgba(248,250,252,0.3)] border-t-2 border-[#e2e8f0]'
                : 'border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors'
            "
          >
            <td
              v-for="(cell, ci) in cells"
              :key="ci"
              class="px-6 py-4 text-sm whitespace-nowrap"
              :class="
                isTotalRow(cells)
                  ? 'font-bold text-[#0f172a]'
                  : isNumeric(cell, ci)
                    ? 'font-mono text-[#475569]'
                    : 'text-[#1e293b] font-medium'
              "
            >
              <span class="inline-flex items-center gap-1.5">
                <span>{{ formatCell(cell, cells, ci, stat) }}</span>
                <InfoTooltip
                  v-if="diffEntry(ri, cells, ci)"
                  :text="rawTooltip(diffEntry(ri, cells, ci))"
                />
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- "Cómo se preguntó cada año" vive en ResultsPanel, debajo de la tarjeta:
       es metadata de la consulta, no de la tabla, y así también se ve en la
       pestaña Gráfica. -->
</template>
