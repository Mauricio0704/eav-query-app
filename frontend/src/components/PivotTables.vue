<script setup>
import { computed } from 'vue'
import InfoTooltip from './InfoTooltip.vue'

const props = defineProps({
  data: { type: Object, required: true },
})

// Vista "Año": redactado exacto de la pregunta por ola (nota al pie).
const isYear = computed(() => props.data.group_by === 'year')

// Columnas de etiqueta antes de los datos: en la vista Año hay 1 (Respuesta);
// en los demás pivotes hay 2 (id_respuesta + Respuesta).
const labelCols = computed(() => (isYear.value ? 1 : 2))

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
</script>

<template>
  <!-- Valores Absolutos -->
  <div>
    <h3 class="text-sm font-bold text-[#1e293b] mb-3 px-2">
      Valores Absolutos
    </h3>
    <div class="overflow-x-auto border border-[#e2e8f0] rounded-lg">
      <table class="w-full">
        <thead>
          <tr class="bg-[rgba(248,250,252,0.5)]">
            <th
              v-for="c in data.counts.columns"
              :key="c"
              class="px-6 py-4 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
            >
              {{ c }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, ri) in data.counts.rows"
            :key="ri"
            :class="
              isTotalRow(row)
                ? 'bg-[rgba(248,250,252,0.3)] border-t-2 border-[#e2e8f0]'
                : 'border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors'
            "
          >
            <td
              v-for="(cell, ci) in row"
              :key="ci"
              class="px-6 py-4 text-sm whitespace-nowrap"
              :class="
                isTotalRow(row)
                  ? 'font-bold text-[#0f172a]'
                  : isNumeric(cell, ci)
                    ? 'font-mono text-[#475569]'
                    : 'text-[#1e293b] font-medium'
              "
            >
              <span class="inline-flex items-center gap-1.5">
                <span>{{ formatCount(cell, row, ci) }}</span>
                <InfoTooltip
                  v-if="diffEntry(ri, row, ci)"
                  :text="rawTooltip(diffEntry(ri, row, ci))"
                />
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Valores Relativos -->
  <div>
    <h3 class="text-sm font-bold text-[#1e293b] mb-3 px-2">
      Valores Relativos
    </h3>
    <div class="overflow-x-auto border border-[#e2e8f0] rounded-lg">
      <table class="w-full">
        <thead>
          <tr class="bg-[rgba(248,250,252,0.5)]">
            <th
              v-for="c in data.percentages.columns"
              :key="c"
              class="px-6 py-4 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
            >
              {{ c }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, ri) in data.percentages.rows"
            :key="ri"
            :class="
              isTotalRow(row)
                ? 'bg-[rgba(248,250,252,0.3)] border-t-2 border-[#e2e8f0]'
                : 'border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors'
            "
          >
            <td
              v-for="(cell, ci) in row"
              :key="ci"
              class="px-6 py-4 text-sm whitespace-nowrap"
              :class="
                isTotalRow(row)
                  ? 'font-bold text-[#0f172a]'
                  : isNumeric(cell, ci)
                    ? 'font-mono text-[#475569]'
                    : 'text-[#1e293b] font-medium'
              "
            >
              <span class="inline-flex items-center gap-1.5">
                <span>{{ formatPercent(cell, ci) }}</span>
                <InfoTooltip
                  v-if="diffEntry(ri, row, ci)"
                  :text="rawTooltip(diffEntry(ri, row, ci))"
                />
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Nota al pie: cómo se preguntó cada año (solo vista "Año") -->
  <div
    v-if="isYear && data.year_texts?.length"
    class="border border-[#e2e8f0] rounded-lg p-4 bg-[rgba(248,250,252,0.5)]"
  >
    <h4 class="text-xs font-bold text-[#64748b] uppercase tracking-wide mb-2">
      Cómo se preguntó cada año
    </h4>
    <ul class="space-y-1">
      <li
        v-for="t in data.year_texts"
        :key="t.year"
        class="text-sm text-[#475569] flex gap-2"
      >
        <span class="font-semibold text-[#1e293b] shrink-0">{{ t.year }}</span>
        <span
          v-if="t.q_id"
          class="shrink-0 font-mono text-xs text-[#0d9488] bg-[#f0fdfa] rounded px-1.5 py-0.5 self-start"
          >{{ t.q_id }}</span
        >
        <span>{{ t.q_text }}</span>
      </li>
    </ul>
  </div>

</template>
