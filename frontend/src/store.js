import { reactive, computed } from 'vue'
import * as api from './api.js'

// Tracks state of query, UI and chat history
export const state = reactive({
  questions: [],
  attributes: [],
  recodes: [],
  presets: [],
  cities: [],
  questionId: '',
  groupBy: 'answer',
  filters: [],
  initialOnly: true,
  appliedPreset: '',
  lastResult: null,
  activeTab: 'table',
  loading: false,
  error: null,
  queryMode: 'manual',
  chatMessages: [],
  chatLoading: false,
  conversations: [],
  currentConversationId: null,
})

const CHAT_STORAGE_KEY = 'eav-chat-conversations'
const MAX_CONVERSATIONS = 5

export const selectedQuestion = computed(
  () => state.questions.find((q) => q.q_id === state.questionId) || null,
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

export const questionsBySection = computed(() => {
  const groups = new Map()
  for (const section of Object.keys(SECTION_LABELS)) groups.set(section, [])
  for (const q of state.questions) {
    const section = q.q_section || 'otros'
    if (!groups.has(section)) groups.set(section, [])
    groups.get(section).push(q)
  }
  const out = []
  for (const [section, questions] of groups) {
    if (questions.length)
      out.push({
        key: section,
        label: SECTION_LABELS[section] || section,
        questions,
      })
  }
  return out
})

function questionSearch(q, block, info, sectionLabel) {
  return `${q.q_id} ${q.q_text || ''} ${block} ${info} ${sectionLabel}`.toLowerCase()
}

export const questionPicker = computed(() => {
  const sections = []
  const byId = new Map()
  const groupOf = new Map()
  let groupSeq = 0

  for (const grp of questionsBySection.value) {
    const sectionLabel = grp.label

    // How many questions share each block within this section.
    const blockCounts = new Map()
    for (const q of grp.questions) {
      const block = (q.q_block || '').trim()
      if (block) blockCounts.set(block, (blockCounts.get(block) || 0) + 1)
    }

    const entries = []
    const groupByBlock = new Map()
    for (const q of grp.questions) {
      const block = (q.q_block || '').trim()
      const info = (q.q_info || '').trim()
      const meta = {
        id: q.q_id,
        main: q.q_text || q.q_id,
        sectionLabel,
        block,
        info,
        note: block || info,
        stem: '',
        groupId: null,
        search: questionSearch(q, block, info, sectionLabel),
      }
      if (block && blockCounts.get(block) > 1) {
        let entry = groupByBlock.get(block)
        if (!entry) {
          entry = {
            type: 'group',
            groupId: `g${groupSeq++}`,
            label: block,
            facets: [],
          }
          groupByBlock.set(block, entry)
          entries.push(entry)
        }
        meta.groupId = entry.groupId
        meta.stem = block
        entry.facets.push(meta)
        groupOf.set(meta.id, entry.groupId)
      } else {
        entries.push({ type: 'q', ...meta })
      }
      byId.set(meta.id, meta)
    }

    sections.push({
      key: grp.key,
      label: sectionLabel,
      count: grp.questions.length,
      entries,
    })
  }

  return { sections, byId, groupOf, total: state.questions.length }
})

const attributeValueMap = computed(() => {
  const out = new Map()
  for (const attr of state.attributes) {
    const valueToLabel = new Map()
    for (const v of attr.values) valueToLabel.set(v.value, v.label)
    out.set(attr.attribute, valueToLabel)
  }
  return out
})

const cityNameMap = computed(() => {
  const out = new Map()
  for (const city of state.cities) out.set(city.city_id, city.name)
  return out
})

export function filterValueLabel(filter) {
  const inner =
    filter.attribute === 'city_id'
      ? cityNameMap.value
      : attributeValueMap.value.get(filter.attribute)
  const v = filter.value
  if (Array.isArray(v)) {
    return v.map((x) => inner?.get(x) ?? String(x)).join(', ')
  }
  return inner?.get(v) ?? String(v)
}

function cleanSQL(sql) {
  return sql
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l !== '')
    .join('\n')
}

export const sqlPreview = computed(() => {
  if (state.lastResult?.sql) return cleanSQL(state.lastResult.sql)
  if (!state.questionId) return '-- Selecciona una pregunta'
  return '-- Ejecuta la consulta para ver el SQL generado'
})

export const canRun = computed(() => !!state.questionId && !state.loading)

