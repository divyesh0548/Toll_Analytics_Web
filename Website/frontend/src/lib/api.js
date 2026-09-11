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

  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
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

export function getPortfolioVolume() {
  return request('/api/analytics/portfolio/volume')
}
