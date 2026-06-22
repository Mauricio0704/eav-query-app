const API = '/api'

export async function fetchQuestions() {
  const res = await fetch(`${API}/questions`)
  if (!res.ok) throw new Error('Error al cargar preguntas')
  return res.json()
}

export async function fetchAttributes() {
  const res = await fetch(`${API}/attributes`)
  if (!res.ok) throw new Error('Error al cargar atributos')
  return res.json()
}

export async function fetchRecodes() {
  const res = await fetch(`${API}/recodes`)
  if (!res.ok) throw new Error('Error al cargar recodes')
  return res.json()
}

export async function fetchPresets() {
  const res = await fetch(`${API}/presets`)
  if (!res.ok) throw new Error('Error al cargar presets')
  return res.json()
}

export async function fetchCities() {
  const res = await fetch(`${API}/cities`)
  if (!res.ok) throw new Error('Error al cargar ciudades')
  return res.json()
}

export async function runQuery(body) {
  const res = await fetch(`${API}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export async function exportCSV(body) {
  const res = await fetch(`${API}/query/csv`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Error al exportar CSV')
  return res.blob()
}

export async function chat(body) {
  const res = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}
