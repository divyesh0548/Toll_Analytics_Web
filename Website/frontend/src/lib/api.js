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
    error.data = data
    if (data?.needs_scrape_mode) error.needs_scrape_mode = true
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

export async function downloadPlazaAuditExceptions(
  plazaIdentifier,
  { year, month, metricsSource = 'manual' } = {},
) {
  const params = new URLSearchParams()
  if (year != null && year !== '') params.set('year', String(year))
  if (month != null && month !== '') params.set('month', String(month))
  if (metricsSource) params.set('metrics_source', String(metricsSource))
  const token = getToken()
  const response = await fetch(
    `${API_BASE}/api/plazas/${plazaIdentifier}/audit-exceptions/export?${params.toString()}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  )
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const error = new Error(data.error || `Request failed (${response.status})`)
    error.status = response.status
    throw error
  }
  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/)
  const filename = match?.[1] || 'audit-exceptions.xlsx'
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function getPlazaAuditExceptions(
  plazaIdentifier,
  { year, month, metricsSource = 'manual' } = {},
) {
  const params = new URLSearchParams()
  if (year != null && year !== '') params.set('year', String(year))
  if (month != null && month !== '') params.set('month', String(month))
  if (metricsSource) params.set('metrics_source', String(metricsSource))
  const query = params.toString()
  return request(
    `/api/plazas/${plazaIdentifier}/audit-exceptions${query ? `?${query}` : ''}`,
  )
}

export function getExceptionPipelineCatalog() {
  return request('/api/exception-pipeline/catalog')
}

export function getExceptionPipelinePeriod({ plazaIdentifier, year, month }) {
  const params = new URLSearchParams({
    plaza_identifier: plazaIdentifier,
    year: String(year),
    month: String(month),
  })
  return request(`/api/exception-pipeline/period?${params.toString()}`)
}

export async function uploadExceptionPipelineInput({
  plazaIdentifier,
  year,
  month,
  slot,
  file,
}) {
  const fileName = file?.name || 'upload.bin'
  const contentType = file?.type || 'application/octet-stream'
  const fileSize = Number(file?.size || 0)
  if (!fileSize) {
    const error = new Error('Uploaded file is empty')
    error.status = 400
    throw error
  }
  const signed = await request('/api/exception-pipeline/inputs/presign', {
    method: 'POST',
    body: JSON.stringify({
      plaza_identifier: plazaIdentifier,
      year,
      month,
      slot,
      file_name: fileName,
      content_type: contentType,
      file_size_bytes: fileSize,
    }),
  })
  const putHeaders = { 'Content-Type': signed.content_type || contentType }
  const putResponse = await fetch(signed.upload_url, {
    method: 'PUT',
    headers: putHeaders,
    body: file,
  })
  if (!putResponse.ok) {
    const detail = await putResponse.text().catch(() => '')
    const error = new Error(
      detail?.trim()
        ? `S3 upload failed (${putResponse.status}): ${detail.trim().slice(0, 200)}`
        : `S3 upload failed (${putResponse.status})`,
    )
    error.status = putResponse.status
    throw error
  }
  return request('/api/exception-pipeline/inputs/complete', {
    method: 'POST',
    body: JSON.stringify({
      plaza_identifier: plazaIdentifier,
      year,
      month,
      slot,
      s3_key: signed.s3_key,
      file_url: signed.file_url,
      original_file_name: signed.original_file_name || fileName,
      file_size_bytes: fileSize,
      content_type: signed.content_type || contentType,
    }),
  })
}

export function deleteExceptionPipelineInput(fileId) {
  return request(`/api/exception-pipeline/inputs/${fileId}`, { method: 'DELETE' })
}

export function createExceptionPipelineBatch(payload) {
  return request('/api/exception-pipeline/batches', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function startExceptionPipelineBatch(batchUuid, { runAnalytics = true } = {}) {
  return request(`/api/exception-pipeline/batches/${batchUuid}/start`, {
    method: 'POST',
    body: JSON.stringify({ run_analytics: Boolean(runAnalytics) }),
  })
}

export function stopExceptionPipelineBatch(batchUuid) {
  return request(`/api/exception-pipeline/batches/${batchUuid}/stop`, {
    method: 'POST',
  })
}

export function resumeInterruptedPipelineBatch(batchUuid) {
  return request(`/api/exception-pipeline/batches/${batchUuid}/resume-interrupted`, {
    method: 'POST',
  })
}

export function getExceptionPipelineBatch(batchUuid) {
  return request(`/api/exception-pipeline/batches/${batchUuid}`)
}

export function listExceptionPipelineBatches({ plazaIdentifier } = {}) {
  const params = new URLSearchParams()
  if (plazaIdentifier) params.set('plaza_identifier', plazaIdentifier)
  const q = params.toString()
  return request(`/api/exception-pipeline/batches${q ? `?${q}` : ''}`)
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

export function listExceptionPrograms() {
  return request('/api/exception-jobs/programs')
}

export function listAnalyticsUploadPrograms() {
  return request('/api/analytics/upload-programs')
}

export function listExceptionJobs(plazaIdentifier, programCode) {
  const params = new URLSearchParams()
  if (plazaIdentifier) params.set('plaza_identifier', plazaIdentifier)
  if (programCode) params.set('program_code', programCode)
  const query = params.toString() ? `?${params.toString()}` : ''
  return request(`/api/exception-jobs${query}`)
}

export function getAnnexureServerDefaults(pipelinePlazaKey) {
  return request(
    `/api/exception-jobs/annexure-defaults?pipeline_plaza_key=${encodeURIComponent(
      pipelinePlazaKey || '',
    )}`,
  )
}

export function listStagingInvalidFiles(plazaIdentifier, exceptionTypeId = 5) {
  const params = new URLSearchParams()
  params.set('plaza_identifier', plazaIdentifier || '')
  params.set('exception_type_id', String(exceptionTypeId || 5))
  return request(`/api/exception-jobs/staging-invalid-files?${params.toString()}`)
}

export function attachStagingInvalidFile(jobUuid, outputFileId) {
  return request(`/api/exception-jobs/${jobUuid}/attach-staging`, {
    method: 'POST',
    body: JSON.stringify({ output_file_id: outputFileId }),
  })
}

export function listExemptFinalFiles(plazaIdentifier, limit = 20) {
  const params = new URLSearchParams()
  params.set('plaza_identifier', plazaIdentifier || '')
  params.set('limit', String(limit || 20))
  return request(`/api/exception-jobs/exempt-final-files?${params.toString()}`)
}

export function attachExemptFinalFile(jobUuid, monthlyInputId) {
  return request(`/api/exception-jobs/${jobUuid}/attach-exempt-final`, {
    method: 'POST',
    body: JSON.stringify({ monthly_input_id: monthlyInputId }),
  })
}

export function getExceptionJob(jobUuid) {
  return request(`/api/exception-jobs/${jobUuid}`)
}

export function createExceptionJob(payload) {
  return request('/api/exception-jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function uploadExceptionJobFile(jobUuid, slot, file) {
  const fileName = file?.name || 'upload.bin'
  const contentType = file?.type || 'application/octet-stream'
  const fileSize = Number(file?.size || 0)
  if (!fileSize) {
    const error = new Error('Uploaded file is empty')
    error.status = 400
    throw error
  }

  // 1) Ask backend for a short-lived S3 PUT URL (auth + slot checks).
  const signed = await request(`/api/exception-jobs/${jobUuid}/files/presign`, {
    method: 'POST',
    body: JSON.stringify({
      slot,
      file_name: fileName,
      content_type: contentType,
      file_size_bytes: fileSize,
    }),
  })

  // 2) Browser uploads directly to S3 (does not go through Flask).
  // Must send the exact Content-Type that was signed (see backend presign).
  const putHeaders = {}
  const signedType = signed.content_type || contentType || 'application/octet-stream'
  putHeaders['Content-Type'] = signedType
  let putResponse
  try {
    putResponse = await fetch(signed.upload_url, {
      method: 'PUT',
      headers: putHeaders,
      body: file,
    })
  } catch (err) {
    const error = new Error(
      'S3 upload blocked (network/CORS). In AWS S3 → bucket → Permissions → ' +
        'Cross-origin resource sharing (CORS), allow PUT from this page origin ' +
        '(localhost:8080 and/or your ngrok HTTPS URL). See Website/DOCKER.md § S3 CORS. ' +
        `(${err?.message || 'Failed to fetch'})`,
    )
    error.status = 0
    throw error
  }
  if (!putResponse.ok) {
    const detail = await putResponse.text().catch(() => '')
    const error = new Error(
      detail?.trim()
        ? `S3 upload failed (${putResponse.status}): ${detail.trim().slice(0, 200)}`
        : `S3 upload failed (${putResponse.status})`,
    )
    error.status = putResponse.status
    throw error
  }

  // 3) Register the object on the job after a successful PUT.
  return request(`/api/exception-jobs/${jobUuid}/files/complete`, {
    method: 'POST',
    body: JSON.stringify({
      slot,
      s3_key: signed.s3_key,
      file_url: signed.file_url,
      original_file_name: signed.original_file_name || fileName,
      file_size_bytes: fileSize,
    }),
  })
}

export function deleteExceptionJobFile(jobUuid, fileId) {
  return request(`/api/exception-jobs/${jobUuid}/files/${fileId}`, {
    method: 'DELETE',
  })
}

export function deleteExceptionJob(jobUuid) {
  return request(`/api/exception-jobs/${jobUuid}`, {
    method: 'DELETE',
  })
}

export function startExceptionJob(jobUuid, { scrapeMode } = {}) {
  const mode = String(scrapeMode || '').trim().toLowerCase()
  const body = {
    scrape_mode: mode === 'export' ? 'export' : 'live',
  }
  return request(`/api/exception-jobs/${jobUuid}/start`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function resumeInterruptedJob(jobUuid) {
  return request(`/api/exception-jobs/${jobUuid}/resume-interrupted`, {
    method: 'POST',
  })
}

export function downloadExceptionJobFile(jobUuid, fileId) {
  return request(`/api/exception-jobs/${jobUuid}/files/${fileId}/download`)
}

export function listExceptionJobOutputs(jobUuid) {
  return request(`/api/exception-jobs/${jobUuid}/outputs`)
}

export async function downloadExceptionJobOutput(jobUuid, relativePath, fileName) {
  const params = new URLSearchParams({ path: relativePath })
  const token = getToken()
  const response = await fetch(
    `${API_BASE}/api/exception-jobs/${jobUuid}/outputs/download?${params.toString()}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  )
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const error = new Error(data.error || `Request failed (${response.status})`)
    error.status = response.status
    throw error
  }
  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/)
  const filename = fileName || match?.[1] || 'output'
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function getMappingConfig() {
  return request('/api/mapping-config')
}

