const API_BASE = import.meta.env.VITE_API_URL || ''
const TOKEN_KEY = 'toll_auth_token'
const ROLE_KEY = 'toll_user_role'
const WRITE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const VIEWER_WRITE_ERROR = 'Account is limited to read-only access'
const VIEWER_WRITE_ALLOWLIST = new Set(['/api/auth/login', '/api/auth/change-password'])

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  clearUserRole()
}

export function getUserRole() {
  return localStorage.getItem(ROLE_KEY)
}

export function setUserRole(role) {
  if (role) localStorage.setItem(ROLE_KEY, role)
  else clearUserRole()
}

export function clearUserRole() {
  localStorage.removeItem(ROLE_KEY)
}

async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  if (
    WRITE_METHODS.has(method) &&
    !VIEWER_WRITE_ALLOWLIST.has(path) &&
    getUserRole() === 'viewer'
  ) {
    const error = new Error(VIEWER_WRITE_ERROR)
    error.status = 403
    throw error
  }

  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  const headers = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers || {}),
  }
  if (isFormData) {
    delete headers['Content-Type']
  }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status})`)
    error.status = response.status
    throw error
  }
  return data
}

export function login(email, password) {
  return request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function changePassword(payload) {
  return request('/api/auth/change-password', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchMe() {
  return request('/api/auth/me')
}

export function listUsers() {
  return request('/api/auth/users')
}

export function createUser(payload) {
  return request('/api/auth/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listCompanies() {
  return request('/api/companies')
}

export function getCompany(companyIdentifier) {
  return request(`/api/companies/${companyIdentifier}`)
}

export function createCompany(payload) {
  return request('/api/companies', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateCompany(companyIdentifier, payload) {
  return request(`/api/companies/${companyIdentifier}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function listSpvs(companyIdentifier) {
  const query = companyIdentifier
    ? `?company_identifier=${encodeURIComponent(companyIdentifier)}`
    : ''
  return request(`/api/spvs${query}`)
}

export function createSpv(payload) {
  return request('/api/spvs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getSpv(spvIdentifier) {
  return request(`/api/spvs/${spvIdentifier}`)
}

export function updateSpv(spvIdentifier, payload) {
  return request(`/api/spvs/${spvIdentifier}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function listPlazas(spvIdentifier) {
  const query = spvIdentifier
    ? `?spv_identifier=${encodeURIComponent(spvIdentifier)}`
    : ''
  return request(`/api/plazas${query}`)
}

export function createPlaza(payload) {
  return request('/api/plazas', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getPlaza(plazaIdentifier) {
  return request(`/api/plazas/${plazaIdentifier}`)
}

export function updatePlaza(plazaIdentifier, payload) {
  return request(`/api/plazas/${plazaIdentifier}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function getPlazaNumbers(plazaIdentifier, period = 'mtd', range = {}) {
  const params = new URLSearchParams()
  params.set('period', period)
  if (range?.start) params.set('start', range.start)
  if (range?.end) params.set('end', range.end)
  return request(`/api/analytics/plazas/${plazaIdentifier}/numbers?${params.toString()}`)
}

export function getPlazaAuditExceptions(plazaIdentifier, { year, month } = {}) {
  const params = new URLSearchParams()
  if (year != null && year !== '') params.set('year', String(year))
  if (month != null && month !== '') params.set('month', String(month))
  const query = params.toString()
  return request(
    `/api/plazas/${plazaIdentifier}/audit-exceptions${query ? `?${query}` : ''}`,
  )
}

export function getPlazaCalendarEvents(plazaIdentifier, { start, end, eventType } = {}) {
  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)
  if (eventType) params.set('event_type', eventType)
  const query = params.toString()
  return request(
    `/api/plazas/${plazaIdentifier}/calendar-events${query ? `?${query}` : ''}`,
  )
}

export function createPlazaCalendarEvent(plazaIdentifier, payload) {
  return request(`/api/plazas/${plazaIdentifier}/calendar-events`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updatePlazaCalendarEvent(plazaIdentifier, eventId, payload) {
  return request(`/api/plazas/${plazaIdentifier}/calendar-events/${eventId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deletePlazaCalendarEvent(plazaIdentifier, eventId) {
  return request(`/api/plazas/${plazaIdentifier}/calendar-events/${eventId}`, {
    method: 'DELETE',
  })
}

export function uploadPlazaCalendarEvents(plazaIdentifier, file) {
  const body = new FormData()
  body.append('file', file)
  return request(`/api/plazas/${plazaIdentifier}/calendar-events/upload`, {
    method: 'POST',
    body,
  })
}

export function getPortfolioVolume() {
  return request('/api/analytics/portfolio/volume')
}

export function getPortfolioRollup() {
  return request('/api/analytics/portfolio/rollup')
}
