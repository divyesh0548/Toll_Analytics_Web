/** Max visible category labels on any chart X-axis. */
export const MAX_X_AXIS_LABELS = 60

/** Rotate labels diagonally when more than this many are shown. */
export const DIAGONAL_X_AXIS_LABELS = 30

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