export function addMappingAlias(canonicalId, alias) {
  return request(`/api/mapping-config/canonicals/${canonicalId}/aliases`, {
    method: 'POST',
    body: JSON.stringify({ alias }),
  })
}

export function updateMappingAlias(aliasId, alias) {
  return request(`/api/mapping-config/aliases/${aliasId}`, {
    method: 'PATCH',
    body: JSON.stringify({ alias }),
  })
}

export function deleteMappingAlias(aliasId) {
  return request(`/api/mapping-config/aliases/${aliasId}`, {
    method: 'DELETE',
  })
}

export function addMappingListItem(domainCode, listKey, value) {
  return request(`/api/mapping-config/domains/${domainCode}/lists/${listKey}`, {
    method: 'POST',
    body: JSON.stringify({ value }),
  })
}

export function updateMappingListItem(itemId, value) {
  return request(`/api/mapping-config/list-items/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify({ value }),
  })
}

export function deleteMappingListItem(itemId) {
  return request(`/api/mapping-config/list-items/${itemId}`, {
    method: 'DELETE',
  })
}

export function updateMappingSetting(settingKey, value) {
  return request(`/api/mapping-config/settings/${settingKey}`, {
    method: 'PATCH',
    body: JSON.stringify({ value }),
  })
}

export function markExceptionJobFailed(jobUuid, reason) {
  return request(`/api/exception-jobs/${jobUuid}/mark-failed`, {
    method: 'POST',
    body: JSON.stringify(
      reason ? { reason } : { reason: 'Marked failed — process was not running.' },
    ),
  })
}
