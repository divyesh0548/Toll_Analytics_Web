import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, FileUp, Loader2, Play, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SearchableSelect } from '@/components/ui/searchable-select'
import {
  createExceptionJob,
  deleteExceptionJobFile,
  getExceptionJob,
  listExceptionJobs,
  listExceptionPrograms,
  listPlazas,
  markExceptionJobFailed,
  startExceptionJob,
  uploadExceptionJobFile,
} from '@/lib/api'
import { cn } from '@/lib/utils'

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

  const [plazaIdentifier, setPlazaIdentifier] = useState('')
  const [pipelinePlazaKey, setPipelinePlazaKey] = useState('')
  const [activeJob, setActiveJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const loadCatalog = useCallback(async () => {
    const [catalog, plazaData, jobData] = await Promise.all([
      listExceptionPrograms(),
      listPlazas(),
      listExceptionJobs(),
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

  // Poll active job while queued/running
  useEffect(() => {
    if (!activeJob?.job_uuid) return undefined
    if (!['queued', 'running'].includes(activeJob.status)) return undefined
    const timer = setInterval(async () => {
      try {
        const data = await getExceptionJob(activeJob.job_uuid)
        setActiveJob(data.job)
        if (['succeeded', 'failed'].includes(data.job.status)) {
          const jobData = await listExceptionJobs()
          setJobs(jobData.jobs || [])
        }
      } catch {
        /* ignore poll errors */
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [activeJob?.job_uuid, activeJob?.status])

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
    setBusy(true)
    setNotice('')
    setError('')
    try {
      const data = await createExceptionJob({
        program_code: FULL_EXEMPT_CODE,
        plaza_identifier: plazaIdentifier,
        pipeline_plaza_key: pipelinePlazaKey,
      })
      setActiveJob(data.job)
      setNotice('Job created. Upload the required files, then Start.')
      const jobData = await listExceptionJobs()
      setJobs(jobData.jobs || [])
    } catch (err) {
      setError(err.message || 'Could not create job')
    } finally {
      setBusy(false)
    }
  }

  async function handleUpload(slotKey, fileList) {
    if (!activeJob || !fileList?.length) return
    setBusy(true)
    setError('')
    try {
      let job = activeJob
      for (const file of Array.from(fileList)) {
        const data = await uploadExceptionJobFile(activeJob.job_uuid, slotKey, file)
        job = data.job
      }
      setActiveJob(job)
      setNotice('Upload saved to S3.')
    } catch (err) {
      setError(err.message || 'Upload failed')
    } finally {
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
      const jobData = await listExceptionJobs()
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

  async function openJob(jobUuid) {
    setBusy(true)
    setError('')
    try {
      const data = await getExceptionJob(jobUuid)
      setActiveJob(data.job)
      setSelectedProgram(programs.find((p) => p.code === data.job.program_code) || null)
      setPlazaIdentifier(data.job.plaza_identifier)
      setPipelinePlazaKey(data.job.pipeline_plaza_key)
    } catch (err) {
      setError(err.message || 'Could not load job')
    } finally {
      setBusy(false)
    }
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
                    Metrics: {(selectedProgram.group_exception_codes || []).join(', ')}
                  </CardDescription>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setSelectedProgram(null)
                    setActiveJob(null)
                  }}
                >
                  All programs
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {!activeJob ? (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label>Website plaza</Label>
                      <SearchableSelect
                        options={plazaOptions}
                        value={plazaIdentifier}
                        onChange={setPlazaIdentifier}
                        placeholder="Select plaza…"
                      />
                    </div>
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
                  </div>
                  <Button
                    type="button"
                    disabled={busy || !plazaIdentifier || !pipelinePlazaKey}
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
                    <code className="text-small">{activeJob.job_uuid.slice(0, 8)}…</code>
                    <span
                      className={cn(
                        'rounded-sm px-2 py-0.5 text-small capitalize',
                        statusClass(activeJob.status),
                      )}
                    >
                      {activeJob.status}
                    </span>
                    {selectedPlaza ? (
                      <span className="text-muted-foreground">· {selectedPlaza.plaza_name}</span>
                    ) : null}
                    <span className="text-muted-foreground">· {activeJob.pipeline_plaza_key}</span>
                  </div>

                  {(selectedProgram.input_slots || []).map((slot) => {
                    const slotFiles = (activeJob.files || []).filter((f) => f.slot === slot.key)
                    const canEdit = ['draft', 'failed'].includes(activeJob.status)
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
                            <label className="inline-flex cursor-pointer items-center gap-2 rounded-sm border border-border px-3 py-1.5 text-small hover:bg-accent">
                              <Upload className="h-3.5 w-3.5" />
                              Upload
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
                        {slotFiles.length === 0 ? (
                          <p className="text-small text-muted-foreground">No files yet.</p>
                        ) : (
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
                        )}
                      </div>
                    )
                  })}

                  {['draft', 'failed'].includes(activeJob.status) ? (
                    <Button type="button" disabled={busy} onClick={handleStart}>
                      {busy ? (
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
              <CardDescription>Open a draft/failed job to edit uploads and re-run.</CardDescription>
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
                      <p className="truncate text-body">{job.plaza_name || job.plaza_identifier}</p>
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
