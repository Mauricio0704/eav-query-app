import { reactive, computed } from 'vue'
import * as api from './api.js'

export const state = reactive({
  questions: [],
  attributes: [],
  questionId: '',
  groupBy: 'answer',
  lastResult: null,
  activeTab: 'table',
  loading: false,
  error: null,
})

export const selectedQuestion = computed(() =>
  state.questions.find(q => q.q_id === state.questionId) || null
)

export const sqlPreview = computed(() => {
  if (!state.questionId) return '-- Selecciona una pregunta'
  const groupExpr = state.groupBy === 'answer'
    ? 'o.option_label'
    : state.groupBy === 'city_id'
      ? 'r.city_id'
      : `(SELECT COALESCE(o2.option_label, rg.value::TEXT)\n      FROM respondent_attributes rg\n      LEFT JOIN options o2 ON o2.question_id = rg.question_id AND o2.option_id = rg.value\n      WHERE rg.respondent_id = r.respondent_id AND rg.attribute = '${state.groupBy}' LIMIT 1)`

  return `SELECT ${groupExpr} AS grupo,\n  o.option_label AS respuesta,\n  COUNT(*) AS total\nFROM answers a\nJOIN responses r ON r.respondent_id = a.respondent_id\nLEFT JOIN options o ON o.question_id = a.question_id AND o.option_id = a.option_id\nWHERE a.question_id = '${state.questionId}'\nGROUP BY grupo, respuesta\nORDER BY grupo, total DESC`
})

export const canRun = computed(() => !!state.questionId && !state.loading)

export async function init() {
  try {
    const [qs, attrs] = await Promise.all([
      api.fetchQuestions(),
      api.fetchAttributes(),
    ])
    state.questions = qs
    state.attributes = attrs
  } catch (e) {
    state.error = 'Error conectando al servidor'
    console.error(e)
  }
}

function buildBody() {
  return {
    question_id: state.questionId,
    filters: [],
    group_by: state.groupBy,
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
