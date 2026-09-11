# Graph rules

Rules for ApexCharts used on the Toll Analytics website (plaza Numbers Overview, portfolio volume, and any future charts that share `src/lib/chart-axis.js`).

## Time grain (traffic trend)

| Selected range | Series grain | X-axis point meaning |
| --- | --- | --- |
| **1–2 calendar days** (inclusive) | **Hourly** | One point per hour bucket (ETL labels like `14-15`) |
| **More than 2 days** | **Daily** | One point per calendar day |

- API field: `trend_grain` is `"hour"` or `"day"`.
- Series payload remains `daily_trend` (name kept for compatibility); each point has `label`, `traffic`, optional `traffic_ly`, and for hourly also `hour`.
- Last-year comparison uses the same calendar day (and hour, when hourly) from the prior year.
- Chart title switches between **Hourly traffic** and **Daily traffic**.

## X-axis label density (max 60)

Applies to **all** category charts that use `categoryXAxis` / `thinCategoryLabels`.

1. Cap **visible** X-axis labels at **60**.
2. If there are more than 60 data points, show every **2nd** label (alternate).
3. If still more than 60 visible labels, double the step again (every 4th, then 8th, …) until ≤ 60 labels.
4. **All data points stay plotted**; only axis label text is thinned (blanked).
5. Tooltips always show the **full** category label for the hovered point.

Shared helpers: `Website/frontend/src/lib/chart-axis.js`.

## Diagonal labels (more than 30)

1. If **more than 30** labels are visible after thinning, rotate them **-45°** (`rotateAlways: true`).
2. If **30 or fewer**, keep labels horizontal.
3. Extra label height is reserved when diagonal so text is not clipped.

## Dark mode readability

1. Chart `foreColor` and axis/legend label colors use light text in dark mode (e.g. `#e5e7eb`).
2. Tooltips use Apex `theme: 'dark'` in dark mode.
3. Grid lines use a muted dark border so they do not overpower series colors.

## Portfolio volume charts

1. One area chart **per company**, aggregating **all plazas** under that company.
2. Monthly points, up to the last **5 years**.
3. Same max-60 / diagonal-when-over-30 X-axis rules as above.

## Charts currently covered

| Location | Chart | Notes |
| --- | --- | --- |
| Plaza → Numbers → Overview | Traffic trend (hour or day) | Uses `trend_grain` |
| Plaza → Numbers → Overview | MOP Mix | Few categories; helpers still applied |
| Plaza → Numbers → Overview | Vehicle class mix | Horizontal bars |
| Portfolio | Company volume | Monthly series |

## Out of scope (for this doc)

- KPI cards, tables, and lane throughput lists (not Apex time-series axes).
- Revenue / Summary Numbers tabs (placeholders; no graphs yet).
