import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { PageHeader } from '@/components/ui/page-header'
import { SearchableSelect } from '@/components/ui/searchable-select'
import { MappingConfigDialog } from '@/components/mapping-config-dialog'
import { PlazaReferenceFilesDialog } from '@/components/plaza-reference-files-dialog'
import { LocalOutputDownloads } from '@/components/local-output-downloads'
import { useAuth } from '@/components/auth-provider'
import { useToast } from '@/components/toast-provider'
import {
  createExceptionPipelineBatch,
  deleteExceptionPipelineInput,
  getExceptionPipelineBatch,
  getAnnexureServerDefaults,
  getExceptionPipelineCatalog,
  getExceptionPipelinePeriod,
  listExceptionPipelineBatches,
  listPlazas,
  startExceptionPipelineBatch,
  stopExceptionPipelineBatch,
  resumeInterruptedPipelineBatch,
  uploadExceptionPipelineInput,
} from '@/lib/api'

function batchIsActive(batch) {
  if (!batch) return false
  if (['queued', 'running'].includes(String(batch.status || ''))) return true
  return ['queued', 'running'].includes(String(batch.analytics?.status || ''))
}

function pickBatchForPeriod(batches, year, month) {
  const y = Number(year)
  const m = Number(month)
  const matches = (Array.isArray(batches) ? batches : []).filter((b) => {
    if (Number(b.year) !== y || Number(b.month) !== m) return false
    return batchIsActive(b) || String(b.status || '') === 'interrupted'
  })
  if (!matches.length) return null
  return matches[0]
}

