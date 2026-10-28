import { useEffect, useState } from 'react'
import { Download, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  downloadExceptionJobOutput,
  listExceptionJobOutputs,
} from '@/lib/api'

export function LocalOutputDownloads({ jobUuid, enabled, title = 'Output files' }) {
  const [files, setFiles] = useState(null)
  const [error, setError] = useState('')
  const [busyPath, setBusyPath] = useState('')

  useEffect(() => {
    if (!enabled || !jobUuid) {
      setFiles(null)
      return undefined
    }
    let cancelled = false
    setError('')
    listExceptionJobOutputs(jobUuid)
      .then((data) => {
        if (!cancelled) setFiles(data.files || [])
      })
      .catch((err) => {
        if (!cancelled) {
          setFiles([])
          setError(err.message || 'Could not list output files')
        }
      })
    return () => {
      cancelled = true
    }
  }, [enabled, jobUuid])

  if (!enabled || !jobUuid) return null

  async function handleDownload(file) {
    setBusyPath(file.relative_path)
    setError('')
    try {
      await downloadExceptionJobOutput(jobUuid, file.relative_path, file.name)
    } catch (err) {
      setError(err.message || 'Download failed')
    } finally {
      setBusyPath('')
    }
  }

  return (
    <div className="space-y-2 rounded-sm border border-border bg-secondary/30 px-3 py-3">
      <p className="text-body font-medium">{title}</p>
      <p className="text-small text-muted-foreground">
        Metrics were not updated and these files were not uploaded. Download them here.
      </p>
      {files === null ? (
        <p className="flex items-center gap-2 text-small text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Looking for output files…
        </p>
      ) : null}
      {files && files.length === 0 ? (
        <p className="text-small text-muted-foreground">
          No output files are on the server for this run.
        </p>
      ) : null}
      {files && files.length > 0 ? (
        <ul className="space-y-1">
          {files.map((file) => (
            <li
              key={file.relative_path}
              className="flex flex-wrap items-center justify-between gap-2"
            >
              <span className="truncate text-body">{file.name}</span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busyPath === file.relative_path}
                onClick={() => handleDownload(file)}
              >
                {busyPath === file.relative_path ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Download
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <p className="text-small text-red-600 dark:text-red-300">{error}</p> : null}
    </div>
  )
}
