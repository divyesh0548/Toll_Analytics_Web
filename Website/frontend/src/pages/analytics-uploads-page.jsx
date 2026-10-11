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
  listAnalyticsUploadPrograms,
  listExceptionJobs,
  listPlazas,
  markExceptionJobFailed,
  startExceptionJob,
  uploadExceptionJobFile,
} from '@/lib/api'
import { cn, formatLocalDateTime } from '@/lib/utils'

function jobDisplayName(job) {
  if (!job) return ''
  const plaza = job.plaza_name || job.plaza_identifier || 'Job'
  const when = formatLocalDateTime(job.created_at)
  return when && when !== '—' ? `${plaza} · ${when}` : plaza
}

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

export function AnalyticsUploadsPage() {
  const [programs, setPrograms] = useState([])
  const [plazas, setPlazas] = useState([])
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedProgram, setSelectedProgram] = useState(null)
  const [plazaIdentifier, setPlazaIdentifier] = useState('')
  const [activeJob, setActiveJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [uploadingSlot, setUploadingSlot] = useState(null)
  const [uploadingNames, setUploadingNames] = useState([])
  const [notice, setNotice] = useState('')

  const loadCatalog = useCallback(async (program) => {
    const filterCode = program?.code
    const [catalog, plazaData, jobData] = await Promise.all([
      listAnalyticsUploadPrograms(),
      listPlazas(),
      listExceptionJobs(undefined, filterCode || 'analytics_vrn_etc'),
    ])
    setPrograms(catalog.programs || [])
    setPlazas(plazaData.plazas || [])
    setJobs(jobData.jobs || [])
  }, [])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        await loadCatalog(selectedProgram)
      } catch (err) {
        if (active) setError(err.message || 'Failed to load analytics upload programs')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [loadCatalog, selectedProgram])

  useEffect(() => {
    if (!selectedProgram && programs.length === 1 && programs[0].enabled) {
      setSelectedProgram(programs[0])
    }
  }, [programs, selectedProgram])

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
            selectedProgram?.code || 'analytics_vrn_etc',
          )
          setJobs(jobData.jobs || [])
        }
      } catch {
        /* ignore poll errors */
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [activeJob?.job_uuid, activeJob?.status, selectedProgram?.code])

  const plazaOptions = useMemo(
    () =>
      plazas.map((p) => ({
        value: p.plaza_identifier,
        label: p.plaza_name,
        meta: p.plaza_code || '',
      })),
    [plazas],
  )

  async function handleCreateJob() {
    if (!selectedProgram?.code) {
      setError('Select a program before creating a job.')
      return
    }
    setBusy(true)
    setNotice('')
    setError('')
    try {
      const data = await createExceptionJob({
        program_code: selectedProgram.code,
        plaza_identifier: plazaIdentifier,
      })
      setActiveJob(data.job)
      setNotice('Job created. Upload VRN (and optional ETC), then Start.')
      const jobData = await listExceptionJobs(undefined, selectedProgram.code)
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
      setNotice('Job marked failed. You can edit files and Retry.')
      const jobData = await listExceptionJobs(undefined, selectedProgram?.code)
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
      const parent = programs.find((p) => p.code === data.job.program_code) || null
      setSelectedProgram(parent)
      setPlazaIdentifier(data.job.plaza_identifier)
    } catch (err) {
      setError(err.message || 'Could not load job')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading analytics upload…</p>
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
            Analytics
          </p>
          <h1 className="text-display">VRN / ETC upload</h1>
          <p className="max-w-2xl text-body text-muted-foreground">
            Upload plaza VRN and optional ETC workbooks to S3, then queue the plaza ETL.
            Metrics update only when the new value is greater. S3 inputs are removed only
            after a successful run; failed jobs keep files for retry.
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
                  <CardTitle className="text-subheader">{program.label}</CardTitle>
                  <CardDescription>{program.description}</CardDescription>
                </CardHeader>
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
                  <CardDescription>{selectedProgram.description}</CardDescription>
                </div>
                {programs.length > 1 ? (
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
                ) : null}
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {!activeJob ? (
                <>
                  <div className="space-y-2">
                    <Label>Plaza</Label>
                    <SearchableSelect
                      options={plazaOptions}
                      value={plazaIdentifier}
                      onChange={setPlazaIdentifier}
                      placeholder="Select plaza…"
                    />
                  </div>
                  <Button
                    type="button"
                    disabled={busy || !plazaIdentifier || !selectedProgram?.code}
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

                  {(selectedProgram.input_slots || []).map((slot) => {
                    const slotFiles = (activeJob.files || []).filter((f) => f.slot === slot.key)
                    const canEdit = ['draft', 'failed'].includes(activeJob.status)
                    const isUploading = uploadingSlot === slot.key

                    return (
                      <div key={slot.key} className="space-y-2 rounded-sm border border-border p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-subheader">
                            {slot.label}
                            {slot.required ? (
                              <span className="text-primary"> *</span>
                            ) : (
                              <span className="text-small text-muted-foreground"> (optional)</span>
                            )}
                          </p>
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
                              {isUploading ? 'Uploading…' : 'Upload'}
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
                        {isUploading ? (
                          <p className="truncate text-small text-muted-foreground">
                            {uploadingNames.join(', ')}
                          </p>
                        ) : null}
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
                                    size="sm"
                                    disabled={busy}
                                    onClick={() => handleDeleteFile(file.id)}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )
                  })}

                  {activeJob.progress_message ? (
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-sm bg-secondary/40 p-3 text-small">
                      {activeJob.progress_message}
                    </pre>
                  ) : null}
                  {activeJob.error_message ? (
                    <p className="text-body text-red-700 dark:text-red-300">
                      {activeJob.error_message}
                    </p>
                  ) : null}

                  <div className="flex flex-wrap gap-2">
                    {['draft', 'failed'].includes(activeJob.status) ? (
                      <Button type="button" disabled={busy} onClick={handleStart}>
                        {busy ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                        {activeJob.status === 'failed' ? 'Retry' : 'Start job'}
                      </Button>
                    ) : null}
                    {['queued', 'running'].includes(activeJob.status) ? (
                      <Button
                        type="button"
                        variant="outline"
                        disabled={busy}
                        onClick={handleMarkFailed}
                      >
                        Mark failed
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy}
                      onClick={() => {
                        setActiveJob(null)
                        setNotice('')
                      }}
                    >
                      New job
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent jobs</CardTitle>
              <CardDescription>Open a failed job to adjust files and retry.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {jobs.length === 0 ? (
                <p className="text-small text-muted-foreground">No jobs yet.</p>
              ) : (
                jobs.map((job) => (
                  <button
                    key={job.job_uuid}
                    type="button"
                    className="flex w-full items-center justify-between gap-2 rounded-sm border border-border px-3 py-2 text-left hover:bg-accent/50"
                    onClick={() => openJob(job.job_uuid)}
                  >
                    <span className="truncate text-body">{jobDisplayName(job)}</span>
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
