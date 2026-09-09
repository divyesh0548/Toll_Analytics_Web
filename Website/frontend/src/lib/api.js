const API_BASE = import.meta.env.VITE_API_URL || ''

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`)
  }
  return data
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
