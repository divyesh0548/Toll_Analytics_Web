import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, FileUp, Loader2, Play, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SearchableSelect } from '@/components/ui/searchable-select'
import {
  attachStagingInvalidFile,
  createExceptionJob,
  deleteExceptionJobFile,
  getAnnexureServerDefaults,
  getExceptionJob,
  listExceptionJobs,
  listExceptionPrograms,
  listPlazas,
  listStagingInvalidFiles,
  markExceptionJobFailed,
  startExceptionJob,
  uploadExceptionJobFile,
} from '@/lib/api'
import { cn, formatLocalDateTime } from '@/lib/utils'

const PROGRAM_SHORT = {
  full_exempt_e1_e2_e3_e13_e14: 'Exempt Query',
  e04: 'E04',
  e05_group: 'E05',
  valid_invalid_lookup: 'Valid/Invalid',
  e05: 'Incorrect FASTag',
  e06: 'E06',
  e07: 'E07',
  e09: 'E09',
  e10: 'E10',
  e15: 'E15',
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
      return 'bg-amber-500/15 text-amber-800 dark:text-amber-200'
    default:
      return 'bg-secondary text-secondary-foreground'
  }
}

export function ExceptionUploadsPage() {
  const [programs, setPrograms] = useState([])
  const [pipelineKeys, setPipelineKeys] = useState([])
  const [plazas, setPlazas] = useState([])
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedProgram, setSelectedProgram] = useState(null)
  const [selectedProcess, setSelectedProcess] = useState(null)

  const [plazaIdentifier, setPlazaIdentifier] = useState('')
  const [pipelinePlazaKey, setPipelinePlazaKey] = useState('')
  const [activeJob, setActiveJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [uploadingSlot, setUploadingSlot] = useState(null)
  const [uploadingNames, setUploadingNames] = useState([])
  const [notice, setNotice] = useState('')
  const [serverDefaults, setServerDefaults] = useState(null)
  const [stagingFiles, setStagingFiles] = useState([])
  const [stagingFileId, setStagingFileId] = useState('')

  const activeProcess = selectedProcess || processesFor(selectedProgram)[0] || null

  const loadCatalog = useCallback(async (program) => {
    const filterCode = jobFilterCode(program)
    const [catalog, plazaData, jobData] = await Promise.all([
      listExceptionPrograms(),
      listPlazas(),
      listExceptionJobs(undefined, filterCode || undefined),
    ])
    setPrograms(catalog.programs || [])
    setPipelineKeys(catalog.pipeline_plaza_keys || [])
    setPlazas(plazaData.plazas || [])
    setJobs(jobData.jobs || [])
  }, [])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        await loadCatalog(selectedProgram)
      } catch (err) {
        if (active) setError(err.message || 'Failed to load exception programs')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [loadCatalog, selectedProgram])

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
        const data = await getAnnexureServerDefaults(key)
        if (!cancelled) setServerDefaults(data)
      } catch {
        if (!cancelled) setServerDefaults(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [activeJob?.pipeline_plaza_key, pipelinePlazaKey, selectedProgram?.code])

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
      setNotice('Job created. Upload the required files, then Start.')
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

  async function handleUpload(slotKey, fileList) {
    if (!activeJob || !fileList?.length) return
    const files = Array.from(fileList)
    setUploadingSlot(slotKey)
    setUploadingNames(files.map((f) => f.name))
    setBusy(true)
    setError('')
    setNotice('')
    try {
      let job = activeJob
      for (const file of files) {
        const data = await uploadExceptionJobFile(activeJob.job_uuid, slotKey, file)
        job = data.job
      }
      setActiveJob(job)
      setNotice(
        files.length === 1
          ? `Uploaded ${files[0].name}`
          : `Uploaded ${files.length} files`,
      )
    } catch (err) {
      setError(err.message || 'Upload failed')
    } finally {
      setUploadingSlot(null)
      setUploadingNames([])
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

  async function handleStart() {
    if (!activeJob) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const data = await startExceptionJob(activeJob.job_uuid)
      setActiveJob(data.job)
      setNotice('Job queued. Progress updates automatically.')
    } catch (err) {
      setError(err.message || 'Could not start job')
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

  const stagingOptions = useMemo(
    () =>
      stagingFiles.map((f) => ({
        value: String(f.id),
        label: f.file_name || f.original_file_name || `file #${f.id}`,
        meta: formatLocalDateTime(f.created_at),
      })),
    [stagingFiles],
  )

  async function openJob(jobUuid) {
    setBusy(true)
    setError('')
    try {
      const data = await getExceptionJob(jobUuid)
      setActiveJob(data.job)
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

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading exception programs…</p>
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
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
                    const isUploading = uploadingSlot === slot.key
                    const defaults = slot.server_default ? serverDefaultForSlot(slot.key) : null
                    const hasServerFile = Boolean(defaults?.exists && defaults?.file_name)
                    const hasOverrideUpload = slotFiles.length > 0
                    const isInvalidPickSlot = Boolean(slot.or_staging_pick)
                    const hasInvalidReady = isInvalidPickSlot && slotFiles.length > 0

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
                              Pick one path: reuse a file from Valid/Invalid Lookup, or upload
                              a new file. Then click Start job.
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
                                    Latest files for this plaza first. Selecting one attaches it.
                                  </p>
                                </div>
                                {stagingOptions.length === 0 ? (
                                  <p className="text-small text-muted-foreground">
                                    None yet — run “Valid / Invalid Lookup” for this plaza first,
                                    or use upload on the right.
                                  </p>
                                ) : (
                                  <SearchableSelect
                                    value={stagingFileId}
                                    onChange={(value) => {
                                      setStagingFileId(value)
                                      if (value) handleAttachStaging(value)
                                    }}
                                    options={stagingOptions}
                                    placeholder="Choose existing invalid file…"
                                    disabled={busy}
                                  />
                                )}
                              </div>

                              <div className="space-y-3 rounded-sm border border-border bg-secondary/20 p-3">
                                <div>
                                  <p className="text-body font-medium">B. Upload new file</p>
                                  <p className="text-small text-muted-foreground">
                                    Use this if you already have an invalid_table CSV/Excel.
                                  </p>
                                </div>
                                <label
                                  className={cn(
                                    'inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-sm border border-border bg-background px-3 py-2 text-small hover:bg-accent',
                                    isUploading && 'pointer-events-none opacity-70',
                                  )}
                                >
                                  {isUploading ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Upload className="h-3.5 w-3.5" />
                                  )}
                                  {isUploading ? 'Uploading…' : 'Browse & upload invalid table'}
                                  <input
                                    type="file"
                                    className="hidden"
                                    accept={slot.accept}
                                    disabled={busy}
                                    onChange={(event) => {
                                      handleUpload(slot.key, event.target.files)
                                      event.target.value = ''
                                    }}
                                  />
                                </label>
                              </div>
                            </div>
                          ) : null}

                          {isUploading ? (
                            <div className="flex items-start gap-2 rounded-sm bg-amber-500/10 px-3 py-2 text-small text-amber-900 dark:text-amber-100">
                              <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
                              <div className="min-w-0">
                                <p className="font-medium">Uploading invalid table…</p>
                                <p className="truncate text-muted-foreground">
                                  {uploadingNames.join(', ')}
                                </p>
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
                          {canEdit ? (
                            <label
                              className={cn(
                                'inline-flex cursor-pointer items-center gap-2 rounded-sm border border-border px-3 py-1.5 text-small hover:bg-accent',
                                isUploading && 'pointer-events-none opacity-70',
                              )}
                            >
                              {isUploading ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Upload className="h-3.5 w-3.5" />
                              )}
                              {isUploading ? 'Uploading…' : hasServerFile ? 'Override' : 'Upload'}
                              <input
                                type="file"
                                className="hidden"
                                accept={slot.accept}
                                multiple={Boolean(slot.multiple)}
                                disabled={busy}
                                onChange={(event) => {
                                  handleUpload(slot.key, event.target.files)
                                  event.target.value = ''
                                }}
                              />
                            </label>
                          ) : null}
                        </div>

                        {hasServerFile && !hasOverrideUpload ? (
                          <div className="rounded-sm border border-dashed border-border bg-secondary/30 px-3 py-2 text-small">
                            <p className="text-body">
                              On server: <span className="font-medium">{defaults.file_name}</span>
                            </p>
                            <p className="text-muted-foreground">
                              No need to upload unless you want to override this default.
                            </p>
                          </div>
                        ) : null}

                        {hasServerFile && hasOverrideUpload ? (
                          <p className="text-small text-muted-foreground">
                            Using your upload instead of server default{' '}
                            <span className="font-medium">{defaults.file_name}</span>.
                          </p>
                        ) : null}

                        {isUploading ? (
                          <div className="flex items-start gap-2 rounded-sm bg-amber-500/10 px-3 py-2 text-small text-amber-900 dark:text-amber-100">
                            <Loader2 className="mt-0.5 h-4 w-4 animate-spin" />
                            <div className="min-w-0">
                              <p className="font-medium">Uploading to S3…</p>
                              <p className="truncate text-muted-foreground">
                                {uploadingNames.join(', ')}
                              </p>
                            </div>
                          </div>
                        ) : null}

                        {!isUploading && slotFiles.length === 0 && !hasServerFile ? (
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
                    <Button type="button" disabled={busy} onClick={handleStart}>
                      {busy && !uploadingSlot ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                      {activeJob.status === 'failed' ? 'Retry job' : 'Start job'}
                    </Button>
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
                    onClick={() => setActiveJob(null)}
                  >
                    New job for this program
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent jobs</CardTitle>
              <CardDescription>
                {selectedProgram.label}
                {selectedProgram.is_process_group
                  ? ' — both processes; named as plaza + date/time.'
                  : ' — named as plaza + date/time.'}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {jobs.length === 0 ? (
                <p className="text-body text-muted-foreground">No jobs yet.</p>
              ) : (
                jobs.slice(0, 20).map((job) => (
                  <button
                    key={job.job_uuid}
                    type="button"
                    className="flex w-full items-center justify-between gap-2 rounded-sm border border-border px-3 py-2 text-left hover:bg-accent/50"
                    onClick={() => openJob(job.job_uuid)}
                  >
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
                  </button>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </section>
  )
}
