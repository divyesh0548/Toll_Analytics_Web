/** Indian states/UTs for company registered-office dropdown. */
export const INDIAN_STATES = [
  'Andaman and Nicobar Islands',
  'Andhra Pradesh',
  'Arunachal Pradesh',
  'Assam',
  'Bihar',
  'Chandigarh',
  'Chhattisgarh',
  'Dadra and Nagar Haveli and Daman and Diu',
  'Delhi',
  'Goa',
  'Gujarat',
  'Haryana',
  'Himachal Pradesh',
  'Jammu and Kashmir',
  'Jharkhand',
  'Karnataka',
  'Kerala',
  'Ladakh',
  'Lakshadweep',
  'Madhya Pradesh',
  'Maharashtra',
  'Manipur',
  'Meghalaya',
  'Mizoram',
  'Nagaland',
  'Odisha',
  'Puducherry',
  'Punjab',
  'Rajasthan',
  'Sikkim',
  'Tamil Nadu',
  'Telangana',
  'Tripura',
  'Uttar Pradesh',
  'Uttarakhand',
  'West Bengal',
]

const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/
const GSTIN_RE = /^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$/
const CIN_RE = /^[LU][A-Z0-9]{20}$/

export function extractPanFromGstin(gstin) {
  const value = (gstin || '').trim().toUpperCase()
  if (value.length < 12) return ''
  return value.slice(2, 12)
}

export function validateGstin(gstin) {
  const value = (gstin || '').trim().toUpperCase()
  if (!value) return 'GSTIN is required'
  if (value.length !== 15) return 'GSTIN must be exactly 15 characters'
  const stateCode = Number(value.slice(0, 2))
  if (!Number.isFinite(stateCode) || stateCode < 1 || stateCode > 38) {
    return 'GSTIN state code must be between 01 and 38'
  }
  const pan = value.slice(2, 12)
  if (!PAN_RE.test(pan)) return 'GSTIN must contain a valid PAN in positions 3–12'
  if (!/^[0-9A-Z]$/.test(value[12])) return 'GSTIN entity number (13th character) is invalid'
  if (value[13] !== 'Z') return 'GSTIN 14th character must be Z'
  if (!/^[0-9A-Z]$/.test(value[14])) return 'GSTIN check digit (15th character) is invalid'
  if (!GSTIN_RE.test(value)) return 'GSTIN format is invalid'
  return ''
}

export function validatePan(pan, { required = false } = {}) {
  const value = (pan || '').trim().toUpperCase()
  if (!value) return required ? 'PAN is required' : ''
  if (value.length !== 10) return 'PAN must be exactly 10 characters'
  if (!PAN_RE.test(value)) return 'PAN format is invalid (e.g. ABCDE1234F)'
  return ''
}

export function validateCin(cin, { required = false } = {}) {
  const value = (cin || '').trim().toUpperCase()
  if (!value) return required ? 'CIN is required' : ''
  if (value.length !== 21) return 'CIN must be exactly 21 characters'
  if (!/^[LU]/.test(value)) return 'CIN must start with L (Listed) or U (Unlisted)'
  if (!CIN_RE.test(value)) return 'CIN format is invalid'
  return ''
}

export function validateEmail(email, { required = false } = {}) {
  const value = (email || '').trim()
  if (!value) return required ? 'Email is required' : ''
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return 'Enter a valid email address'
  return ''
}

export function validatePhone(phone, { required = false } = {}) {
  const value = (phone || '').trim()
  if (!value) return required ? 'Phone is required' : ''
  const digits = value.replace(/[^\d]/g, '')
  if (!/^[+]?[\d\s()-]{8,20}$/.test(value) || digits.length < 8 || digits.length > 15) {
    return 'Enter a valid phone number (8–15 digits)'
  }
  return ''
}

export function validateCompanyContacts(contacts) {
  const filled = (contacts || []).filter((c) => c.name?.trim() || c.email?.trim() || c.phone?.trim())
  if (filled.length === 0) {
    return 'Add at least one contact with an email or phone'
  }
  for (const [index, contact] of filled.entries()) {
    if (!contact.name?.trim()) {
      return `Contact ${index + 1}: name is required`
    }
    if (!contact.email?.trim() && !contact.phone?.trim()) {
      return `Contact ${index + 1}: provide at least an email or phone`
    }
    const emailError = validateEmail(contact.email)
    if (emailError) return `Contact ${index + 1}: ${emailError}`
    const phoneError = validatePhone(contact.phone)
    if (phoneError) return `Contact ${index + 1}: ${phoneError}`
  }
  return ''
}
