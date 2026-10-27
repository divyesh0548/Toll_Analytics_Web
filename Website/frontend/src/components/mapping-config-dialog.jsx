import { useEffect, useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { useToast } from '@/components/toast-provider'
import {
  addMappingAlias,
  addMappingListItem,
  deleteMappingAlias,
  deleteMappingListItem,
  getMappingConfig,
  updateMappingAlias,
  updateMappingListItem,
  updateMappingSetting,
} from '@/lib/api'

const ALIAS_LABEL = {
  vehicle_class: 'Names that map to this class',
  mop: 'Names that map to this payment mode',
  column_alias: 'Header names',
  header_keyword: 'Keywords',
  tc_index: 'Class names for this index',
  journey_type: 'Names that map to this journey',
  pass_type: 'Accepted values',
}

const SETTING_HELP = {
  header_scan_rows: 'How many rows to scan when looking for a header.',
  min_header_matches: 'How many header names must match before a row is treated as the header.',
  overrides_by_source: 'Lower match counts used for specific file sources.',
}

const SOURCE_LABELS = {
  vrn_thin: 'VRN thin files',
  e11: 'E11',
  e15: 'E15',
}

function sourceLabel(key) {
  if (SOURCE_LABELS[key]) return SOURCE_LABELS[key]
  const text = String(key || '').replace(/_/g, ' ')
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : key
}

function ValueRow({ value, busy, onSave, onRemove, label }) {
  const [text, setText] = useState(value)
  useEffect(() => {
    setText(value)
  }, [value])
  const dirty = text.trim() !== value
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="min-w-[12rem] flex-1">
        <span className="sr-only">{label}</span>
        <input
          className="h-8 w-full rounded-sm border border-border bg-background px-2 text-small"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      <Button type="button" size="sm" disabled={!dirty || busy} onClick={() => onSave(text.trim())}>
        Save
      </Button>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onRemove}>
        Remove
      </Button>
    </div>
  )
}

function AddRow({ label, placeholder, busy, onAdd }) {
  const [text, setText] = useState('')
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="min-w-[12rem] flex-1 space-y-1">
        <span className="block text-small text-muted-foreground">{label}</span>
        <input
          className="h-8 w-full rounded-sm border border-border bg-background px-2 text-small"
          value={text}
          placeholder={placeholder}
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={busy || !text.trim()}
        onClick={async () => {
          const ok = await onAdd(text.trim())
          if (ok) setText('')
        }}
      >
        Add
      </Button>
    </div>
  )
}

