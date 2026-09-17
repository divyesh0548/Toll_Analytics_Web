/** Max visible category labels on any chart X-axis. */
export const MAX_X_AXIS_LABELS = 60

/** Half-width charts (≈50% layout): tighter label budget. */
export const HALF_WIDTH_MAX_X_AXIS_LABELS = 30

/** Rotate labels diagonally when more than this many are shown. */
export const DIAGONAL_X_AXIS_LABELS = 30

/** Indian numbering for chart revenue axes. */
export const LAC = 100000
export const CRORE = 10000000

const MONTH_SHORT = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

/**
 * Step size for showing every Nth label so count stays ≤ maxLabels.
 * Doubles (1 → 2 → 4 → …) until ceil(pointCount / step) ≤ maxLabels.
 */
export function xAxisLabelStep(pointCount, maxLabels = MAX_X_AXIS_LABELS) {
  const n = Number(pointCount) || 0
  if (n <= maxLabels) return 1
  let step = 1
  while (Math.ceil(n / step) > maxLabels) {
    step *= 2
  }
  return step
}

/**
 * Keep all category slots (so series points stay aligned) but blank labels
 * that should be hidden. Use with tooltip.x.formatter for full labels.
 */
export function thinCategoryLabels(labels, maxLabels = MAX_X_AXIS_LABELS) {
  const list = Array.isArray(labels) ? labels : []
  const step = xAxisLabelStep(list.length, maxLabels)
  if (step <= 1) return list
  return list.map((label, index) => (index % step === 0 ? label : ''))
}

export function visibleCategoryLabelCount(labels) {
  return (Array.isArray(labels) ? labels : []).filter(
    (label) => label != null && String(label).trim() !== '',
  ).length
}

/**
 * Thinned categories + Apex xaxis.labels options.
 * Diagonal (-45°) when more than 30 labels are visible.
 */
export function categoryXAxis(
  fullLabels,
  labelStyle = {},
  maxLabels = MAX_X_AXIS_LABELS,
) {
  const categories = thinCategoryLabels(fullLabels, maxLabels)
  const shown = visibleCategoryLabelCount(categories)
  const diagonal = shown > DIAGONAL_X_AXIS_LABELS
  return {
    categories,
    labels: {
      rotate: diagonal ? -45 : 0,
      rotateAlways: diagonal,
      hideOverlappingLabels: false,
      trim: false,
      minHeight: diagonal ? 48 : undefined,
      style: labelStyle,
    },
  }
}

/** ApexCharts tooltip helper: always show the full category for a point. */
export function categoryTooltipXFormatter(fullLabels) {
  return function formatTooltipX(value, opts) {
    const index = opts?.dataPointIndex
    if (typeof index === 'number' && fullLabels[index] != null && fullLabels[index] !== '') {
      return String(fullLabels[index])
    }
    if (value != null && value !== '') return String(value)
    return fullLabels[index] != null ? String(fullLabels[index]) : ''
  }
}

function monthTitleFromIso(iso) {
  const text = String(iso || '').slice(0, 10)
  const [y, m] = text.split('-').map(Number)
  if (!y || !m) return text
  return `${MONTH_SHORT[m - 1]} ${y}`
}

export function normalizeIsoDate(value) {
  const text = String(value || '').slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : ''
}

export function uniqueMonthCount(isoDates) {
  const keys = new Set()
  for (const raw of isoDates || []) {
    const iso = normalizeIsoDate(raw)
    if (iso) keys.add(iso.slice(0, 7))
  }
  return keys.size
}

/** Day tick like "12 Jan" (used when the range spans more than 3 months). */
export function dayMonthLabel(iso) {
  const text = normalizeIsoDate(iso)
  if (!text) return String(iso || '')
  const [, m, d] = text.split('-').map(Number)
  return `${d} ${MONTH_SHORT[m - 1]}`
}

/**
 * Apex `xaxis.group` bands when the series spans more than 3 calendar months.
 * `isoDates` must align 1:1 with chart categories (YYYY-MM-DD).
 */
export function monthAxisGroups(isoDates, labelStyle = {}) {
  const dates = (isoDates || []).map(normalizeIsoDate).filter(Boolean)
  if (dates.length < 2) return undefined

  const groups = []
  let current = null
  for (const iso of dates) {
    const key = iso.slice(0, 7)
    if (!current || current.key !== key) {
      current = { key, title: monthTitleFromIso(iso), cols: 1 }
      groups.push(current)
    } else {
      current.cols += 1
    }
  }

  if (groups.length <= 3) return undefined

  return {
    style: {
      fontSize: '11px',
      fontWeight: 600,
      ...(labelStyle?.colors ? { colors: labelStyle.colors } : {}),
    },
    groups: groups.map((g) => ({ title: g.title, cols: g.cols })),
  }
}

/**
 * Pick one revenue display unit for a series (never mix lac + crore on one axis).
 * crore only when every positive value is ≥ 1 crore; otherwise lac if max ≥ 1 lac.
 */
export function resolveRevenueScale(values) {
  const nums = (values || [])
    .map((v) => Number(v))
    .filter((n) => Number.isFinite(n) && n >= 0)
  const max = nums.length ? Math.max(...nums) : 0
  const positive = nums.filter((n) => n > 0)
  const minPositive = positive.length ? Math.min(...positive) : 0

  if (max >= CRORE && minPositive >= CRORE) {
    return {
      divisor: CRORE,
      unitKey: 'crore',
      axisTitle: 'Revenue (₹ Crore)',
      shortUnit: 'Cr',
    }
  }
  if (max >= LAC) {
    return {
      divisor: LAC,
      unitKey: 'lac',
      axisTitle: 'Revenue (₹ Lakh)',
      shortUnit: 'Lakh',
    }
  }
  return {
    divisor: 1,
    unitKey: 'rupee',
    axisTitle: 'Revenue (₹)',
    shortUnit: '₹',
  }
}

export function scaleRevenueValues(values, scale) {
  const divisor = scale?.divisor || 1
  return (values || []).map((v) => {
    if (v == null || v === '') return null
    const n = Number(v)
    if (!Number.isFinite(n)) return null
    return n / divisor
  })
}

export function formatScaledRevenue(value, scale, { digits = 2 } = {}) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  if (scale?.unitKey === 'rupee') {
    return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
  }
  const formatted = n.toLocaleString('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })
  return `${formatted} ${scale.shortUnit}`
}

/** KPI / big-number formatting: ₹, Lakh, or Cr with one consistent unit. */
export function formatMoneyCompact(value, { digits = 2 } = {}) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const scale = resolveRevenueScale([n])
  return formatScaledRevenue(n / scale.divisor, scale, { digits })
}
