import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Download, FileUp, Loader2, Play, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { SearchableSelect } from '@/components/ui/searchable-select'
import { useAuth } from '@/components/auth-provider'
import { LocalOutputDownloads } from '@/components/local-output-downloads'
import {
  attachExemptFinalFile,
  attachStagingInvalidFile,
  createExceptionJob,
  deleteExceptionJob,
  deleteExceptionJobFile,
  downloadExceptionJobFile,
  getAnnexureServerDefaults,
  getExceptionJob,
  listExceptionJobs,
  listExceptionPrograms,
  listExemptFinalFiles,
  listPlazas,
  listStagingInvalidFiles,
  markExceptionJobFailed,
  startExceptionJob,
  resumeInterruptedJob,
  uploadExceptionJobFile,
} from '@/lib/api'
import { cn, formatLocalDateTime } from '@/lib/utils'

const PROGRAM_SHORT = {
  full_exempt_e1_e2_e3_e13_e14: 'Exempt Query',
  e04: 'E04',
  e05_group: 'E05',
  valid_invalid_lookup: 'Valid/Invalid',
  e05: 'E05',
  e06: 'E06 Permit',
  e07: 'E07 Pass Loss',
  e09: 'E09 Unsettled',
  e10: 'E10 Overload',
  e15: 'E15 From-To',
}

function jobFilterCode(program) {
  if (!program) return undefined
  if (Array.isArray(program.job_program_codes) && program.job_program_codes.length) {
    return program.job_program_codes.join(',')
  }
  if (program.is_process_group && Array.isArray(program.processes)) {
    return program.processes.map((p) => p.code).join(',')
  }
  return program.code
}

function processesFor(program) {
  if (!program) return []
  if (program.is_process_group && Array.isArray(program.processes)) {
    return program.processes.filter((p) => p.enabled !== false)
  }
  return [program]
}

/** Plaza + local created_at only (DB/API keep UTC). Never reuse job_name timestamps. */
function jobDisplayName(job, { includeProgram = false } = {}) {
  if (!job) return ''
  const plaza = job.plaza_name || job.pipeline_plaza_key || job.plaza_identifier || 'Job'
  const when = formatLocalDateTime(job.created_at)
  const base = includeProgram
    ? `${PROGRAM_SHORT[job.program_code] || job.program_code || 'Job'} · ${plaza}`
    : plaza
  return when && when !== '—' ? `${base} · ${when}` : base
}

const FULL_EXEMPT_CODE = 'full_exempt_e1_e2_e3_e13_e14'

function statusClass(status) {
  switch (status) {
    case 'succeeded':
      return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
    case 'failed':
      return 'bg-red-500/15 text-red-700 dark:text-red-300'
    case 'running':
    case 'queued':
    case 'interrupted':
      return 'bg-amber-500/15 text-amber-800 dark:text-amber-200'
    default:
      return 'bg-secondary text-secondary-foreground'
  }
}

