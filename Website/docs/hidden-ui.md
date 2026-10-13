# Hidden UI (recover later)

User-facing navigation and labels that were **hidden or renamed** without removing
routes, pages, or APIs. Direct URLs still work unless noted.

Last updated: 2026-10-13

## Feature flags (backend `.env`)

| Flag | Default | Effect |
|---|---|---|
| `SHOW_EXCEPTION_UPLOADS` | `0` / false | When `1` / `true` / `yes` / `on`, show **Exceptions** / **Exception uploads** links for `/exceptions/uploads` (navbar, portfolio, File Upload page). Exposed to the browser via `/api/auth/me` → `features.show_exception_uploads`. |

## Renamed UI (route/path unchanged)

| Where | Old label | New label | Notes |
|---|---|---|---|
| Navbar | Exception pipeline | **File Upload** | Still opens `/exceptions/pipeline` |
| Portfolio | Monthly pipeline | **File Upload** | Still opens `/exceptions/pipeline` |
| File Upload page title | Monthly one-click pipeline | **File Upload** | Same page component |
| Audit Exceptions metrics source | One-click pipeline | **File Upload** | Option `value="pipeline"` unchanged |
| Audit Exceptions metrics source | Single-run (legacy) | **Manual upload** | Option `value="manual"` unchanged |

## Still available (not removed)

- Route `/exceptions/uploads` → `ExceptionUploadsPage` (single-exception job UI)
- Route `/exceptions/pipeline` → `ExceptionPipelinePage` (monthly shared uploads)
- Backend APIs for exception jobs and exception-pipeline batches
- Metrics source toggle still switches `manual` vs `pipeline` tables

## Related earlier hide / redirect

| Item | Status |
|---|---|
| `/analytics/uploads` | Redirects to `/exceptions/pipeline` (separate analytics upload page folded into File Upload) |