export async function init() {
  try {
    const [qs, attrs, recodes, presets, cities] = await Promise.all([
      api.fetchQuestions(),
      api.fetchAttributes(),
      api.fetchRecodes(),
      api.fetchPresets(),
      api.fetchCities(),
    ])
    state.questions = qs
    state.attributes = attrs
    state.recodes = recodes
    state.presets = presets
    state.cities = cities
    loadConversations()
  } catch (e) {
    state.error = 'Error conectando al servidor'
    console.error(e)
  }
}

export function applyPreset(key) {
  const p = state.presets.find((x) => x.key === key)
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

// Add a value to a manual filter
export function addFilter(attribute, value) {
  if (!attribute || value === '' || value == null) return
  const v = Number(value)
  const existing = state.filters.find((f) => f.attribute === attribute)
  if (existing) {
    const arr = Array.isArray(existing.value)
      ? existing.value
      : [existing.value]
    if (!arr.includes(v)) existing.value = [...arr, v]
  } else {
    state.filters.push({ attribute, value: [v] })
  }
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

export function setQueryMode(mode) {
  state.queryMode = mode
}

// ── Chat history (localStorage) ────────────────────────────────────────────

let _msgSeq = 0
function msgId() {
  return (
    (crypto.randomUUID && crypto.randomUUID()) || `m${Date.now()}_${_msgSeq++}`
  )
}

function conversationTitle(messages) {
  const firstUser = messages.find((m) => m.role === 'user')
  const t = (firstUser?.text || 'Conversación').trim()
  return t.length > 48 ? t.slice(0, 48) + '…' : t
}

function persistConversations() {
  // Keep only the most recently updated conversations.
  state.conversations.sort((a, b) => b.updatedAt - a.updatedAt)
  if (state.conversations.length > MAX_CONVERSATIONS) {
    state.conversations.splice(MAX_CONVERSATIONS)
  }
  try {
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(state.conversations))
  } catch (e) {
    console.error('No se pudo guardar el historial de chats:', e)
  }
}

export function loadConversations() {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      state.conversations = parsed
        .filter((c) => c && c.id && Array.isArray(c.messages))
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_CONVERSATIONS)
    }
  } catch (e) {
    console.error('No se pudo leer el historial de chats:', e)
  }
}

// Snapshot the active chat into the conversation list and persist it.
function syncCurrentConversation() {
  if (!state.chatMessages.length) return
  const now = Date.now()
  let conv = state.conversations.find(
    (c) => c.id === state.currentConversationId,
  )
  if (!conv) {
    conv = {
      id: (crypto.randomUUID && crypto.randomUUID()) || String(now),
      createdAt: now,
      updatedAt: now,
      title: '',
      messages: [],
    }
    state.currentConversationId = conv.id
    state.conversations.unshift(conv)
  }
  conv.messages = JSON.parse(JSON.stringify(state.chatMessages))
  conv.title = conversationTitle(state.chatMessages)
  conv.updatedAt = now
  persistConversations()
}

export function newConversation() {
  state.chatMessages = []
  state.currentConversationId = null
}

export function loadConversation(id) {
  const conv = state.conversations.find((c) => c.id === id)
  if (!conv) return
  state.currentConversationId = id
  state.chatMessages = conv.messages.map((m) => ({ ...m, id: m.id || msgId() }))
}

export function deleteConversation(id) {
  const idx = state.conversations.findIndex((c) => c.id === id)
  if (idx === -1) return
  state.conversations.splice(idx, 1)
  if (state.currentConversationId === id) newConversation()
  persistConversations()
}

export async function sendChatMessage(text) {
  const msg = (text || '').trim()
  if (!msg || state.chatLoading) return
  // History = prior turns (text only) before this new message.
  const history = state.chatMessages.map((m) => ({
    role: m.role,
    text: m.text,
  }))
  state.chatMessages.push({ id: msgId(), role: 'user', text: msg })
  syncCurrentConversation() // surface the conversation in the list right away
  state.chatLoading = true
  try {
    const res = await api.chat({ message: msg, history })
    state.chatMessages.push({
      id: msgId(),
      role: 'assistant',
      text: res.reply,
      data: res.data || null,
      toolCalls: res.tool_calls || [],
    })
  } catch (e) {
    state.chatMessages.push({
      id: msgId(),
      role: 'assistant',
      text: `Lo siento, ocurrió un error: ${e.message}`,
      error: true,
    })
  } finally {
    state.chatLoading = false
    syncCurrentConversation()
  }
}

export async function retryLastMessage() {
  if (state.chatLoading) return
  const msgs = state.chatMessages
  if (msgs.length && msgs[msgs.length - 1].role === 'assistant') msgs.pop()
  if (!msgs.length || msgs[msgs.length - 1].role !== 'user') return
  const last = msgs.pop()
  syncCurrentConversation()
  await sendChatMessage(last.text)
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