const FULL_EXEMPT_CODE = 'full_exempt_e1_e2_e3_e13_e14'
const E15_CODE = 'e15'

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
  const { showToast } = useToast()
  const { canWrite, publishExceptionResults } = useAuth()
  const [configOpen, setConfigOpen] = useState(false)
  const [filesOpen, setFilesOpen] = useState(false)
  const [referenceStatus, setReferenceStatus] = useState(null)
  const [recommendationVisible, setRecommendationVisible] = useState(true)
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
  const [pendingRemoveIds, setPendingRemoveIds] = useState(() => new Set())
  const [batch, setBatch] = useState(null)
  const [busy, setBusy] = useState(false)
  const [periodLoading, setPeriodLoading] = useState(false)
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false)
  const [exemptPromptOpen, setExemptPromptOpen] = useState(false)
  const [startAfterExemptPrompt, setStartAfterExemptPrompt] = useState(false)
  const [error, setError] = useState('')

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
  const removeCount = pendingRemoveIds.size
  const hasUnsavedChanges = pendingCount > 0 || removeCount > 0

  useEffect(() => {
    const timer = window.setTimeout(() => setRecommendationVisible(false), 60_000)
    return () => window.clearTimeout(timer)
  }, [])

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
    setPendingRemoveIds(new Set())
    setBatch(null)
  }, [plazaIdentifier, year, month])

  useEffect(() => {
    if (!plazaIdentifier) {
      setPeriod(null)
      setBatch(null)
      setPeriodLoading(false)
      return undefined
    }
    let active = true
    setPeriodLoading(true)
    setPeriod(null)
    ;(async () => {
      try {
        const [data, batchesRes] = await Promise.all([
          getExceptionPipelinePeriod({
            plazaIdentifier,
            year,
            month,
          }),
          listExceptionPipelineBatches({ plazaIdentifier }),
        ])
        if (!active) return
        setPeriod(data)
        const restored = pickBatchForPeriod(
          batchesRes?.batches,
          year,
          month,
        )
        setBatch(restored)
        if (restored) {
          const stepCodes = (restored.steps || [])
            .map((s) => s.program_code)
            .filter(Boolean)
          setSelectedCodes(stepCodes)
          setRunAnalytics(Boolean(restored.analytics_job_uuid || restored.analytics))
        } else {
          setSelectedCodes((prev) => {
            const enabled = new Set(
              (data.programs || []).filter((p) => p.enabled).map((p) => p.code),
            )
            const next = prev.filter((code) => enabled.has(code))
            const chosen = next.length ? next : Array.from(enabled)
            if (
              chosen.length === prev.length &&
              chosen.every((code, index) => code === prev[index])
            ) {
              return prev
            }
            return chosen
          })
        }
        setError('')
        if (Number(data.pruned_missing_files || 0) > 0) {
          showToast(
            `${data.pruned_missing_files} stored file${
              data.pruned_missing_files === 1 ? ' was' : 's were'
            } removed because the object is no longer in storage. Re-upload those slots.`,
            'error',
          )
        }
      } catch (err) {
        if (active) {
          setPeriod(null)
          setError(err.message || 'Failed to load period')
        }
      } finally {
        if (active) setPeriodLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [plazaIdentifier, year, month, showToast])

  useEffect(() => {
    if (!batch?.batch_uuid) return undefined
    if (!batchIsActive(batch)) return undefined
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

  function stageRemoveUploaded(fileId) {
    setPendingRemoveIds((prev) => {
      const next = new Set(prev)
      next.add(fileId)
      return next
    })
    setError('')
  }

  function undoRemoveUploaded(fileId) {
    setPendingRemoveIds((prev) => {
      const next = new Set(prev)
      next.delete(fileId)
      return next
    })
  }

  async function handleSaveChanges() {
    if (!plazaIdentifier || !hasUnsavedChanges) return
    setBusy(true)
    setError('')
    try {
      let removed = 0
      let uploaded = 0
      for (const fileId of pendingRemoveIds) {
        await deleteExceptionPipelineInput(fileId)
        removed += 1
      }
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
      setPendingRemoveIds(new Set())
      await refreshPeriod()
      const bits = []
      if (uploaded) {
        bits.push(
          uploaded === 1 ? 'uploaded 1 file' : `uploaded ${uploaded} files`,
        )
      }
      if (removed) {
        bits.push(
          removed === 1 ? 'removed 1 file' : `removed ${removed} files`,
        )
      }
      showToast(
        bits.length
          ? `Saved: ${bits.join(', ')}. Choose checks below, then start the process.`
          : 'Saved.',
      )
    } catch (err) {
      setError(err.message || 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  const hasExemptFinal = (period?.files || []).some(
    (f) => f.slot === 'full_exempt_final',
  )
  const fullExemptProgram = programs.find((p) => p.code === FULL_EXEMPT_CODE)

  function scrapeVehicleText(code) {
    const preview = period?.scrape_preview
    const row = code === 'e05' ? preview?.e05 : code === 'e06' ? preview?.e06 : null
    if (!row) return ''
    if (row.error) return row.error
    if (row.vehicles == null || row.vehicles === undefined) return ''
    const count = Number(row.vehicles || 0).toLocaleString()
    if (!row.live) {
      return code === 'e05'
        ? 'Scraped file uploaded — no live IHMCL scrape.'
        : 'Scraped file uploaded — no live permit scrape.'
    }
    if (code === 'e06') {
      const hits = Number(row.cache_hits || 0)
      if (hits > 0) {
        return `Live permit scrape: ${count} vehicles (${hits.toLocaleString()} already stored).`
      }
      return `Live permit scrape: ${count} vehicles.`
    }
    if (row.basis === 'two_axle') {
      return `Live IHMCL scrape: ${count} unique vehicles (2-axle and above).`
    }
    return `Live IHMCL scrape: up to ${count} unique vehicles from the ETC file. The invalid 2-axle rows are the ones scraped.`
  }

  function slotLabel(slot) {
    const match = (catalog?.input_slots || []).find((s) => s.key === slot)
    return match?.label || slot
  }

  function e15CanBeChosen(program) {
    if (!program) return false
    const missing = program.missing_slots || []
    if (program.enabled) return true
    return missing.length > 0 && missing.every((slot) => slot === 'full_exempt_final')
  }

  function openExemptPrompt(thenStart) {
    setStartAfterExemptPrompt(Boolean(thenStart))
    setExemptPromptOpen(true)
  }

  function closeExemptPrompt() {
    setExemptPromptOpen(false)
    setStartAfterExemptPrompt(false)
  }

  function toggleProgram(code, enabled) {
    if (code === E15_CODE) {
      const program = programs.find((p) => p.code === E15_CODE)
      if (selectedCodes.includes(E15_CODE)) {
        setSelectedCodes((prev) => prev.filter((c) => c !== E15_CODE))
        return
      }
      if (!e15CanBeChosen(program)) return
      if (!hasExemptFinal && !selectedCodes.includes(FULL_EXEMPT_CODE)) {
        openExemptPrompt(false)
        return
      }
      setSelectedCodes((prev) => [...prev, E15_CODE])
      return
    }
    if (!enabled) return
    setSelectedCodes((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    )
  }

  const analyticsReady = Boolean(period?.analytics_ready)
  const fullExemptSelected = selectedCodes.includes(FULL_EXEMPT_CODE)
  const approvedBlocksRun = Boolean(
    fullExemptSelected && referenceStatus?.approved_exemption?.blocks_run,
  )
  const ratesBlockRun = Boolean(
    fullExemptSelected &&
      referenceStatus &&
      !referenceStatus.rates?.exists &&
      !referenceStatus.rates?.python_fallback,
  )
  const referenceBlockMessage = approvedBlocksRun
    ? 'Exempt Query needs an Approved exemption file that covers this month. Upload it with Configure rates and other files.'
    : ratesBlockRun
      ? 'No rates file covers this month, and this plaza is not in the server rate table. Upload a rates file with Configure rates and other files.'
      : ''
  const canStart =
    Boolean(plazaIdentifier) &&
    !periodLoading &&
    !hasUnsavedChanges &&
    !referenceBlockMessage &&
    (selectedCodes.length > 0 || (runAnalytics && analyticsReady))
  const mappedPipelineKey =
    catalog?.plaza_identifier_to_pipeline_key?.[plazaIdentifier] || ''

  useEffect(() => {
    if (!plazaIdentifier || !mappedPipelineKey) {
      setReferenceStatus((current) => (current == null ? current : null))
      return undefined
    }
    let cancelled = false
    getAnnexureServerDefaults(mappedPipelineKey, plazaIdentifier, year, month)
      .then((data) => {
        if (!cancelled) setReferenceStatus(data)
      })
      .catch(() => {
        if (!cancelled) setReferenceStatus((current) => (current == null ? current : null))
      })
    return () => {
      cancelled = true
    }
  }, [plazaIdentifier, mappedPipelineKey, year, month, filesOpen])
  const interruptedBatch = String(batch?.status || '') === 'interrupted'
  const batchActive = batchIsActive(batch)

  async function startWithCodes(codes) {
    setBusy(true)
    setError('')
    try {
      const created = await createExceptionPipelineBatch({
        plaza_identifier: plazaIdentifier,
        year,
        month,
        program_codes: codes,
        continue_on_failure: true,
        run_analytics: runAnalytics,
      })
      const started = await startExceptionPipelineBatch(created.batch.batch_uuid, {
        runAnalytics,
      })
      setBatch(started.batch)
      const bits = []
      if (codes.length) bits.push('exception checks')
      if (started.batch?.analytics) bits.push('plaza analytics')
      showToast(
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

  async function handleStart() {
    if (!canStart) return
    if (
      selectedCodes.includes(E15_CODE) &&
      !hasExemptFinal &&
      !selectedCodes.includes(FULL_EXEMPT_CODE)
    ) {
      openExemptPrompt(true)
      return
    }
    await startWithCodes(selectedCodes)
  }

  function confirmRunFullExemptWithE15() {
    if (!fullExemptProgram?.enabled) return
    const codes = Array.from(
      new Set([...selectedCodes, FULL_EXEMPT_CODE, E15_CODE]),
    )
    setSelectedCodes(codes)
    const shouldStart = startAfterExemptPrompt
    closeExemptPrompt()
    if (shouldStart) {
      void startWithCodes(codes)
    }
  }

  async function handleResumeInterrupted() {
    if (!batch?.batch_uuid) return
    setBusy(true)
    setError('')
    try {
      const data = await resumeInterruptedPipelineBatch(batch.batch_uuid)
      setBatch(data.batch)
      showToast('Process queued again.')
    } catch (err) {
      setError(err.message || 'Could not run the interrupted process')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemoveInterrupted() {
    if (!batch?.batch_uuid) return
    setBusy(true)
    setError('')
    try {
      await stopExceptionPipelineBatch(batch.batch_uuid)
      setBatch(null)
      showToast('Interrupted process removed. Uploaded files were kept.', 'warning')
      await refreshPeriod()
    } catch (err) {
      setError(err.message || 'Could not remove the interrupted process')
    } finally {
      setBusy(false)
    }
  }

  async function handleStopConfirm() {
    if (!batch?.batch_uuid) return
    setBusy(true)
    setError('')
    setStopConfirmOpen(false)
    try {
      const data = await stopExceptionPipelineBatch(batch.batch_uuid)
      setBatch(data.batch)
      showToast(
        'Process stopped. Run progress was discarded; uploaded input files are unchanged.',
        'warning',
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
      <PageHeader
        eyebrow={
          <div className="space-y-1">
            <Button asChild variant="ghost" size="sm" className="-ml-2">
              <Link to="/portfolio">
                <ArrowLeft className="h-4 w-4" />
                Portfolio
              </Link>
            </Button>
            <p className="text-small uppercase tracking-[0.14em] text-muted-foreground">
              Toll operations
            </p>
          </div>
        }
        title="File Upload"
        description="Select plaza files for a month, stage adds or removals, click Save, then start the process. Independent exception checks can run two at a time; dependents (e.g. E15) wait for required outputs. Plaza analytics runs in parallel when VRN/ETC are present."
        actions={
          canWrite ? (
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={() => setConfigOpen(true)}>
                Config
              </Button>
              <Button type="button" variant="outline" onClick={() => setFilesOpen(true)}>
                Configure rates and other files
              </Button>
            </div>
          ) : null
        }
      />
      {canWrite ? (
        <>
          <MappingConfigDialog open={configOpen} onClose={() => setConfigOpen(false)} />
          <PlazaReferenceFilesDialog
            open={filesOpen}
            onClose={() => setFilesOpen(false)}
            plazas={plazas}
            initialPlazaIdentifier={plazaIdentifier}
          />
        </>
      ) : null}

      {recommendationVisible ? (
        <div
          role="status"
          className="flex items-start justify-between gap-3 rounded-sm border border-primary/30 bg-card px-4 py-3 text-body shadow-sm"
        >
          <div>
            <p className="font-medium text-primary">Notice</p>
            <p className="mt-1 text-muted-foreground">
              Recommendation: upload and process one calendar month at a time. Mixing
              multiple months in a single run can confuse period matching and make
              results harder to review.
            </p>
          </div>
          <button
            type="button"
            className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Dismiss recommendation"
            onClick={() => setRecommendationVisible(false)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      {error ? (
        <p className="rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-body">
          {error}
        </p>
      ) : null}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 pt-6">
          <label className="w-[16rem] max-w-full space-y-1">
            <span className="block text-small text-muted-foreground">Plaza</span>
            <SearchableSelect
              options={(Array.isArray(plazas) ? plazas : []).map((p) => ({
                value: p.plaza_identifier,
                label: p.plaza_name || p.plaza_identifier,
              }))}
              value={plazaIdentifier}
              onChange={(value) => setPlazaIdentifier(value)}
              placeholder="Select plaza…"
              searchPlaceholder="Search plaza…"
            />
          </label>
          <label className="w-[7rem] space-y-1">
            <span className="block text-small text-muted-foreground">Year</span>
            <SearchableSelect
              options={years.map((y) => ({ value: String(y), label: String(y) }))}
              value={String(year)}
              onChange={(value) => setYear(Number(value))}
              placeholder="Year"
              searchPlaceholder="Search year…"
            />
          </label>
          <label className="w-[7.5rem] space-y-1">
            <span className="block text-small text-muted-foreground">Month</span>
            <SearchableSelect
              options={MONTHS.map((m) => ({
                value: String(m.value),
                label: m.label,
              }))}
              value={String(month)}
              onChange={(value) => setMonth(Number(value))}
              placeholder="Month"
              searchPlaceholder="Search month…"
            />
          </label>
          {plazaIdentifier && periodLoading ? (
            <p className="flex items-center gap-2 text-small text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading files for this plaza and month…
            </p>
          ) : null}
          {plazaIdentifier && !periodLoading ? (
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
            Each input accepts multiple files. Stage adds and removals, then
            click Save. Scraped vehicle/permit is optional. To-plaza VRN is
            separate from this plaza&apos;s VRN.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!plazaIdentifier ? (
            <p className="text-small text-muted-foreground">
              Select a plaza and month to load existing files.
            </p>
          ) : null}
          {plazaIdentifier && periodLoading ? (
            <div className="flex flex-col items-center justify-center gap-3 py-10 text-muted-foreground">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p className="text-body">Fetching saved files for this month…</p>
            </div>
          ) : null}
          {plazaIdentifier && !periodLoading
            ? uploadSlots.map((slot) => {
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
                      disabled={busy || !plazaIdentifier || periodLoading}
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
                          <span className="text-muted-foreground">(will upload on Save)</span>
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
                    {uploaded.map((f) => {
                      const markedRemove = pendingRemoveIds.has(f.id)
                      return (
                        <li
                          key={f.id}
                          className="flex flex-wrap items-center justify-between gap-2 text-small"
                        >
                          <span className={markedRemove ? 'text-muted-foreground line-through' : ''}>
                            {f.original_file_name}
                            {f.source === 'pipeline_output'
                              ? ' (auto)'
                              : markedRemove
                                ? ' (will remove on Save)'
                                : ' (uploaded)'}
                          </span>
                          {f.source !== 'pipeline_output' ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              disabled={busy}
                              onClick={() =>
                                markedRemove
                                  ? undoRemoveUploaded(f.id)
                                  : stageRemoveUploaded(f.id)
                              }
                            >
                              {markedRemove ? 'Undo' : 'Remove'}
                            </Button>
                          ) : null}
                        </li>
                      )
                    })}
                  </ul>
                ) : !pending.length ? (
                  <p className="mt-2 text-small text-muted-foreground">No files yet.</p>
                ) : null}
              </div>
            )
          })
            : null}
          {plazaIdentifier && !periodLoading ? (
            <>
              {(period?.files || []).some((f) => f.slot === 'full_exempt_final') ? (
                <p className="text-small text-muted-foreground">
                  Full Exempt final is registered for this month — E15 can run.
                </p>
              ) : null}
              <Button
                type="button"
                disabled={busy || !plazaIdentifier || !hasUnsavedChanges}
                onClick={handleSaveChanges}
              >
                {busy && hasUnsavedChanges
                  ? 'Saving…'
                  : hasUnsavedChanges
                    ? `Save${
                        pendingCount || removeCount
                          ? ` (${[
                              pendingCount
                                ? `+${pendingCount}`
                                : null,
                              removeCount
                                ? `−${removeCount}`
                                : null,
                            ]
                              .filter(Boolean)
                              .join(', ')})`
                          : ''
                      }`
                    : 'Save'}
              </Button>
            </>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Checks to run</CardTitle>
          <CardDescription>
            Save files first. Each check unlocks when its required files for
            this month are present. Plaza analytics is optional and selected by
            default when VRN/ETC are available.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {periodLoading ? (
            <div className="flex items-center gap-2 py-6 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <span className="text-small">Loading available checks…</span>
            </div>
          ) : (
            <>
              {scrapeVehicleText('e05') || scrapeVehicleText('e06') ? (
                <div className="rounded-sm border border-border bg-muted/40 px-3 py-2 text-small">
                  <p className="font-medium">Vehicles to scrape</p>
                  {scrapeVehicleText('e05') ? (
                    <p className="mt-1 text-muted-foreground">
                      E05 — {scrapeVehicleText('e05')}
                    </p>
                  ) : null}
                  {scrapeVehicleText('e06') ? (
                    <p className="mt-1 text-muted-foreground">
                      E06 — {scrapeVehicleText('e06')}
                    </p>
                  ) : null}
                </div>
              ) : null}
              <label
                className={`flex items-start gap-3 rounded-sm border border-border p-3 ${
                  analyticsReady ? '' : 'opacity-55'
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={runAnalytics && analyticsReady}
                  disabled={!analyticsReady || busy || !plazaIdentifier}
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
              {programs.map((p) => {
                const choosable = p.code === E15_CODE ? e15CanBeChosen(p) : p.enabled
                const e15NeedsExempt = p.code === E15_CODE && !hasExemptFinal
                const e15MissingOther = e15NeedsExempt
                  ? (p.missing_slots || []).filter((slot) => slot !== 'full_exempt_final')
                  : []
                let statusText = 'Ready'
                if (e15NeedsExempt && e15MissingOther.length) {
                  statusText = `Missing: ${e15MissingOther.map(slotLabel).join(', ')}. No Full Exempt file for this month.`
                } else if (
                  e15NeedsExempt &&
                  selectedCodes.includes(E15_CODE) &&
                  selectedCodes.includes(FULL_EXEMPT_CODE)
                ) {
                  statusText = 'E15 will run after Full Exempt finishes for this month.'
                } else if (e15NeedsExempt && !fullExemptProgram?.enabled) {
                  const need = (fullExemptProgram?.missing_slots || [])
                    .map(slotLabel)
                    .join(', ')
                  statusText = need
                    ? `No Full Exempt file for this month. Full Exempt also needs: ${need}`
                    : 'No Full Exempt file for this month. Run Exempt Query — Full Process as well.'
                } else if (e15NeedsExempt) {
                  statusText =
                    'No Full Exempt file for this month. Select E15 to run Full Exempt as well.'
                } else if (!p.enabled) {
                  statusText = `Missing: ${(p.missing_slots || []).map(slotLabel).join(', ') || 'inputs'}`
                } else if (p.code === FULL_EXEMPT_CODE && approvedBlocksRun) {
                  statusText =
                    'Needs an Approved exemption file that covers this month. Upload it with Configure rates and other files.'
                } else if (p.code === FULL_EXEMPT_CODE && ratesBlockRun) {
                  statusText =
                    'No rates file covers this month, and this plaza is not in the server rate table.'
                } else if (
                  p.code === FULL_EXEMPT_CODE &&
                  referenceStatus &&
                  !referenceStatus.rates?.exists &&
                  referenceStatus.rates?.python_fallback
                ) {
                  statusText = 'Ready. No uploaded rates file — the server rate table will be used.'
                } else if (
                  p.code === 'e05' &&
                  !(period?.files || []).some((f) => f.slot === 'scraped') &&
                  !scrapeVehicleText('e05')
                ) {
                  statusText =
                    'Ready. No scraped file — IHMCL will be scraped live when this check runs.'
                }
                const scrapeText = scrapeVehicleText(p.code)
                if (scrapeText) {
                  statusText = p.enabled ? scrapeText : `${statusText} ${scrapeText}`
                }
                return (
                <label
                  key={p.code}
                  className={`flex items-start gap-3 rounded-sm border border-border p-3 ${
                    choosable &&
                    !(p.code === FULL_EXEMPT_CODE && (approvedBlocksRun || ratesBlockRun))
                      ? ''
                      : 'opacity-55'
                  }`}
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={selectedCodes.includes(p.code)}
                    disabled={
                      busy ||
                      (!choosable && !selectedCodes.includes(p.code)) ||
                      (p.code === FULL_EXEMPT_CODE &&
                        (approvedBlocksRun || ratesBlockRun) &&
                        !selectedCodes.includes(p.code))
                    }
                    onChange={() => {
                      if (
                        p.code === FULL_EXEMPT_CODE &&
                        (approvedBlocksRun || ratesBlockRun) &&
                        !selectedCodes.includes(p.code)
                      ) {
                        return
                      }
                      toggleProgram(p.code, p.enabled)
                    }}
                  />
                  <span>
                    <span className="block text-body font-medium">{p.label}</span>
                    <span className="text-small text-muted-foreground">{statusText}</span>
                  </span>
                </label>
                )
              })}
              {hasUnsavedChanges ? (
                <p className="text-small text-muted-foreground">
                  Click Save above before starting the process. Unsaved adds and
                  removals do not change which checks are unlocked.
                </p>
              ) : null}
              {referenceBlockMessage ? (
                <p className="rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-body">
                  {referenceBlockMessage}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  disabled={busy || !canStart || batchActive || interruptedBatch || periodLoading}
                  onClick={handleStart}
                >
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
            </>
          )}
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
              <div key={s.program_code} className="space-y-2 text-small">
                <p>
                  {s.program_code}: {s.status}
                  {s.error_message ? ` — ${s.error_message}` : ''}
                </p>
                {s.status === 'succeeded' &&
                s.child_job_uuid &&
                !publishExceptionResults ? (
                  <LocalOutputDownloads
                    jobUuid={s.child_job_uuid}
                    enabled
                    title={`${s.program_code} output files`}
                  />
                ) : null}
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
        open={interruptedBatch}
        onClose={() => {}}
        title="This process was stopped when the server closed"
        description="It was still running. Run it again, or remove it. Uploaded files stay either way. It will not start on its own."
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={handleRemoveInterrupted}
          >
            Remove
          </Button>
          <Button type="button" disabled={busy} onClick={handleResumeInterrupted}>
            Run again
          </Button>
        </div>
      </Dialog>

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

      <Dialog
        open={exemptPromptOpen}
        onClose={() => {
          if (!busy) closeExemptPrompt()
        }}
        title="Run Full Exempt for this month?"
        description={
          fullExemptProgram?.enabled
            ? 'No Full Exempt file is stored for this month. E15 needs that file. Run Exempt Query — Full Process in this same process. E15 will start after it finishes.'
            : `No Full Exempt file is stored for this month. E15 needs that file. Upload the Full Exempt files first${
                (fullExemptProgram?.missing_slots || []).length
                  ? `: ${(fullExemptProgram?.missing_slots || []).map(slotLabel).join(', ')}`
                  : ''
              }.`
        }
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={closeExemptPrompt}
          >
            Cancel
          </Button>
          {fullExemptProgram?.enabled ? (
            <Button type="button" disabled={busy} onClick={confirmRunFullExemptWithE15}>
              {startAfterExemptPrompt ? 'Run Full Exempt too' : 'Add Full Exempt'}
            </Button>
          ) : null}
        </div>
      </Dialog>
    </section>
  )
}
