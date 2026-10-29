import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
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

const EMPTY_OVERRIDES = {}
const EMPTY_SETTINGS = []

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

function sortRows(rows, key) {
  return [...rows].sort((a, b) =>
    String(a[key]).localeCompare(String(b[key]), undefined, { sensitivity: 'base' }),
  )
}

function withAlias(data, canonicalId, alias) {
  return {
    ...data,
    domains: data.domains.map((domain) => ({
      ...domain,
      groups: domain.groups.map((group) => {
        if (group.id !== canonicalId) return group
        const aliases = sortRows(
          [...group.aliases.filter((row) => row.id !== alias.id), { id: alias.id, alias: alias.alias }],
          'alias',
        )
        return { ...group, aliases }
      }),
    })),
  }
}

function withoutAlias(data, aliasId) {
  return {
    ...data,
    domains: data.domains.map((domain) => ({
      ...domain,
      groups: domain.groups.map((group) => ({
        ...group,
        aliases: group.aliases.filter((row) => row.id !== aliasId),
      })),
    })),
  }
}

function withListItem(data, item) {
  return {
    ...data,
    domains: data.domains.map((domain) => {
      if (domain.code !== item.domain_code) return domain
      return {
        ...domain,
        lists: domain.lists.map((list) => {
          if (list.list_key !== item.list_key) return list
          return {
            ...list,
            items: sortRows(
              [...list.items.filter((row) => row.id !== item.id), { id: item.id, value: item.value }],
              'value',
            ),
          }
        }),
      }
    }),
  }
}

function withoutListItem(data, itemId) {
  return {
    ...data,
    domains: data.domains.map((domain) => ({
      ...domain,
      lists: domain.lists.map((list) => ({
        ...list,
        items: list.items.filter((row) => row.id !== itemId),
      })),
    })),
  }
}

function withSetting(data, setting) {
  return {
    ...data,
    settings: (data.settings || []).map((row) =>
      row.key === setting.key ? { ...row, value: setting.value } : row,
    ),
  }
}

function ValueChip({ value, busy, onSave, onRemove, label }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(value)
  const inputRef = useRef(null)
  const rootRef = useRef(null)

  useEffect(() => {
    setText(value)
  }, [value])

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  useEffect(() => {
    if (!menuOpen) return undefined
    function onPointerDown(event) {
      if (!rootRef.current?.contains(event.target)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [menuOpen])

  function cancel() {
    setText(value)
    setEditing(false)
  }

  function save() {
    const next = text.trim()
    if (!next || next === value || busy) return
    setEditing(false)
    onSave(next)
  }

  if (editing) {
    return (
      <span className="inline-flex max-w-full flex-wrap items-center gap-1.5">
        <input
          ref={inputRef}
          aria-label={label}
          className="h-8 min-w-[12rem] rounded-sm border border-border bg-background px-2 text-small"
          value={text}
          disabled={busy}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              save()
            }
            if (event.key === 'Escape') {
              event.preventDefault()
              event.stopPropagation()
              cancel()
            }
          }}
        />
        <Button
          type="button"
          size="sm"
          disabled={busy || !text.trim() || text.trim() === value}
          onClick={save}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Save
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={cancel}>
          Cancel
        </Button>
      </span>
    )
  }

  return (
    <span ref={rootRef} className="relative inline-flex">
      <button
        type="button"
        className="max-w-[16rem] truncate rounded-sm border border-border bg-muted/50 px-2 py-1 text-small"
        aria-expanded={menuOpen}
        aria-label={value}
        disabled={busy}
        onClick={() => setMenuOpen((open) => !open)}
      >
        {busy ? <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> : null}
        {value}
      </button>
      {menuOpen ? (
        <span className="config-word-actions absolute left-0 top-full z-20 mt-1 flex gap-1 rounded-sm border border-border bg-card p-1 shadow-md">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              setMenuOpen(false)
              setEditing(true)
            }}
          >
            Edit
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              setMenuOpen(false)
              onRemove()
            }}
          >
            Delete
          </Button>
        </span>
      ) : null}
    </span>
  )
}

function AddChip({ busy, onAdd, placeholder }) {
  const [text, setText] = useState('')
  const trimmed = text.trim()

  async function save() {
    if (!trimmed || busy) return
    const ok = await onAdd(trimmed)
    if (ok) setText('')
  }

  return (
    <div className="mt-2 flex w-full flex-wrap items-center gap-2">
      <input
        className="h-8 min-w-[14rem] flex-1 rounded-sm border border-border bg-background px-2 text-small placeholder:text-muted-foreground"
        value={text}
        placeholder={placeholder}
        disabled={busy}
        aria-label={placeholder}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return
          event.preventDefault()
          save()
        }}
      />
      <Button type="button" size="sm" disabled={busy || !trimmed} onClick={save}>
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        Save
      </Button>
    </div>
  )
}

