import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  createExceptionPipelineBatch,
  deleteExceptionPipelineInput,
  getExceptionPipelineBatch,
  getExceptionPipelineCatalog,
  getExceptionPipelinePeriod,
  listPlazas,
  startExceptionPipelineBatch,
  uploadExceptionPipelineInput,
} from '@/lib/api'

const MONTHS = [
  { value: 1, label: 'Jan' },
  { value: 2, label: 'Feb' },
  { value: 3, label: 'Mar' },
  { value: 4, label: 'Apr' },
  { value: 5, label: 'May' },
  { value: 6, label: 'Jun' },
  { value: 7, label: 'Jul' },
  { value: 8, label: 'Aug' },
  { value: 9, label: 'Sep' },
  { value: 10, label: 'Oct' },
  { value: 11, label: 'Nov' },
  { value: 12, label: 'Dec' },
]

export function ExceptionPipelinePage() {
  const now = new Date()
  const [plazas, setPlazas] = useState([])
  const [catalog, setCatalog] = useState(null)
  const [plazaIdentifier, setPlazaIdentifier] = useState('')
  const [pipelinePlazaKey, setPipelinePlazaKey] = useState('')
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [period, setPeriod] = useState(null)
  const [selectedCodes, setSelectedCodes] = useState([])
  const [batch, setBatch] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const uploadSlots = useMemo(
    () => (catalog?.input_slots || []).filter((s) => s.user_upload),
    [catalog],
  )
  const programs = period?.programs || []

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const [plazaRes, cat] = await Promise.all([
          listPlazas(),
          getExceptionPipelineCatalog(),
        ])
        if (!active) return
        setPlazas(plazaRes.plazas || plazaRes || [])
        setCatalog(cat)
      } catch (err) {
        if (active) setError(err.message || 'Failed to load catalog')
      }
    })()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!plazaIdentifier) {
      setPeriod(null)
      return undefined
    }
    let active = true
    ;(async () => {
      try {
        const data = await getExceptionPipelinePeriod({
          plazaIdentifier,
          year,
          month,
        })
        if (!active) return
        setPeriod(data)
        setSelectedCodes((prev) => {
          const enabled = new Set(
            (data.programs || []).filter((p) => p.enabled).map((p) => p.code),
          )
          const kept = prev.filter((c) => enabled.has(c))
          return kept.length ? kept : Array.from(enabled)
        })
        setError('')
      } catch (err) {
        if (active) setError(err.message || 'Failed to load period')
      }
    })()
    return () => {
      active = false
    }
  }, [plazaIdentifier, year, month])

  useEffect(() => {
    if (!batch?.batch_uuid) return undefined
    if (!['queued', 'running'].includes(batch.status)) return undefined
    const timer = setInterval(async () => {
      try {
        const data = await getExceptionPipelineBatch(batch.batch_uuid)
        setBatch(data.batch)
        if (plazaIdentifier) {
          const periodData = await getExceptionPipelinePeriod({
            plazaIdentifier,
            year,
            month,
          })
          setPeriod(periodData)
        }
      } catch {
        /* ignore poll errors */
      }
    }, 4000)
    return () => clearInterval(timer)
  }, [batch?.batch_uuid, batch?.status, plazaIdentifier, year, month])

  async function refreshPeriod() {
    if (!plazaIdentifier) return
    const data = await getExceptionPipelinePeriod({ plazaIdentifier, year, month })
    setPeriod(data)
  }

  async function handleUpload(slotKey, fileList) {
    const files = Array.from(fileList || [])
    if (!files.length || !plazaIdentifier) return
    setBusy(true)
    setError('')
    try {
      for (const file of files) {
        await uploadExceptionPipelineInput({
          plazaIdentifier,
          year,
          month,
          slot: slotKey,
          file,
        })
      }
      await refreshPeriod()
      setNotice(`Uploaded to ${slotKey}`)
    } catch (err) {
      setError(err.message || 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(fileId) {
    setBusy(true)
    try {
      await deleteExceptionPipelineInput(fileId)
      await refreshPeriod()
    } catch (err) {
      setError(err.message || 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  function toggleProgram(code, enabled) {
    if (!enabled) return
    setSelectedCodes((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    )
  }

  async function handleStart() {
    if (!plazaIdentifier || !selectedCodes.length) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const created = await createExceptionPipelineBatch({
        plaza_identifier: plazaIdentifier,
        pipeline_plaza_key: pipelinePlazaKey || undefined,
        year,
        month,
        program_codes: selectedCodes,
        continue_on_failure: true,
      })
      const started = await startExceptionPipelineBatch(created.batch.batch_uuid)
      setBatch(started.batch)
      setNotice('Pipeline batch started. Metrics write to the pipeline tables only.')
    } catch (err) {
      setError(err.message || 'Could not start batch')
    } finally {
      setBusy(false)
    }
  }

  const years = useMemo(() => {
    const y = now.getFullYear()
    return [y, y - 1, y - 2, y - 3, y - 4]
  }, [now])

  return (
    <section className="space-y-6">
      <div className="space-y-1">
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-1">
          <Link to="/portfolio">
            <ArrowLeft className="h-4 w-4" />
            Portfolio
          </Link>
        </Button>
        <p className="text-small uppercase tracking-[0.14em] text-muted-foreground">
          Exceptions
        </p>
        <h1 className="text-display">Monthly one-click pipeline</h1>
        <p className="max-w-3xl text-body text-muted-foreground">
          Upload shared files once for a plaza and month, enable programs whose
          inputs are present, then run them serially. Metrics and outputs go to
          the new pipeline tables (legacy single-run page is unchanged).
        </p>
        <p className="text-small text-muted-foreground">
          Prefer the classic flow?{' '}
          <Link className="underline" to="/exceptions/uploads">
            Single exception uploads
          </Link>
        </p>
      </div>

      {error ? (
        <p className="rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-body">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-sm border border-border bg-accent/40 px-3 py-2 text-body">{notice}</p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Period</CardTitle>
          <CardDescription>Plaza + calendar month for shared inputs.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <label className="space-y-1">
            <span className="block text-body">Plaza</span>
            <select
              className="h-10 min-w-[14rem] rounded-sm border border-input bg-background px-2"
              value={plazaIdentifier}
              onChange={(e) => setPlazaIdentifier(e.target.value)}
            >
              <option value="">Select plaza…</option>
              {(Array.isArray(plazas) ? plazas : []).map((p) => (
                <option key={p.plaza_identifier} value={p.plaza_identifier}>
                  {p.plaza_name || p.plaza_identifier}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-body">Year</span>
            <select
              className="h-10 rounded-sm border border-input bg-background px-2"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
            >
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-body">Month</span>
            <select
              className="h-10 rounded-sm border border-input bg-background px-2"
              value={month}
              onChange={(e) => setMonth(Number(e.target.value))}
            >
              {MONTHS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-body">Pipeline plaza key (Full Exempt)</span>
            <select
              className="h-10 min-w-[10rem] rounded-sm border border-input bg-background px-2"
              value={pipelinePlazaKey}
              onChange={(e) => setPipelinePlazaKey(e.target.value)}
            >
              <option value="">—</option>
              {(catalog?.pipeline_plaza_keys || []).map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Shared input files</CardTitle>
          <CardDescription>
            Scraped vehicle/permit is optional. To-plaza VRN is separate from this
            plaza&apos;s VRN. Full Exempt final is produced by the pipeline and
            auto-feeds E15.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {uploadSlots.map((slot) => {
            const files = (period?.files || []).filter((f) => f.slot === slot.key)
            return (
              <div key={slot.key} className="rounded-sm border border-border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-body font-medium">{slot.label}</p>
                    <p className="text-small text-muted-foreground">{slot.description}</p>
                    <p className="text-small text-muted-foreground">{slot.required_hint}</p>
                  </div>
                  <label className="cursor-pointer">
                    <span className="inline-flex h-9 items-center rounded-sm border border-input px-3 text-small">
                      {busy ? 'Working…' : 'Upload'}
                    </span>
                    <input
                      type="file"
                      className="hidden"
                      multiple={Boolean(slot.multiple)}
                      accept={slot.accept}
                      disabled={busy || !plazaIdentifier}
                      onChange={(e) => {
                        handleUpload(slot.key, e.target.files)
                        e.target.value = ''
                      }}
                    />
                  </label>
                </div>
                {files.length ? (
                  <ul className="mt-2 space-y-1">
                    {files.map((f) => (
                      <li
                        key={f.id}
                        className="flex flex-wrap items-center justify-between gap-2 text-small"
                      >
                        <span>
                          {f.original_file_name}
                          {f.source === 'pipeline_output' ? ' (auto)' : ''}
                        </span>
                        {f.source !== 'pipeline_output' ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => handleDelete(f.id)}
                          >
                            Remove
                          </Button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-small text-muted-foreground">No files yet.</p>
                )}
              </div>
            )
          })}
          {(period?.files || []).some((f) => f.slot === 'full_exempt_final') ? (
            <p className="text-small text-muted-foreground">
              Full Exempt final is registered for this month — E15 can run.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Programs</CardTitle>
          <CardDescription>
            Checkboxes enable only when required monthly slots are present.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {programs.map((p) => (
            <label
              key={p.code}
              className={`flex items-start gap-3 rounded-sm border border-border p-3 ${
                p.enabled ? '' : 'opacity-55'
              }`}
            >
              <input
                type="checkbox"
                className="mt-1"
                checked={selectedCodes.includes(p.code)}
                disabled={!p.enabled || busy}
                onChange={() => toggleProgram(p.code, p.enabled)}
              />
              <span>
                <span className="block text-body font-medium">{p.label}</span>
                {!p.enabled ? (
                  <span className="text-small text-muted-foreground">
                    Missing: {(p.missing_slots || []).join(', ') || 'inputs'}
                  </span>
                ) : (
                  <span className="text-small text-muted-foreground">Ready</span>
                )}
              </span>
            </label>
          ))}
          <Button
            type="button"
            disabled={busy || !selectedCodes.length || !plazaIdentifier}
            onClick={handleStart}
          >
            Start selected programs
          </Button>
        </CardContent>
      </Card>

      {batch ? (
        <Card>
          <CardHeader>
            <CardTitle>Batch status</CardTitle>
            <CardDescription>
              {batch.batch_uuid} · {batch.status}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-body">{batch.progress_message}</p>
            {(batch.steps || []).map((s) => (
              <div key={s.program_code} className="text-small">
                {s.program_code}: {s.status}
                {s.error_message ? ` — ${s.error_message}` : ''}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </section>
  )
}