/** Browse → stage files (shared Upload below all slots — no per-slot upload). */
function SlotPendingUpload({
  slot,
  pendingFiles,
  isUploading,
  busy,
  chooseLabel,
  onSelect,
  onClear,
}) {
  const pending = pendingFiles || []
  return (
    <div className="space-y-2">
      <label
        className={cn(
          'inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-sm border border-border bg-background px-3 py-2 text-small hover:bg-accent',
          (busy || isUploading) && 'pointer-events-none opacity-70',
        )}
      >
        <FileUp className="h-3.5 w-3.5" />
        {chooseLabel ||
          (pending.length
            ? slot.multiple
              ? 'Add more files…'
              : 'Change file…'
            : slot.multiple
              ? 'Choose files…'
              : 'Choose file…')}
        <input
          type="file"
          className="hidden"
          accept={slot.accept}
          multiple={Boolean(slot.multiple)}
          disabled={busy || isUploading}
          onChange={(event) => {
            onSelect(slot.key, event.target.files)
            event.target.value = ''
          }}
        />
      </label>

      {pending.length > 0 ? (
        <div className="space-y-2 rounded-sm border border-border bg-secondary/20 px-3 py-2">
          <p className="text-small text-muted-foreground">
            Selected {pending.length} file{pending.length === 1 ? '' : 's'} — not uploaded yet
          </p>
          <ul className="space-y-1">
            {pending.map((file) => (
              <li
                key={`${file.name}-${file.size}-${file.lastModified}`}
                className="truncate text-body"
              >
                {file.name}
              </li>
            ))}
          </ul>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy || isUploading}
            onClick={() => onClear(slot.key)}
          >
            Clear
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export function ExceptionUploadsPage() {
  const { publishExceptionResults } = useAuth()
  const [programs, setPrograms] = useState([])
  const [pipelineKeys, setPipelineKeys] = useState([])
  const [plazas, setPlazas] = useState([])
  const [jobs, setJobs] = useState([])
  const [jobsLoading, setJobsLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedProgram, setSelectedProgram] = useState(null)
  const [selectedProcess, setSelectedProcess] = useState(null)

  const [plazaIdentifier, setPlazaIdentifier] = useState('')
  const [pipelinePlazaKey, setPipelinePlazaKey] = useState('')
  const [activeJob, setActiveJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [uploadingSlot, setUploadingSlot] = useState(null)
  const [pendingBySlot, setPendingBySlot] = useState({})
  const [notice, setNotice] = useState('')
  const [serverDefaults, setServerDefaults] = useState(null)
  const [stagingFiles, setStagingFiles] = useState([])
  const [stagingFileId, setStagingFileId] = useState('')
  const [exemptFinalFiles, setExemptFinalFiles] = useState([])
  const [exemptFinalFileId, setExemptFinalFileId] = useState('')
  const [scrapeModeOpen, setScrapeModeOpen] = useState(false)
  const [jobSelectMode, setJobSelectMode] = useState(false)
  const [selectedJobUuids, setSelectedJobUuids] = useState(() => new Set())

  const activeProcess = selectedProcess || processesFor(selectedProgram)[0] || null
  const recentJobs = useMemo(() => jobs.slice(0, 20), [jobs])

  const programCode = String(
    activeProcess?.code || selectedProgram?.code || activeJob?.program_code || '',
  ).toLowerCase()
  const scrapeSlotKey =
    activeProcess?.scrape_slot ||
    selectedProgram?.scrape_slot ||
    (programCode === 'e05' ? 'ihmcl' : programCode === 'e06' ? 'permit' : '')
  const mayLiveScrape = Boolean(
    activeProcess?.may_live_scrape ??
      selectedProgram?.may_live_scrape ??
      (programCode === 'e05' || programCode === 'e06'),
  )
  const needsScrapeModeChoice = useMemo(() => {
    if (!activeJob || !mayLiveScrape || !scrapeSlotKey) return false
    const hasScrapeInput = (activeJob.files || []).some((f) => f.slot === scrapeSlotKey)
    return !hasScrapeInput
  }, [activeJob, mayLiveScrape, scrapeSlotKey])
  const scrapeExportFiles = useMemo(
    () => (activeJob?.files || []).filter((f) => f.slot === 'scrape_vehicles'),
    [activeJob],
  )

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
  const isUploading = Boolean(uploadingSlot)
  const interruptedJob = jobs.find((job) => job.status === 'interrupted')

  const loadCatalog = useCallback(async () => {
    const [catalog, plazaData] = await Promise.all([
      listExceptionPrograms(),
      listPlazas(),
    ])
    setPrograms(catalog.programs || [])
    setPipelineKeys(catalog.pipeline_plaza_keys || [])
    setPlazas(plazaData.plazas || [])
  }, [])

  const loadJobsForProgram = useCallback(async (program) => {
    const filterCode = jobFilterCode(program)
    if (!filterCode) {
      setJobs([])
      return
    }
    const jobData = await listExceptionJobs(undefined, filterCode)
    setJobs(jobData.jobs || [])
  }, [])

  // Programs + plazas once (no unfiltered job list).
  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        await loadCatalog()
      } catch (err) {
        if (active) setError(err.message || 'Failed to load exception programs')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [loadCatalog])

  // Load jobs only for the selected program (never show a mixed list first).
  useEffect(() => {
    setJobSelectMode(false)
    setSelectedJobUuids(new Set())
    if (!selectedProgram) {
      setJobs([])
      setJobsLoading(false)
      return undefined
    }
    let active = true
    setJobs([])
    setJobsLoading(true)
    ;(async () => {
      try {
        await loadJobsForProgram(selectedProgram)
      } catch (err) {
        if (active) {
          setJobs([])
          setError(err.message || 'Failed to load jobs')
        }
      } finally {
        if (active) setJobsLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [selectedProgram, loadJobsForProgram])

  // Default / sync process when opening a program group.
  useEffect(() => {
    if (!selectedProgram) {
      setSelectedProcess(null)
      return
    }
    const procs = processesFor(selectedProgram)
    if (!procs.length) {
      setSelectedProcess(null)
      return
    }
    setSelectedProcess((prev) => {
      if (prev && procs.some((p) => p.code === prev.code)) return prev
      return procs[0]
    })
  }, [selectedProgram])

  // Load server-side default rates / approved exemption for override slots.
  useEffect(() => {
    const key = activeJob?.pipeline_plaza_key || pipelinePlazaKey
    if (!key || selectedProgram?.code !== FULL_EXEMPT_CODE) {
      setServerDefaults(null)
      return undefined
    }
    let cancelled = false
    ;(async () => {
      try {
        const data = await getAnnexureServerDefaults(
          key,
          activeJob?.plaza_identifier || plazaIdentifier,
          activeJob?.year,
          activeJob?.month,
        )
        if (!cancelled) setServerDefaults(data)
      } catch {
        if (!cancelled) setServerDefaults(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [
    activeJob?.pipeline_plaza_key,
    activeJob?.plaza_identifier,
    pipelinePlazaKey,
    plazaIdentifier,
    selectedProgram?.code,
  ])

  // Staging invalid_table list for E05 main process (latest first).
  useEffect(() => {
    const plazaId = activeJob?.plaza_identifier || plazaIdentifier
    if (!plazaId || !activeProcess?.allows_staging_invalid_pick) {
      setStagingFiles([])
      setStagingFileId('')
      return undefined
    }
    let cancelled = false
    ;(async () => {
      try {
        const data = await listStagingInvalidFiles(plazaId, 5)
        if (!cancelled) setStagingFiles(data.files || [])
      } catch {
        if (!cancelled) setStagingFiles([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [
    activeJob?.plaza_identifier,
    plazaIdentifier,
    activeProcess?.allows_staging_invalid_pick,
    activeJob?.status,
  ])

  // Full Exempt finals for E15 From-plaza (this plaza only, latest first).
  useEffect(() => {
    const plazaId = activeJob?.plaza_identifier || plazaIdentifier
    if (!plazaId || !activeProcess?.allows_exempt_final_pick) {
      setExemptFinalFiles([])
      setExemptFinalFileId('')
      return undefined
    }
    let cancelled = false
    ;(async () => {
      try {
        const data = await listExemptFinalFiles(plazaId, 20)
        if (!cancelled) setExemptFinalFiles(data.files || [])
      } catch {
        if (!cancelled) setExemptFinalFiles([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [
    activeJob?.plaza_identifier,
    plazaIdentifier,
    activeProcess?.allows_exempt_final_pick,
    activeJob?.status,
  ])

  // Poll active job while queued/running
  useEffect(() => {
    if (!activeJob?.job_uuid) return undefined
    if (!['queued', 'running'].includes(activeJob.status)) return undefined
    const timer = setInterval(async () => {
      try {
        const data = await getExceptionJob(activeJob.job_uuid)
        setActiveJob(data.job)
        if (['succeeded', 'failed'].includes(data.job.status)) {
          const jobData = await listExceptionJobs(
            undefined,
            jobFilterCode(selectedProgram),
          )
          setJobs(jobData.jobs || [])
        }
      } catch {
        /* ignore poll errors */
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [activeJob?.job_uuid, activeJob?.status, selectedProgram])

  const plazaOptions = useMemo(
    () =>
      plazas.map((p) => ({
        value: p.plaza_identifier,
        label: p.plaza_name,
        meta: p.plaza_code || '',
      })),
    [plazas],
  )

  const pipelineOptions = useMemo(
    () => pipelineKeys.map((key) => ({ value: key, label: key })),
    [pipelineKeys],
  )

  const selectedPlaza = plazas.find((p) => p.plaza_identifier === plazaIdentifier)

  async function handleCreateJob() {
    const process = activeProcess
    if (!process?.code) {
      setError('Select a process before creating a job.')
      return
    }
    setBusy(true)
    setNotice('')
    setError('')
    try {
      const data = await createExceptionJob({
        program_code: process.code,
        plaza_identifier: plazaIdentifier,
        ...(process.requires_pipeline_plaza_key ||
        selectedProgram?.requires_pipeline_plaza_key
          ? { pipeline_plaza_key: pipelinePlazaKey }
          : {}),
      })
      setActiveJob(data.job)
      setPendingBySlot({})
      setStagingFileId('')
      setExemptFinalFileId('')
      setNotice('Job created. Choose files for each slot, click Upload files, then Start.')
      const jobData = await listExceptionJobs(
        undefined,
        jobFilterCode(selectedProgram) || process.code,
      )
      setJobs(jobData.jobs || [])
    } catch (err) {
      setError(err.message || 'Could not create job')
    } finally {
      setBusy(false)
    }
  }

  function handleSelectPendingFiles(slotKey, fileList) {
    if (!fileList?.length) return
    const files = Array.from(fileList)
    setPendingBySlot((prev) => {
      const slot = (activeProcess?.input_slots || selectedProgram?.input_slots || []).find(
        (s) => s.key === slotKey,
      )
      if (slot?.multiple && prev[slotKey]?.length) {
        return { ...prev, [slotKey]: [...prev[slotKey], ...files] }
      }
      return { ...prev, [slotKey]: files }
    })
    setNotice('')
    setError('')
  }

  function handleClearPending(slotKey) {
    setPendingBySlot((prev) => {
      const next = { ...prev }
      delete next[slotKey]
      return next
    })
  }

  async function handleUploadAllPending() {
    if (!activeJob || pendingCount === 0) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      let job = activeJob
      let uploaded = 0
      for (const [slotKey, files] of pendingEntries) {
        setUploadingSlot(slotKey)
        for (const file of files) {
          const data = await uploadExceptionJobFile(activeJob.job_uuid, slotKey, file)
          job = data.job
          uploaded += 1
        }
      }
      setActiveJob(job)
      setPendingBySlot({})
      setNotice(
        uploaded === 1
          ? 'Uploaded 1 file. You can Start the job when ready.'
          : `Uploaded ${uploaded} files. You can Start the job when ready.`,
      )
    } catch (err) {
      setError(err.message || 'Upload failed')
    } finally {
      setUploadingSlot(null)
      setBusy(false)
    }
  }

  async function handleDeleteFile(fileId) {
    if (!activeJob) return
    setBusy(true)
    setError('')
    try {
      const data = await deleteExceptionJobFile(activeJob.job_uuid, fileId)
      setActiveJob(data.job)
    } catch (err) {
      setError(err.message || 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleMarkFailed() {
    if (!activeJob) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const data = await markExceptionJobFailed(activeJob.job_uuid)
      setActiveJob(data.job)
      setNotice('Job marked failed. You can Retry now.')
      const jobData = await listExceptionJobs(
        undefined,
        jobFilterCode(selectedProgram),
      )
      setJobs(jobData.jobs || [])
    } catch (err) {
      setError(err.message || 'Could not mark job failed')
    } finally {
      setBusy(false)
    }
  }

  function exitJobSelectMode() {
    setJobSelectMode(false)
    setSelectedJobUuids(new Set())
  }

  function toggleJobSelected(jobUuid) {
    setSelectedJobUuids((prev) => {
      const next = new Set(prev)
      if (next.has(jobUuid)) next.delete(jobUuid)
      else next.add(jobUuid)
      return next
    })
  }

  function toggleSelectAllRecentJobs() {
    setSelectedJobUuids((prev) => {
      const ids = recentJobs.map((j) => j.job_uuid)
      if (ids.length > 0 && ids.every((id) => prev.has(id))) {
        return new Set()
      }
      return new Set(ids)
    })
  }

  async function handleDeleteSelectedJobs() {
    const targets = [...selectedJobUuids]
    if (!targets.length) return
    const ok = window.confirm(
      `Delete ${targets.length} job${targets.length === 1 ? '' : 's'}? Input files will be removed. Outputs and scrape cache are kept.`,
    )
    if (!ok) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      let deleted = 0
      const errors = []
      for (const jobUuid of targets) {
        try {
          await deleteExceptionJob(jobUuid)
          deleted += 1
          if (activeJob?.job_uuid === jobUuid) {
            setActiveJob(null)
            setPendingBySlot({})
            setStagingFileId('')
            setExemptFinalFileId('')
          }
        } catch (err) {
          errors.push(err.message || `Failed to delete ${jobUuid.slice(0, 8)}`)
        }
      }
      exitJobSelectMode()
      const jobData = await listExceptionJobs(
        undefined,
        jobFilterCode(selectedProgram),
      )
      setJobs(jobData.jobs || [])
      if (deleted) {
        setNotice(
          deleted === 1
            ? 'Job deleted. Outputs and scrape cache were kept.'
            : `${deleted} jobs deleted. Outputs and scrape cache were kept.`,
        )
      }
      if (errors.length) {
        setError(errors.slice(0, 3).join(' · '))
      }
    } catch (err) {
      setError(err.message || 'Could not delete jobs')
    } finally {
      setBusy(false)
    }
  }

  async function handleResumeInterruptedJob() {
    if (!interruptedJob) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const data = await resumeInterruptedJob(interruptedJob.job_uuid)
      setActiveJob(data.job)
      setNotice('Job queued again.')
      await loadJobsForProgram(selectedProgram)
    } catch (err) {
      setError(err.message || 'Could not run the interrupted job')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemoveInterruptedJob() {
    if (!interruptedJob) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await deleteExceptionJob(interruptedJob.job_uuid)
      if (activeJob?.job_uuid === interruptedJob.job_uuid) setActiveJob(null)
      setNotice('Interrupted job removed.')
      await loadJobsForProgram(selectedProgram)
    } catch (err) {
      setError(err.message || 'Could not remove the interrupted job')
    } finally {
      setBusy(false)
    }
  }

  async function queueJobWithScrapeMode(scrapeMode) {
    if (!activeJob) return
    setBusy(true)
    setError('')
    setNotice('')
    setScrapeModeOpen(false)
    try {
      const data = await startExceptionJob(activeJob.job_uuid, {
        scrapeMode: scrapeMode || undefined,
      })
      setActiveJob(data.job)
      setNotice(
        scrapeMode === 'export'
          ? 'Job queued — will export vehicles to scrape, then stop.'
          : 'Job queued. Progress updates automatically.',
      )
    } catch (err) {
      if (err?.needs_scrape_mode || err?.data?.needs_scrape_mode) {
        setScrapeModeOpen(true)
        setError('')
      } else {
        setError(err.message || 'Could not start job')
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleStart() {
    if (!activeJob) return
    if (needsScrapeModeChoice) {
      setScrapeModeOpen(true)
      return
    }
    await queueJobWithScrapeMode('live')
  }

  async function handleDownloadJobFile(fileId) {
    if (!activeJob) return
    setBusy(true)
    setError('')
    try {
      const data = await downloadExceptionJobFile(activeJob.job_uuid, fileId)
      if (data?.download_url) {
        window.open(data.download_url, '_blank', 'noopener,noreferrer')
      } else {
        setError('Download URL missing')
      }
    } catch (err) {
      setError(err.message || 'Download failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleAttachStaging(fileIdOverride) {
    const id = fileIdOverride ?? stagingFileId
    if (!activeJob || !id) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const data = await attachStagingInvalidFile(activeJob.job_uuid, Number(id))
      setActiveJob(data.job)
      setStagingFileId(String(id))
      setNotice('Invalid table attached. You can Start the job when ready.')
    } catch (err) {
      setError(err.message || 'Could not attach staging file')
    } finally {
      setBusy(false)
    }
  }

  async function handleAttachExemptFinal(fileIdOverride) {
    const id = fileIdOverride ?? exemptFinalFileId
    if (!activeJob || !id) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const data = await attachExemptFinalFile(activeJob.job_uuid, Number(id))
      setActiveJob(data.job)
      setExemptFinalFileId(String(id))
      setNotice('Full Exempt final attached as From-plaza. Upload To-plaza VRN, then Start.')
    } catch (err) {
      setError(err.message || 'Could not attach exempt final file')
    } finally {
      setBusy(false)
    }
  }

  const stagingOptions = useMemo(
    () =>
      stagingFiles.map((f) => ({
        value: String(f.id),
        label: f.file_name || f.original_file_name || `file #${f.id}`,
        meta: formatLocalDateTime(f.created_at),
      })),
    [stagingFiles],
  )

  const exemptFinalOptions = useMemo(
    () =>
      exemptFinalFiles.map((f) => ({
        value: String(f.id),
        label:
          f.display_name ||
          f.original_file_name ||
          `${f.plaza_name || 'Plaza'} · ${f.period_label || 'Exempt final'}`,
        meta: [
          f.period_label,
          formatLocalDateTime(f.created_at),
        ]
          .filter(Boolean)
          .join(' · '),
      })),
    [exemptFinalFiles],
  )
  async function openJob(jobUuid) {
    setBusy(true)
    setError('')
    try {
      const data = await getExceptionJob(jobUuid)
      setActiveJob(data.job)
      setPendingBySlot({})
      setStagingFileId('')
      setExemptFinalFileId('')
      const jobCode = data.job.program_code
      const parent =
        programs.find((p) => p.code === jobCode) ||
        programs.find(
          (p) =>
            p.is_process_group &&
            (p.processes || []).some((proc) => proc.code === jobCode),
        ) ||
        null
      setSelectedProgram(parent)
      if (parent?.is_process_group) {
        const proc = (parent.processes || []).find((p) => p.code === jobCode)
        setSelectedProcess(proc || null)
      } else {
        setSelectedProcess(parent)
      }
      setPlazaIdentifier(data.job.plaza_identifier)
      setPipelinePlazaKey(data.job.pipeline_plaza_key)
    } catch (err) {
      setError(err.message || 'Could not load job')
    } finally {
      setBusy(false)
    }
  }

  function serverDefaultForSlot(slotKey) {
    if (!serverDefaults || !slotKey) return null
    return serverDefaults[slotKey] || null
  }

  const jobSlots = new Set((activeJob?.files || []).map((file) => file.slot))
  const exemptReferenceBlocksStart =
    selectedProgram?.code === FULL_EXEMPT_CODE &&
    ((serverDefaults?.approved_exemption?.blocks_run &&
      !jobSlots.has('approved_exemption')) ||
      (serverDefaults &&
        !serverDefaults.rates?.exists &&
        !serverDefaults.rates?.python_fallback &&
        !jobSlots.has('rates')))

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading exception programs…</p>
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          {selectedProgram ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="-ml-2 mb-1"
              onClick={() => {
                setSelectedProgram(null)
                setSelectedProcess(null)
                setActiveJob(null)
                setJobs([])
                setPendingBySlot({})
                setNotice('')
                setError('')
                setStagingFileId('')
                setExemptFinalFileId('')
              }}
            >
              <ArrowLeft className="h-4 w-4" />
              All programs
            </Button>
          ) : (
            <Button asChild variant="ghost" size="sm" className="-ml-2 mb-1">
              <Link to="/portfolio">
                <ArrowLeft className="h-4 w-4" />
                Portfolio
              </Link>
            </Button>
          )}
          <p className="text-small uppercase tracking-[0.14em] text-muted-foreground">
            Exceptions
          </p>
          <h1 className="text-display">File upload &amp; run</h1>
          <p className="max-w-2xl text-body text-muted-foreground">
            Choose an exception program, upload source files to S3 (
            <code className="text-small">Toll Analytics Files</code>
            ), then start a job. E01–E03 / E13–E14 share one Full Exempt pipeline.
          </p>
        </div>
      </div>

      {error ? (
        <Card>
          <CardHeader>
            <CardTitle>Something went wrong</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}
      {notice ? (
        <p className="rounded-sm border border-border bg-accent/40 px-3 py-2 text-body">{notice}</p>
      ) : null}

      {!selectedProgram ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {programs.map((program) => (
            <button
              key={program.code}
              type="button"
              disabled={!program.enabled}
              onClick={() => {
                if (!program.enabled) return
                setSelectedProgram(program)
                setActiveJob(null)
                setJobs([])
                setJobsLoading(true)
                setPendingBySlot({})
                setStagingFileId('')
                setExemptFinalFileId('')
                setNotice('')
              }}
              className={cn(
                'text-left transition',
                program.enabled ? 'hover:-translate-y-0.5' : 'cursor-not-allowed opacity-55',
              )}
            >
              <Card className="h-full">
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-subheader">{program.label}</CardTitle>
                    <span
                      className={cn(
                        'rounded-sm px-2 py-0.5 text-small',
                        program.enabled
                          ? 'bg-primary/15 text-primary'
                          : 'bg-secondary text-muted-foreground',
                      )}
                    >
                      {program.enabled ? 'Ready' : 'Soon'}
                    </span>
                  </div>
                  <CardDescription>{program.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-small text-muted-foreground">
                    Codes: {(program.group_exception_codes || []).join(', ')}
                    {program.is_process_group && program.processes?.length
                      ? ` · ${program.processes.length} processes`
                      : ''}
                  </p>
                </CardContent>
              </Card>
            </button>
          ))}
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>{selectedProgram.label}</CardTitle>
                  <CardDescription>
                    {`Metrics: ${(selectedProgram.group_exception_codes || []).join(', ')}`}
                    {selectedProgram.description ? (
                      <span className="mt-1 block text-muted-foreground">
                        {selectedProgram.description}
                      </span>
                    ) : null}
                  </CardDescription>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setSelectedProgram(null)
                    setSelectedProcess(null)
                    setActiveJob(null)
                    setPendingBySlot({})
                    setStagingFileId('')
                    setExemptFinalFileId('')
                  }}
                >
                  All programs
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {selectedProgram.is_process_group && processesFor(selectedProgram).length > 1 ? (
                <div className="space-y-2">
                  <Label>Process</Label>
                  <div className="flex flex-wrap gap-2">
                    {processesFor(selectedProgram).map((proc) => (
                      <Button
                        key={proc.code}
                        type="button"
                        size="sm"
                        variant={activeProcess?.code === proc.code ? 'default' : 'outline'}
                        disabled={busy}
                        onClick={() => {
                          setSelectedProcess(proc)
                          if (activeJob && activeJob.program_code !== proc.code) {
                            setActiveJob(null)
                          }
                          setNotice('')
                          setError('')
                        }}
                      >
                        {proc.label}
                      </Button>
                    ))}
                  </div>
                  {activeProcess?.description ? (
                    <p className="text-small text-muted-foreground">
                      {activeProcess.description}
                    </p>
                  ) : null}
                  {activeProcess?.updates_metrics === false ? (
                    <p className="text-small text-muted-foreground">
                      This step does not update metrics — staging file only.
                    </p>
                  ) : null}
                </div>
              ) : null}

              {!activeJob ? (
                <>
                  <div
                    className={cn(
                      'grid gap-4',
                      (activeProcess?.requires_pipeline_plaza_key ||
                        selectedProgram.requires_pipeline_plaza_key)
                        ? 'sm:grid-cols-2'
                        : 'sm:grid-cols-1',
                    )}
                  >
                    <div className="space-y-2">
                      <Label>Plaza</Label>
                      <SearchableSelect
                        options={plazaOptions}
                        value={plazaIdentifier}
                        onChange={setPlazaIdentifier}
                        placeholder="Select plaza…"
                      />
                      {(activeProcess?.uses_entity_map ?? selectedProgram.uses_entity_map) ? (
                        <p className="text-small text-muted-foreground">
                          Entity name for rates / downloads is resolved from{' '}
                          <code className="text-small">plaza_entity_map.json</code>.
                        </p>
                      ) : null}
                    </div>
                    {(activeProcess?.requires_pipeline_plaza_key ||
                      selectedProgram.requires_pipeline_plaza_key) ? (
                      <div className="space-y-2">
                        <Label>Pipeline plaza key</Label>
                        <SearchableSelect
                          options={pipelineOptions}
                          value={pipelinePlazaKey}
                          onChange={setPipelinePlazaKey}
                          placeholder="e.g. BASSI…"
                        />
                        <p className="text-small text-muted-foreground">
                          Must match codes_dump / annexure config (usually uppercase name).
                        </p>
                      </div>
                    ) : null}
                  </div>
                  <Button
                    type="button"
                    disabled={
                      busy ||
                      !plazaIdentifier ||
                      !activeProcess?.code ||
                      ((activeProcess?.requires_pipeline_plaza_key ||
                        selectedProgram.requires_pipeline_plaza_key) &&
                        !pipelinePlazaKey)
                    }
                    onClick={handleCreateJob}
                  >
                    {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
                    Create job
                  </Button>
                </>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2 text-body">
                    <span className="text-muted-foreground">Job</span>
                    <span className="font-medium">{jobDisplayName(activeJob)}</span>
                    <span
                      className={cn(
                        'rounded-sm px-2 py-0.5 text-small capitalize',
                        statusClass(activeJob.status),
                      )}
                    >
                      {activeJob.status}
                    </span>
                    <code className="text-small text-muted-foreground">
                      {activeJob.job_uuid.slice(0, 8)}…
                    </code>
                  </div>

                  {(activeProcess?.input_slots || selectedProgram.input_slots || []).map((slot) => {
                    const slotFiles = (activeJob.files || []).filter((f) => f.slot === slot.key)
                    const canEdit = ['draft', 'failed'].includes(activeJob.status)
                    const defaults = slot.server_default ? serverDefaultForSlot(slot.key) : null
                    const hasServerFile = Boolean(defaults?.exists && defaults?.file_name)
                    const hasOverrideUpload = slotFiles.length > 0
                    const isInvalidPickSlot = Boolean(slot.or_staging_pick)
                    const hasInvalidReady = isInvalidPickSlot && slotFiles.length > 0
                    const isExemptFinalPickSlot = Boolean(slot.or_exempt_final_pick)
                    const hasExemptFinalReady =
                      isExemptFinalPickSlot && slotFiles.length > 0

                    // Clearer two-path UX for Incorrect FASTag invalid table.
                    if (isInvalidPickSlot) {
                      return (
                        <div
                          key={slot.key}
                          className="space-y-3 rounded-sm border border-border p-4"
                        >
                          <div>
                            <p className="text-subheader">
                              Invalid table
                              <span className="text-primary"> *</span>
                            </p>
                            <p className="mt-1 text-small text-muted-foreground">
                              Pick one path: reuse a file from Valid/Invalid Lookup, or choose
                              a new file and use Upload files below. Then Start job.
                            </p>
                          </div>

                          {hasInvalidReady ? (
                            <div className="space-y-2 rounded-sm border border-emerald-500/30 bg-emerald-500/10 px-3 py-3">
                              <p className="text-body font-medium text-emerald-800 dark:text-emerald-200">
                                Ready — invalid table attached
                              </p>
                              {slotFiles.map((file) => (
                                <div
                                  key={file.id}
                                  className="flex items-center justify-between gap-2 text-body"
                                >
                                  <span className="truncate">{file.original_file_name}</span>
                                  {canEdit ? (
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="sm"
                                      disabled={busy}
                                      onClick={() => handleDeleteFile(file.id)}
                                    >
                                      Change
                                    </Button>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          ) : null}

                          {canEdit && !hasInvalidReady ? (
                            <div className="grid gap-3 sm:grid-cols-2">
                              <div className="space-y-3 rounded-sm border border-border bg-secondary/20 p-3">
                                <div>
                                  <p className="text-body font-medium">A. From Valid/Invalid</p>
                                  <p className="text-small text-muted-foreground">
                                    Latest files for this plaza first. Choose one, then Attach.
                                  </p>
                                </div>
                                {stagingOptions.length === 0 ? (
                                  <p className="text-small text-muted-foreground">
                                    None yet — run “Valid / Invalid Lookup” for this plaza first,
                                    or use upload on the right.
                                  </p>
                                ) : (
                                  <>
                                    <SearchableSelect
                                      value={stagingFileId}
                                      onChange={(value) => setStagingFileId(value)}
                                      options={stagingOptions}
                                      placeholder="Choose existing invalid file…"
                                      disabled={busy}
                                    />
                                    <Button
                                      type="button"
                                      size="sm"
                                      disabled={busy || !stagingFileId}
                                      onClick={() => handleAttachStaging()}
                                    >
                                      Attach
                                    </Button>
                                  </>
                                )}
                              </div>

                              <div className="space-y-3 rounded-sm border border-border bg-secondary/20 p-3">
                                <div>
                                  <p className="text-body font-medium">B. Choose new file</p>
                                  <p className="text-small text-muted-foreground">
                                    Select a file here, then click Upload files below.
                                  </p>
                                </div>
                                <SlotPendingUpload
                                  slot={slot}
                                  pendingFiles={pendingBySlot[slot.key]}
                                  isUploading={isUploading}
                                  busy={busy}
                                  chooseLabel="Choose invalid table…"
                                  onSelect={handleSelectPendingFiles}
                                  onClear={handleClearPending}
                                />
                              </div>
                            </div>
                          ) : null}
                        </div>
                      )
                    }

                    // E15 From-plaza: reuse Full Exempt final for this plaza, or upload.
                    if (isExemptFinalPickSlot) {
                      return (
                        <div
                          key={slot.key}
                          className="space-y-3 rounded-sm border border-border p-4"
                        >
                          <div>
                            <p className="text-subheader">
                              From-plaza exempt
                              <span className="text-primary"> *</span>
                            </p>
                            <p className="mt-1 text-small text-muted-foreground">
                              Reuse a Full Exempt *_final.xlsx already generated for this plaza,
                              or upload a new file.
                            </p>
                          </div>

                          {hasExemptFinalReady ? (
                            <div className="space-y-2 rounded-sm border border-emerald-500/30 bg-emerald-500/10 px-3 py-3">
                              <p className="text-body font-medium text-emerald-800 dark:text-emerald-200">
                                Ready — From-plaza exempt attached
                              </p>
                              {slotFiles.map((file) => (
                                <div
                                  key={file.id}
                                  className="flex items-center justify-between gap-2 text-body"
                                >
                                  <span className="truncate">{file.original_file_name}</span>
                                  {canEdit ? (
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="sm"
                                      disabled={busy}
                                      onClick={() => handleDeleteFile(file.id)}
                                    >
                                      Change
                                    </Button>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          ) : null}

                          {canEdit && !hasExemptFinalReady ? (
                            <div className="grid gap-3 sm:grid-cols-2">
                              <div className="space-y-3 rounded-sm border border-border bg-secondary/20 p-3">
                                <div>
                                  <p className="text-body font-medium">A. From Full Exempt</p>
                                  <p className="text-small text-muted-foreground">
                                    Most recent finals for this plaza. Choose one, then Attach.
                                  </p>
                                </div>
                                {exemptFinalOptions.length === 0 ? (
                                  <p className="text-small text-muted-foreground">
                                    None yet — run “Exempt Query — Full Process” for this plaza
                                    first, or upload on the right.
                                  </p>
                                ) : (
                                  <>
                                    <SearchableSelect
                                      value={exemptFinalFileId}
                                      onChange={(value) => setExemptFinalFileId(value)}
                                      options={exemptFinalOptions}
                                      placeholder="Choose existing exempt final…"
                                      disabled={busy}
                                    />
                                    <Button
                                      type="button"
                                      size="sm"
                                      disabled={busy || !exemptFinalFileId}
                                      onClick={() => handleAttachExemptFinal()}
                                    >
                                      Attach
                                    </Button>
                                  </>
                                )}
                              </div>

                              <div className="space-y-3 rounded-sm border border-border bg-secondary/20 p-3">
                                <div>
                                  <p className="text-body font-medium">B. Choose new file</p>
                                  <p className="text-small text-muted-foreground">
                                    Select a file here, then click Upload files below.
                                  </p>
                                </div>
                                <SlotPendingUpload
                                  slot={slot}
                                  pendingFiles={pendingBySlot[slot.key]}
                                  isUploading={isUploading}
                                  busy={busy}
                                  chooseLabel="Choose exempt file…"
                                  onSelect={handleSelectPendingFiles}
                                  onClear={handleClearPending}
                                />
                              </div>
                            </div>
                          ) : null}
                        </div>
                      )
                    }

                    return (
                      <div key={slot.key} className="space-y-2 rounded-sm border border-border p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <p className="text-subheader">
                              {slot.label}
                              {slot.required ? (
                                <span className="text-primary"> *</span>
                              ) : (
                                <span className="text-small text-muted-foreground"> (optional)</span>
                              )}
                            </p>
                          </div>
                        </div>

                        {canEdit ? (
                          <SlotPendingUpload
                            slot={slot}
                            pendingFiles={pendingBySlot[slot.key]}
                            isUploading={isUploading}
                            busy={busy}
                            chooseLabel={
                              hasServerFile ? 'Choose override file…' : undefined
                            }
                            onSelect={handleSelectPendingFiles}
                            onClear={handleClearPending}
                          />
                        ) : null}

                        {hasServerFile && !hasOverrideUpload ? (
                          <div className="rounded-sm border border-dashed border-border bg-secondary/30 px-3 py-2 text-small">
                            <p className="text-body">
                              Uploaded file: <span className="font-medium">{defaults.file_name}</span>
                            </p>
                            <p className="text-muted-foreground">
                              Valid {defaults.valid_from} to {defaults.valid_to || 'open'}.
                              This job uses it when the period sits inside these dates.
                              Upload a file here only to override it for this job.
                            </p>
                          </div>
                        ) : null}

                        {slot.key === 'rates' && !hasServerFile && !hasOverrideUpload ? (
                          <p className="text-small text-muted-foreground">
                            {defaults?.python_fallback
                              ? 'No uploaded rates file for this period. The server rate table will be used.'
                              : 'No uploaded rates file for this period, and this plaza is not in the server rate table.'}
                          </p>
                        ) : null}

                        {slot.key === 'approved_exemption' &&
                        defaults?.uses_approved_script &&
                        !hasServerFile &&
                        !hasOverrideUpload ? (
                          <p className="text-small text-destructive">
                            This plaza cannot run Exempt Query until an Approved exemption
                            file that covers the period is uploaded.
                          </p>
                        ) : null}

                        {hasServerFile && hasOverrideUpload ? (
                          <p className="text-small text-muted-foreground">
                            Using your upload instead of server default{' '}
                            <span className="font-medium">{defaults.file_name}</span>.
                          </p>
                        ) : null}

                        {!isUploading &&
                        slotFiles.length === 0 &&
                        !hasServerFile &&
                        !(pendingBySlot[slot.key] || []).length &&
                        slot.key !== 'rates' &&
                        !(
                          slot.key === 'approved_exemption' &&
                          defaults?.uses_approved_script
                        ) ? (
                          <p className="text-small text-muted-foreground">No files yet.</p>
                        ) : null}

                        {slotFiles.length > 0 ? (
                          <ul className="space-y-1">
                            {slotFiles.map((file) => (
                              <li
                                key={file.id}
                                className="flex items-center justify-between gap-2 text-body"
                              >
                                <span className="truncate">{file.original_file_name}</span>
                                {canEdit ? (
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    disabled={busy}
                                    onClick={() => handleDeleteFile(file.id)}
                                    aria-label="Remove file"
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    )
                  })}

                  {['draft', 'failed'].includes(activeJob.status) ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        disabled={busy || pendingCount === 0}
                        onClick={handleUploadAllPending}
                      >
                        {isUploading ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Upload className="h-4 w-4" />
                        )}
                        {isUploading
                          ? 'Uploading…'
                          : pendingCount > 0
                            ? `Upload ${pendingCount} file${pendingCount === 1 ? '' : 's'}`
                            : 'Upload files'}
                      </Button>
                      <Button
                        type="button"
                        disabled={busy || isUploading || exemptReferenceBlocksStart}
                        onClick={handleStart}
                      >
                        {busy && !isUploading ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                        {activeJob.status === 'failed' ? 'Retry job' : 'Start job'}
                      </Button>
                    </div>
                  ) : null}

                  {['queued', 'running'].includes(activeJob.status) ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy}
                      onClick={handleMarkFailed}
                    >
                      Mark as failed (unstick)
                    </Button>
                  ) : null}

                  {scrapeExportFiles.length > 0 ? (
                    <div className="space-y-2 rounded-sm border border-amber-500/40 bg-amber-500/10 px-3 py-3">
                      <p className="text-body font-medium">
                        Vehicles to scrape (download, scrape offline, then upload result)
                      </p>
                      {scrapeExportFiles.map((file) => (
                        <div
                          key={file.id}
                          className="flex flex-wrap items-center justify-between gap-2"
                        >
                          <span className="truncate text-body">{file.original_file_name}</span>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            onClick={() => handleDownloadJobFile(file.id)}
                          >
                            <Download className="h-3.5 w-3.5" />
                            Download
                          </Button>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {activeJob.status === 'succeeded' && !publishExceptionResults ? (
                    <LocalOutputDownloads jobUuid={activeJob.job_uuid} enabled />
                  ) : null}

                  {activeJob.progress_message ? (
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-sm bg-secondary/40 p-3 text-small">
                      {activeJob.progress_message}
                    </pre>
                  ) : null}
                  {activeJob.error_message ? (
                    <p className="text-body text-red-600 dark:text-red-300">{activeJob.error_message}</p>
                  ) : null}

                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setActiveJob(null)
                      setPendingBySlot({})
                      setStagingFileId('')
                      setExemptFinalFileId('')
                    }}
                  >
                    New job for this program
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
              <div className="min-w-0 space-y-1">
                <CardTitle>Recent jobs</CardTitle>
                <CardDescription>
                  {selectedProgram.label}
                  {selectedProgram.is_process_group
                    ? ' — both processes; named as plaza + date/time.'
                    : ' — named as plaza + date/time.'}
                </CardDescription>
              </div>
              {jobs.length > 0 && !jobsLoading ? (
                jobSelectMode ? (
                  <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={busy || recentJobs.length === 0}
                      onClick={toggleSelectAllRecentJobs}
                    >
                      {recentJobs.length > 0 &&
                      recentJobs.every((j) => selectedJobUuids.has(j.job_uuid))
                        ? 'Clear'
                        : 'Select all'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={exitJobSelectMode}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      disabled={busy || selectedJobUuids.size === 0}
                      className="bg-red-600 text-white hover:bg-red-700"
                      onClick={handleDeleteSelectedJobs}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                      {selectedJobUuids.size > 0 ? ` (${selectedJobUuids.size})` : ''}
                    </Button>
                  </div>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => {
                      setJobSelectMode(true)
                      setSelectedJobUuids(new Set())
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete
                  </Button>
                )
              ) : null}
            </CardHeader>
            <CardContent className="space-y-2">
              {jobsLoading ? (
                <p className="text-body text-muted-foreground">Loading jobs…</p>
              ) : jobs.length === 0 ? (
                <p className="text-body text-muted-foreground">No jobs yet.</p>
              ) : (
                recentJobs.map((job) => {
                  const selected = selectedJobUuids.has(job.job_uuid)
                  return (
                    <div
                      key={job.job_uuid}
                      className={cn(
                        'flex items-stretch gap-2 rounded-sm border border-border px-3 py-2',
                        jobSelectMode && selected && 'border-red-500/40 bg-red-500/5',
                      )}
                    >
                      {jobSelectMode ? (
                        <label className="flex shrink-0 cursor-pointer items-center">
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-red-600"
                            checked={selected}
                            disabled={busy}
                            onChange={() => toggleJobSelected(job.job_uuid)}
                            aria-label={`Select ${jobDisplayName(job)}`}
                          />
                        </label>
                      ) : null}
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left hover:opacity-90"
                        disabled={busy && jobSelectMode}
                        onClick={() => {
                          if (jobSelectMode) {
                            toggleJobSelected(job.job_uuid)
                            return
                          }
                          openJob(job.job_uuid)
                        }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-body">{jobDisplayName(job)}</p>
                            <p className="truncate text-small text-muted-foreground">
                              {job.pipeline_plaza_key} · {job.job_uuid.slice(0, 8)}
                            </p>
                          </div>
                          <span
                            className={cn(
                              'shrink-0 rounded-sm px-2 py-0.5 text-small capitalize',
                              statusClass(job.status),
                            )}
                          >
                            {job.status}
                          </span>
                        </div>
                      </button>
                    </div>
                  )
                })
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <Dialog
        open={Boolean(interruptedJob)}
        onClose={() => {}}
        title="This job was stopped when the server closed"
        description={`${
          PROGRAM_SHORT[interruptedJob?.program_code] || interruptedJob?.program_code || 'This job'
        } was still running. Run it again, or remove it. It will not start on its own.`}
      >
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={handleRemoveInterruptedJob}
          >
            Remove
          </Button>
          <Button type="button" disabled={busy} onClick={handleResumeInterruptedJob}>
            Run again
          </Button>
        </div>
      </Dialog>

      <Dialog
        open={scrapeModeOpen}
        onClose={() => setScrapeModeOpen(false)}
        title="How should scraping run?"
        description={
          activeProcess?.code === 'e06' || selectedProgram?.code === 'e06'
            ? 'No permit file uploaded. Choose live Parivahan scrape, or download the vehicle list and stop so you can scrape offline and attach the file later.'
            : 'No IHMCL scrape file uploaded. Choose live IHMCL scrape, or download the vehicle list and stop so you can scrape offline and attach the file later.'
        }
      >
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => queueJobWithScrapeMode('export')}
          >
            <Download className="h-4 w-4" />
            Download vehicles &amp; stop
          </Button>
          <Button
            type="button"
            disabled={busy}
            onClick={() => queueJobWithScrapeMode('live')}
          >
            <Play className="h-4 w-4" />
            Continue live scraping
          </Button>
        </div>
      </Dialog>
    </section>
  )
}