export function MappingConfigDialog({ open, onClose }) {
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

  const settings = data?.settings ?? EMPTY_SETTINGS
  const overrides = useMemo(() => {
    const value = settings.find((row) => row.key === 'overrides_by_source')?.value
    return value && typeof value === 'object' ? value : EMPTY_OVERRIDES
  }, [settings])

  useEffect(() => {
    setOverrideDraft((current) => {
      if (overrides === EMPTY_OVERRIDES) {
        return current && Object.keys(current).length === 0 ? current : {}
      }
      return { ...overrides }
    })
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

  async function commit(key, action, apply) {
    setBusyKey(key)
    setError('')
    try {
      const result = await action()
      setData((prev) => (prev ? apply(prev, result) : prev))
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
      description="Click a word for Edit and Delete. Type a new word and click Save."
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
              <div className="flex flex-wrap items-start gap-1.5">
                {(list.items || []).map((item) => (
                  <ValueChip
                    key={item.id}
                    value={item.value}
                    label={list.label}
                    busy={busyKey === `list-${item.id}`}
                    onSave={(value) =>
                      commit(
                        `list-${item.id}`,
                        () => updateMappingListItem(item.id, value),
                        (prev) => withListItem(prev, { id: item.id, value, domain_code: activeDomain.code, list_key: list.list_key }),
                      )
                    }
                    onRemove={() =>
                      commit(
                        `list-${item.id}`,
                        () => deleteMappingListItem(item.id),
                        (prev) => withoutListItem(prev, item.id),
                      )
                    }
                  />
                ))}
                <AddChip
                  placeholder="Type a new word"
                  busy={busyKey === `add-list-${list.list_key}`}
                  onAdd={(value) =>
                    commit(
                      `add-list-${list.list_key}`,
                      () => addMappingListItem(activeDomain.code, list.list_key, value),
                      (prev, result) => withListItem(prev, result.list_item),
                    )
                  }
                />
              </div>
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
              <div className="flex flex-wrap items-start gap-1.5">
                {(group.aliases || []).map((alias) => (
                  <ValueChip
                    key={alias.id}
                    value={alias.alias}
                    label={group.label}
                    busy={busyKey === `alias-${alias.id}`}
                    onSave={(value) =>
                      commit(
                        `alias-${alias.id}`,
                        () => updateMappingAlias(alias.id, value),
                        (prev) => withAlias(prev, group.id, { id: alias.id, alias: value }),
                      )
                    }
                    onRemove={() =>
                      commit(
                        `alias-${alias.id}`,
                        () => deleteMappingAlias(alias.id),
                        (prev) => withoutAlias(prev, alias.id),
                      )
                    }
                  />
                ))}
                <AddChip
                  placeholder="Type a new word"
                  busy={busyKey === `add-alias-${group.id}`}
                  onAdd={(value) =>
                    commit(
                      `add-alias-${group.id}`,
                      () => addMappingAlias(group.id, value),
                      (prev, result) => withAlias(prev, group.id, result.alias),
                    )
                  }
                />
              </div>
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
                  commit(
                    `setting-${row.key}`,
                    () => updateMappingSetting(row.key, value),
                    (prev, result) => withSetting(prev, result.setting),
                  )
                }
              />
            ))}
          {settings.some((row) => row.key === 'overrides_by_source') ? (
            <section className="space-y-3 border-t border-border pt-4">
              <h3 className="text-header">Header match overrides by source</h3>
              <p className="text-small text-muted-foreground">
                {SETTING_HELP.overrides_by_source}
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.keys(overrideDraft).map((key) => (
                  <label key={key} className="group inline-flex items-center gap-2 rounded-sm border border-border bg-muted/40 py-1 pl-2 pr-1">
                    <span className="text-small">{sourceLabel(key)}</span>
                    <input
                      type="number"
                      min="0"
                      aria-label={`${sourceLabel(key)} minimum matches`}
                      className="h-7 w-16 rounded-sm border border-border bg-background px-2 text-small"
                      value={overrideDraft[key]}
                      onChange={(event) =>
                        setOverrideDraft((prev) => ({ ...prev, [key]: event.target.value }))
                      }
                    />
                    <button
                      type="button"
                      className="rounded-sm p-0.5 text-muted-foreground opacity-0 hover:text-foreground group-hover:opacity-100 focus:opacity-100"
                      aria-label={`Remove ${sourceLabel(key)}`}
                      onClick={() =>
                        setOverrideDraft((prev) => {
                          const next = { ...prev }
                          delete next[key]
                          return next
                        })
                      }
                    >
                      <X className="h-3 w-3" />
                    </button>
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
                  commit(
                    'setting-overrides_by_source',
                    () => updateMappingSetting('overrides_by_source', payload),
                    (prev, result) => withSetting(prev, result.setting),
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

  const unchanged = String(text) === String(row.value ?? '')

  function commitValue() {
    if (busy || unchanged || text === '') return
    onSave(Number(text))
  }

  return (
    <section className="space-y-2">
      <h3 className="text-header">{row.label}</h3>
      {SETTING_HELP[row.key] ? (
        <p className="text-small text-muted-foreground">{SETTING_HELP[row.key]}</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="number"
          min="0"
          className="h-8 w-28 rounded-sm border border-border bg-background px-2 text-small"
          value={text}
          disabled={busy}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              commitValue()
            }
          }}
        />
        <Button type="button" size="sm" disabled={busy || unchanged || text === ''} onClick={commitValue}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Save
        </Button>
      </div>
    </section>
  )
}
