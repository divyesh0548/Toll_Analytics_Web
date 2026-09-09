const API_BASE = import.meta.env.VITE_API_URL || ''
const TOKEN_KEY = 'toll_auth_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

async function request(path, options = {}) {
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
