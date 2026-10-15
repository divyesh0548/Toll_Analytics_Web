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

const WEEKDAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

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

/**
 * Day tick with weekday — e.g. "2 Mon".
 * Month belongs on the under-axis group band, not on this label.
 */
export function dayWeekdayLabel(iso) {
  const text = normalizeIsoDate(iso)
  if (!text) return String(iso || '')
  const d = new Date(`${text}T00:00:00`)
  if (Number.isNaN(d.getTime())) return text
  // JS getDay(): Sun=0 … Sat=6 → Mon-first index
  const weekday = WEEKDAY_SHORT[(d.getDay() + 6) % 7]
  return `${d.getDate()} ${weekday}`
}

/** @deprecated Prefer dayWeekdayLabel — kept for any leftover imports. */
export function dayMonthLabel(iso) {
  return dayWeekdayLabel(iso)
}

const WEEKDAY_ALT = WEEKDAY_SHORT.join('|')
const LEGACY_DAY_LABEL_RE = new RegExp(
  `^(${WEEKDAY_ALT})\\s+(\\d{1,2})(?:\\s+(.+))?$`,
  'i',
)

/**
 * Normalize a trend tick to "2 Mon" / "2 Mon 14:00".
 * Prefers ISO date when provided; also rewrites legacy "Mon 2" labels.
 */
export function formatTrendAxisLabel(label, iso = null) {
  const raw = String(label || '').trim()
  const isoText = normalizeIsoDate(iso)
  let hourSuffix = ''

  if (isoText) {
    const fromIso = dayWeekdayLabel(isoText)
    if (raw) {
      const legacy = raw.match(LEGACY_DAY_LABEL_RE)
      if (legacy?.[3]) hourSuffix = ` ${legacy[3].trim()}`
      else {
        // "2 Mon 14:00" or bare trailing hour token
        const already = raw.match(
          new RegExp(`^\\d{1,2}\\s+(${WEEKDAY_ALT})(?:\\s+(.+))?$`, 'i'),
        )
        if (already?.[2]) hourSuffix = ` ${already[2].trim()}`
        else if (/^\d{1,2}(?::\d{2})?$/.test(raw)) hourSuffix = ` ${raw}`
      }
    }
    return `${fromIso}${hourSuffix}`
  }

  const legacy = raw.match(LEGACY_DAY_LABEL_RE)
  if (legacy) {
    const rest = legacy[3] ? ` ${legacy[3].trim()}` : ''
    return `${legacy[2]} ${legacy[1]}${rest}`
  }
  return raw
}

/**
 * Build day-axis categories aligned 1:1 with points.
 * Uses ISO dates when present; otherwise rewrites legacy weekday-first labels.
 */
export function trendAxisCategories(isoDates, fallbackLabels = []) {
  const dates = Array.isArray(isoDates) ? isoDates : []
  const labels = Array.isArray(fallbackLabels) ? fallbackLabels : []
  const n = Math.max(dates.length, labels.length)
  const out = []
  for (let i = 0; i < n; i += 1) {
    out.push(formatTrendAxisLabel(labels[i], dates[i]))
  }
  return out
}

/** True when ISO dates cover more than one calendar month. */
export function spansMultipleMonths(isoDates) {
  return uniqueMonthCount(isoDates) > 1
}

/**
 * Apex `xaxis.group` bands when the series spans more than one calendar month.
 * Draws a second row under the axis with month names spanning that month's dates.
 * Hidden for single-month ranges. `isoDates` must align 1:1 with categories (YYYY-MM-DD).
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

  // Single calendar month — no under-axis month band.
  if (groups.length <= 1) return undefined

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
 * Revenue display unit for charts/KPIs.
 * Site-wide: always show revenue in ₹ Lakh (transaction counts stay raw).
 */
export function resolveRevenueScale(_values) {
  return {
    divisor: LAC,
    unitKey: 'lac',
    axisTitle: 'Revenue (₹ Lakh)',
    shortUnit: 'Lakh',
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

/** Absolute rupees (for small per-txn figures like ARPT — not revenue totals). */
export function formatRupees(value, { digits = 0 } = {}) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `₹${Number(value).toLocaleString('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })}`
}

/** Revenue totals in ₹ Lakh (site-wide). Pass absolute rupees. */
export function formatMoneyCompact(value, { digits = 2 } = {}) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value) / LAC
  return `${n.toLocaleString('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })} Lakh`
}

/** Alias used by tables — same as formatMoneyCompact (always Lakh). */
export function formatMoney(value, { digits = 2 } = {}) {
  return formatMoneyCompact(value, { digits })
}