export function MappingConfigDialog({ open, onClose }) {
  const { showToast } = useToast()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [section, setSection] = useState('')
  const [busyKey, setBusyKey] = useState('')
  const [error, setError] = useState('')
  const [overrideDraft, setOverrideDraft] = useState({})
  const [newSource, setNewSource] = useState('')
  const [newSourceValue, setNewSourceValue] = useState('')

  useEffect(() => {
    if (!open) return undefined
    let cancelled = false
    setLoading(true)
    setError('')
    getMappingConfig()
      .then((payload) => {
        if (cancelled) return
        setData(payload)
        const first = payload?.domains?.[0]?.code || (payload?.settings?.length ? 'settings' : '')
        setSection((current) => current || first)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load config')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open])

  const settings = data?.settings || []
  const overrides = useMemo(
    () => settings.find((row) => row.key === 'overrides_by_source')?.value || {},
    [settings],
  )

  useEffect(() => {
    setOverrideDraft(overrides && typeof overrides === 'object' ? { ...overrides } : {})
  }, [overrides])

  const sections = useMemo(() => {
    const rows = (data?.domains || []).map((domain) => ({
      id: domain.code,
      label: domain.label,
    }))
    if (settings.length) rows.push({ id: 'settings', label: 'Detection' })
    return rows
  }, [data, settings.length])

  const activeDomain = (data?.domains || []).find((domain) => domain.code === section) || null

  async function runChange(key, action) {
    setBusyKey(key)
    setError('')
    try {
      const payload = await action()
      setData(payload)
      showToast('Config saved', 'success')
      return true
    } catch (err) {
      setError(err.message || 'Could not save config')
      return false
    } finally {
      setBusyKey('')
    }
  }

  const empty = !loading && data && !(data.domains || []).length && !settings.length

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Config"
      description="Stored mapping values. Edit names, lists, and detection settings. These edits are saved in the database."
      className="mapping-config-dialog max-w-5xl"
    >
      {loading ? (
        <p className="flex items-center gap-2 text-body text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading stored values…
        </p>
      ) : null}
      {error ? (
        <p className="mb-3 rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-body">
          {error}
        </p>
      ) : null}
      {empty ? (
        <p className="text-body text-muted-foreground">
          No mapping values are stored yet. From Website/backend, run{' '}
          <span className="font-medium text-foreground">flask --app run:app seed-shared-config</span>{' '}
          once, then open Config again.
        </p>
      ) : null}
      {sections.length ? (
        <div className="mb-4 flex flex-wrap gap-2">
          {sections.map((item) => (
            <Button
              key={item.id}
              type="button"
              size="sm"
              variant={section === item.id ? 'default' : 'outline'}
              onClick={() => setSection(item.id)}
            >
              {item.label}
            </Button>
          ))}
        </div>
      ) : null}

      {activeDomain ? (
        <div className="space-y-6">
          {(activeDomain.lists || []).map((list) => (
            <section key={list.list_key} className="space-y-3">
              <h3 className="text-header">{list.label}</h3>
              <p className="text-small text-muted-foreground">
                Values in this list are skipped and are not mapped to a group.
              </p>
              <div className="space-y-2">
                {(list.items || []).map((item) => (
                  <ValueRow
                    key={item.id}
                    value={item.value}
                    label={list.label}
                    busy={busyKey === `list-${item.id}`}
                    onSave={(value) =>
                      runChange(`list-${item.id}`, () => updateMappingListItem(item.id, value))
                    }
                    onRemove={() =>
                      runChange(`list-${item.id}`, () => deleteMappingListItem(item.id))
                    }
                  />
                ))}
              </div>
              <AddRow
                label={`Add ${list.label.toLowerCase()} value`}
                placeholder="New value"
                busy={busyKey === `add-list-${list.list_key}`}
                onAdd={(value) =>
                  runChange(`add-list-${list.list_key}`, () =>
                    addMappingListItem(activeDomain.code, list.list_key, value),
                  )
                }
              />
            </section>
          ))}

          {(activeDomain.groups || []).map((group) => (
            <section key={group.id} className="space-y-3 border-t border-border pt-4">
              <div>
                <h3 className="text-header">{group.label}</h3>
                {group.key !== group.label ? (
                  <p className="text-small text-muted-foreground">Stored key: {group.key}</p>
                ) : null}
                {group.db_column ? (
                  <p className="text-small text-muted-foreground">
                    Analytics column: {group.db_column}
                  </p>
                ) : null}
                {group.notes ? (
                  <p className="text-small text-muted-foreground">{group.notes}</p>
                ) : null}
              </div>
              <p className="text-small font-medium text-foreground">
                {ALIAS_LABEL[activeDomain.code] || 'Aliases'}
              </p>
              <div className="space-y-2">
                {(group.aliases || []).map((alias) => (
                  <ValueRow
                    key={alias.id}
                    value={alias.alias}
                    label={group.label}
                    busy={busyKey === `alias-${alias.id}`}
                    onSave={(value) =>
                      runChange(`alias-${alias.id}`, () => updateMappingAlias(alias.id, value))
                    }
                    onRemove={() =>
                      runChange(`alias-${alias.id}`, () => deleteMappingAlias(alias.id))
                    }
                  />
                ))}
              </div>
              <AddRow
                label="Add value"
                placeholder="New value"
                busy={busyKey === `add-alias-${group.id}`}
                onAdd={(value) =>
                  runChange(`add-alias-${group.id}`, () => addMappingAlias(group.id, value))
                }
              />
            </section>
          ))}
        </div>
      ) : null}

      {section === 'settings' && settings.length ? (
        <div className="space-y-6">
          {settings
            .filter((row) => row.key !== 'overrides_by_source')
            .map((row) => (
              <NumberSetting
                key={row.key}
                row={row}
                busy={busyKey === `setting-${row.key}`}
                onSave={(value) =>
                  runChange(`setting-${row.key}`, () => updateMappingSetting(row.key, value))
                }
              />
            ))}
          {settings.some((row) => row.key === 'overrides_by_source') ? (
            <section className="space-y-3 border-t border-border pt-4">
              <h3 className="text-header">Header match overrides by source</h3>
              <p className="text-small text-muted-foreground">
                {SETTING_HELP.overrides_by_source}
              </p>
              <div className="space-y-2">
                {Object.keys(overrideDraft).map((key) => (
                  <label key={key} className="flex flex-wrap items-center gap-3">
                    <span className="w-40 text-small">{sourceLabel(key)}</span>
                    <input
                      type="number"
                      min="0"
                      className="h-8 w-24 rounded-sm border border-border bg-background px-2 text-small"
                      value={overrideDraft[key]}
                      onChange={(event) =>
                        setOverrideDraft((prev) => ({ ...prev, [key]: event.target.value }))
                      }
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        setOverrideDraft((prev) => {
                          const next = { ...prev }
                          delete next[key]
                          return next
                        })
                      }
                    >
                      Remove
                    </Button>
                  </label>
                ))}
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <label className="space-y-1">
                  <span className="block text-small text-muted-foreground">Source name</span>
                  <input
                    className="h-8 w-40 rounded-sm border border-border bg-background px-2 text-small"
                    value={newSource}
                    onChange={(event) => setNewSource(event.target.value)}
                  />
                </label>
                <label className="space-y-1">
                  <span className="block text-small text-muted-foreground">Minimum matches</span>
                  <input
                    type="number"
                    min="0"
                    className="h-8 w-24 rounded-sm border border-border bg-background px-2 text-small"
                    value={newSourceValue}
                    onChange={(event) => setNewSourceValue(event.target.value)}
                  />
                </label>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={!newSource.trim() || newSourceValue === ''}
                  onClick={() => {
                    setOverrideDraft((prev) => ({
                      ...prev,
                      [newSource.trim()]: Number(newSourceValue),
                    }))
                    setNewSource('')
                    setNewSourceValue('')
                  }}
                >
                  Add source
                </Button>
              </div>
              <Button
                type="button"
                size="sm"
                disabled={busyKey === 'setting-overrides_by_source'}
                onClick={() => {
                  const payload = {}
                  for (const [key, raw] of Object.entries(overrideDraft)) {
                    payload[key] = Number(raw)
                  }
                  runChange('setting-overrides_by_source', () =>
                    updateMappingSetting('overrides_by_source', payload),
                  )
                }}
              >
                Save overrides
              </Button>
            </section>
          ) : null}
        </div>
      ) : null}
    </Dialog>
  )
}

function NumberSetting({ row, busy, onSave }) {
  const [text, setText] = useState(String(row.value ?? ''))
  useEffect(() => {
    setText(String(row.value ?? ''))
  }, [row.value])
  const dirty = String(text) !== String(row.value ?? '')
  return (
    <section className="space-y-2">
      <h3 className="text-header">{row.label}</h3>
      {SETTING_HELP[row.key] ? (
        <p className="text-small text-muted-foreground">{SETTING_HELP[row.key]}</p>
      ) : null}
      <div className="flex items-center gap-2">
        <input
          type="number"
          min="0"
          className="h-8 w-28 rounded-sm border border-border bg-background px-2 text-small"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Button type="button" size="sm" disabled={!dirty || busy} onClick={() => onSave(Number(text))}>
          Save
        </Button>
      </div>
    </section>
  )
}
