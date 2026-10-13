import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import {
  createExceptionPipelineBatch,
  deleteExceptionPipelineInput,
  getExceptionPipelineBatch,
  getExceptionPipelineCatalog,
  getExceptionPipelinePeriod,
  listPlazas,
  startExceptionPipelineBatch,
  stopExceptionPipelineBatch,
  uploadExceptionPipelineInput,
} from '@/lib/api'
import { useAuth } from '@/components/auth-provider'

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
  const { showExceptionUploads } = useAuth()
  const now = new Date()
  const [plazas, setPlazas] = useState([])
  const [catalog, setCatalog] = useState(null)
  const [plazaIdentifier, setPlazaIdentifier] = useState('')
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [period, setPeriod] = useState(null)
  const [selectedCodes, setSelectedCodes] = useState([])
  const [runAnalytics, setRunAnalytics] = useState(true)
  const [pendingBySlot, setPendingBySlot] = useState({})
  const [batch, setBatch] = useState(null)
  const [busy, setBusy] = useState(false)
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const uploadSlots = useMemo(
    () => (catalog?.input_slots || []).filter((s) => s.user_upload),
    [catalog],
  )
  const programs = period?.programs || []
  const pendingEntries = useMemo(
    () =>
      Object.entries(pendingBySlot).filter(
        ([, files]) => Array.isArray(files) && files.length > 0,
      ),
    [pendingBySlot],
  )
  const pendingCount = pendingEntries.reduce(
    (sum, [, files]) => sum + files.length,
    0,
  )
  const hasPending = pendingCount > 0

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
    setPendingBySlot({})
    setBatch(null)
    setNotice('')
  }, [plazaIdentifier, year, month])

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
    const analyticsBusy = ['queued', 'running'].includes(
      String(batch.analytics?.status || ''),
    )
    const batchBusy = ['queued', 'running'].includes(batch.status)
    if (!batchBusy && !analyticsBusy) return undefined
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
  }, [
    batch?.batch_uuid,
    batch?.status,
    batch?.analytics?.status,
    plazaIdentifier,
    year,
    month,
  ])

  async function refreshPeriod() {
    if (!plazaIdentifier) return
    const data = await getExceptionPipelinePeriod({ plazaIdentifier, year, month })
    setPeriod(data)
    return data
  }

  function fileKey(file) {
    return `${file.name}::${file.size}::${file.lastModified}`
  }

  function stageFiles(slotKey, fileList) {
    const incoming = Array.from(fileList || [])
    if (!incoming.length) return
    setPendingBySlot((prev) => {
      const existing = prev[slotKey] || []
      const seen = new Set(existing.map(fileKey))
      const merged = [...existing]
      for (const file of incoming) {
        const key = fileKey(file)
        if (seen.has(key)) continue
        seen.add(key)
        merged.push(file)
      }
      return { ...prev, [slotKey]: merged }
    })
    setError('')
    setNotice('')
  }

  function removePendingFile(slotKey, file) {
    setPendingBySlot((prev) => {
      const existing = prev[slotKey] || []
      const nextFiles = existing.filter((f) => fileKey(f) !== fileKey(file))
      const next = { ...prev }
      if (nextFiles.length) next[slotKey] = nextFiles
      else delete next[slotKey]
      return next
    })
  }

  async function handleUploadAll() {
    if (!plazaIdentifier || !hasPending) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      let uploaded = 0
      for (const [slotKey, files] of pendingEntries) {
        for (const file of files) {
          await uploadExceptionPipelineInput({
            plazaIdentifier,
            year,
            month,
            slot: slotKey,
            file,
          })
          uploaded += 1
        }
      }
      setPendingBySlot({})
      await refreshPeriod()
      setNotice(
        uploaded === 1
          ? 'Uploaded 1 file. Choose checks below, then start the process.'
          : `Uploaded ${uploaded} files. Choose checks below, then start the process.`,
      )
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

  const analyticsReady = Boolean(period?.analytics_ready)
  const canStart =
    Boolean(plazaIdentifier) &&
    !hasPending &&
    (selectedCodes.length > 0 || (runAnalytics && analyticsReady))
  const mappedPipelineKey =
    catalog?.plaza_identifier_to_pipeline_key?.[plazaIdentifier] || ''
  const batchActive = Boolean(
    batch &&
      (['queued', 'running'].includes(String(batch.status || '')) ||
        ['queued', 'running'].includes(String(batch.analytics?.status || ''))),
  )

  async function handleStart() {
    if (!canStart) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const created = await createExceptionPipelineBatch({
        plaza_identifier: plazaIdentifier,
        year,
        month,
        program_codes: selectedCodes,
        continue_on_failure: true,
        run_analytics: runAnalytics,
      })
      const started = await startExceptionPipelineBatch(created.batch.batch_uuid, {
        runAnalytics,
      })
      setBatch(started.batch)
      const bits = []
      if (selectedCodes.length) bits.push('exception checks')
      if (started.batch?.analytics) bits.push('plaza analytics')
      setNotice(
        bits.length
          ? `Started: ${bits.join(' + ')}.`
          : 'Processing started.',
      )
    } catch (err) {
      setError(err.message || 'Could not start processing')
    } finally {
      setBusy(false)
    }
  }

  async function handleStopConfirm() {
    if (!batch?.batch_uuid) return
    setBusy(true)
    setError('')
    setNotice('')
    setStopConfirmOpen(false)
    try {
      const data = await stopExceptionPipelineBatch(batch.batch_uuid)
      setBatch(data.batch)
      setNotice(
        'Process stopped. Run progress was discarded; uploaded input files are unchanged.',
      )
      await refreshPeriod()
    } catch (err) {
      setError(err.message || 'Could not stop the process')
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
          Toll operations
        </p>
        <h1 className="text-display">File Upload</h1>
        <p className="max-w-3xl text-body text-muted-foreground">
          Select plaza files for a month, upload them together, then start the
          process. Exception checks run in order from the shared files; when VRN
          and/or ETC are present, plaza analytics also runs.
        </p>
        <p className="max-w-3xl rounded-sm border border-border bg-muted/40 px-3 py-2 text-body text-foreground">
          Recommendation: upload and process one calendar month at a time. Mixing
          multiple months in a single run can confuse period matching and make
          results harder to review.
        </p>
        {showExceptionUploads ? (
          <p className="max-w-3xl text-body text-muted-foreground">
            Prefer the classic flow?{' '}
            <Link
              to="/exceptions/uploads"
              className="text-primary underline-offset-2 hover:underline"
            >
              Single exception uploads
            </Link>
          </p>
        ) : null}
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
          {plazaIdentifier ? (
            <p className="w-full text-small text-muted-foreground">
              {mappedPipelineKey
                ? `Full Exempt key: ${mappedPipelineKey} (from plaza)`
                : 'No Full Exempt key mapped for this plaza yet — Full Exempt checks will need annexure_plaza_config.json.'}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Shared input files</CardTitle>
          <CardDescription>
            Each input accepts multiple files. Select all files for a slot (you
            can add more later), then click Upload files. Scraped vehicle/permit
            is optional. To-plaza VRN is separate from this plaza&apos;s VRN.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {uploadSlots.map((slot) => {
            const uploaded = (period?.files || []).filter((f) => f.slot === slot.key)
            const pending = pendingBySlot[slot.key] || []
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
                      {pending.length ? 'Add more files' : 'Select files'}
                    </span>
                    <input
                      type="file"
                      className="hidden"
                      multiple
                      accept={slot.accept}
                      disabled={busy || !plazaIdentifier}
                      onChange={(e) => {
                        stageFiles(slot.key, e.target.files)
                        e.target.value = ''
                      }}
                    />
                  </label>
                </div>
                {pending.length ? (
                  <ul className="mt-2 space-y-1">
                    {pending.map((file) => (
                      <li
                        key={`${slot.key}-${fileKey(file)}`}
                        className="flex flex-wrap items-center justify-between gap-2 text-small"
                      >
                        <span>
                          {file.name}{' '}
                          <span className="text-muted-foreground">(selected, not uploaded)</span>
                        </span>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => removePendingFile(slot.key, file)}
                        >
                          Remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {uploaded.length ? (
                  <ul className="mt-2 space-y-1">
                    {uploaded.map((f) => (
                      <li
                        key={f.id}
                        className="flex flex-wrap items-center justify-between gap-2 text-small"
                      >
                        <span>
                          {f.original_file_name}
                          {f.source === 'pipeline_output' ? ' (auto)' : ' (uploaded)'}
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
                ) : !pending.length ? (
                  <p className="mt-2 text-small text-muted-foreground">No files yet.</p>
                ) : null}
              </div>
            )
          })}
          {(period?.files || []).some((f) => f.slot === 'full_exempt_final') ? (
            <p className="text-small text-muted-foreground">
              Full Exempt final is registered for this month — E15 can run.
            </p>
          ) : null}
          <Button
            type="button"
            disabled={busy || !plazaIdentifier || !hasPending}
            onClick={handleUploadAll}
          >
            {busy && hasPending
              ? 'Uploading…'
              : hasPending
                ? `Upload ${pendingCount} file${pendingCount === 1 ? '' : 's'}`
                : 'Upload files'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Checks to run</CardTitle>
          <CardDescription>
            Upload files first. Each check unlocks when its required files for
            this month are present. Plaza analytics is optional and selected by
            default when VRN/ETC are available.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <label
            className={`flex items-start gap-3 rounded-sm border border-border p-3 ${
              analyticsReady ? '' : 'opacity-55'
            }`}
          >
            <input
              type="checkbox"
              className="mt-1"
              checked={runAnalytics && analyticsReady}
              disabled={!analyticsReady || busy || hasPending}
              onChange={(e) => setRunAnalytics(Boolean(e.target.checked))}
            />
            <span>
              <span className="block text-body font-medium">
                {period?.analytics_label || 'Plaza analytics (VRN / ETC)'}
              </span>
              <span className="text-small text-muted-foreground">
                {analyticsReady
                  ? runAnalytics
                    ? 'Will run in parallel when you start (same VRN/ETC files).'
                    : 'Skipped for this run.'
                  : 'Upload VRN and/or ETC above to enable plaza analytics.'}
              </span>
            </span>
          </label>
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
                disabled={!p.enabled || busy || hasPending}
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
          {hasPending ? (
            <p className="text-small text-muted-foreground">
              Upload selected files before starting the process.
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="button" disabled={busy || !canStart || batchActive} onClick={handleStart}>
              Start process
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy || !batchActive}
              onClick={() => setStopConfirmOpen(true)}
            >
              Stop
            </Button>
          </div>
        </CardContent>
      </Card>

      {batch ? (
        <Card>
          <CardHeader>
            <CardTitle>Run status</CardTitle>
            <CardDescription>
              {batch.batch_uuid} · {batch.status}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-body">{batch.progress_message}</p>
            {batch.analytics ? (
              <div className="rounded-sm border border-border/70 bg-muted/30 px-3 py-2 text-small">
                <span className="font-medium">
                  {batch.analytics.label || 'Plaza analytics'}:{' '}
                  {batch.analytics.status}
                </span>
                {batch.analytics.error_message
                  ? ` — ${batch.analytics.error_message}`
                  : ''}
                {batch.analytics.progress_message &&
                batch.analytics.status === 'running' ? (
                  <p className="mt-1 text-muted-foreground">
                    {batch.analytics.progress_message}
                  </p>
                ) : null}
              </div>
            ) : null}
            {(batch.steps || []).map((s) => (
              <div key={s.program_code} className="text-small">
                {s.program_code}: {s.status}
                {s.error_message ? ` — ${s.error_message}` : ''}
              </div>
            ))}
            {batchActive ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => setStopConfirmOpen(true)}
              >
                Stop
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Dialog
        open={stopConfirmOpen}
        onClose={() => {
          if (!busy) setStopConfirmOpen(false)
        }}
        title="Stop this process?"
        description="All in-progress work for this run will be discarded. Uploaded input files will remain available for this plaza and month."
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => setStopConfirmOpen(false)}
          >
            Cancel
          </Button>
          <Button type="button" disabled={busy} onClick={handleStopConfirm}>
            Stop all processes
          </Button>
        </div>
      </Dialog>
    </section>
  )
}
