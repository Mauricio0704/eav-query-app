import { reactive, computed } from 'vue'
import * as api from './api.js'

export const state = reactive({
  questions: [],
  attributes: [],
  recodes: [],
  presets: [],
  questionId: '',
  groupBy: 'answer',
  filters: [],
  initialOnly: true,
  appliedPreset: '',
  lastResult: null,
  activeTab: 'table',
  loading: false,
  error: null,
})

export const selectedQuestion = computed(() =>
  state.questions.find(q => q.q_id === state.questionId) || null
)

const SECTION_LABELS = {
  generales: 'Generales',
  economia_y_trabajo: 'Economía y trabajo',
  educacion: 'Educación',
  salud: 'Salud',
  seguridad: 'Seguridad',
  movilidad: 'Movilidad',
  desarrollo_urbano: 'Desarrollo urbano',
  medio_ambiente: 'Medio ambiente',
  gobierno: 'Gobierno',
  migracion_y_discriminacion: 'Migración y discriminación',
}

export function sectionLabel(key) {
  return SECTION_LABELS[key] || key
}

export const questionsBySection = computed(() => {
  const groups = new Map()
  for (const k of Object.keys(SECTION_LABELS)) groups.set(k, [])
  for (const q of state.questions) {
    const k = q.q_section || 'otros'
    if (!groups.has(k)) groups.set(k, [])
    groups.get(k).push(q)
  }
  const out = []
  for (const [k, qs] of groups) {
    if (qs.length) out.push({ key: k, label: sectionLabel(k), questions: qs })
  }
  return out
})

const attributeValueMap = computed(() => {
  const m = new Map()
  for (const a of state.attributes) {
    const inner = new Map()
    for (const v of a.values) inner.set(v.value, v.label)
    m.set(a.attribute, inner)
  }
  return m
})

export function filterValueLabel(filter) {
  const inner = attributeValueMap.value.get(filter.attribute)
  const v = filter.value
  if (Array.isArray(v)) {
    return v.map(x => inner?.get(x) ?? String(x)).join(', ')
  }
  return inner?.get(v) ?? String(v)
}

export const sqlPreview = computed(() => {
  if (state.lastResult?.sql) return state.lastResult.sql
  if (!state.questionId) return '-- Selecciona una pregunta'
  return '-- Ejecuta la consulta para ver el SQL generado'
})

export const canRun = computed(() => !!state.questionId && !state.loading)

export async function init() {
  try {
    const [qs, attrs, recodes, presets] = await Promise.all([
      api.fetchQuestions(),
      api.fetchAttributes(),
      api.fetchRecodes(),
      api.fetchPresets(),
    ])
    state.questions = qs
    state.attributes = attrs
    state.recodes = recodes
    state.presets = presets
  } catch (e) {
    state.error = 'Error conectando al servidor'
    console.error(e)
  }
}

export function applyPreset(key) {
  const p = state.presets.find(x => x.key === key)
  if (!p) {
    state.appliedPreset = ''
    return
  }
  state.groupBy = p.group_by
  state.filters = JSON.parse(JSON.stringify(p.filters || []))
  state.appliedPreset = key
}

export function clearPreset() {
  state.filters = []
  state.appliedPreset = ''
}

export function removeFilter(idx) {
  state.filters.splice(idx, 1)
  state.appliedPreset = ''
}

function buildBody() {
  return {
    question_id: state.questionId,
    filters: state.filters,
    group_by: state.groupBy,
    initial_only: state.initialOnly,
  }
}

export async function runCurrentQuery() {
  if (!state.questionId) return
  state.loading = true
  state.error = null
  try {
    state.lastResult = await api.runQuery(buildBody())
  } catch (e) {
    state.lastResult = null
    state.error = e.message
  } finally {
    state.loading = false
  }
}

export async function exportCurrentCSV() {
  if (!state.lastResult) return
  const blob = await api.exportCSV(buildBody())
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `encuesta_p${state.questionId}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
