import { RangeSlider } from '@mantine/core'
import { CalendarDays, ChartNoAxesCombined, Filter, RotateCcw, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'wouter'

import {
  type ExperimentFilters,
  type ExperimentFilterOptions,
  useExperimentFilterOptions,
  useExperiments,
} from '../api/experiments'
import { ExperimentLoadingPanel } from '../components/ExperimentLoadingPanel'

const pageSizes = [25, 50, 100]

function numberOrUndefined(value: string): number | undefined {
  const number = Number(value)
  return value.trim() && Number.isFinite(number) ? number : undefined
}

function formatNumber(value: number | null, digits = 3): string {
  return value === null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function formatDate(value: number): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(value * 1000)
}

function filtersFromQuery(search: string): ExperimentFilters {
  const params = new URLSearchParams(search)
  const numericKeys = [
    'created_min',
    'created_max',
    'min_actual_dose',
    'max_actual_dose',
    'min_target_dose',
    'max_target_dose',
    'min_runtime',
    'max_runtime',
  ] as const
  const filters: ExperimentFilters = {}
  for (const key of ['name', 'zr_filter', 'sample', 'operator'] as const) {
    const value = params.get(key)
    if (value) filters[key] = value
  }
  for (const key of numericKeys) {
    const value = params.get(key)
    if (value) filters[key] = numberOrUndefined(value)
  }
  return filters
}

function dateInputValue(timestamp: number | undefined): string {
  if (timestamp === undefined) return ''
  const date = new Date(timestamp * 1000)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function timestampForDate(value: string, endOfDay = false): number | undefined {
  if (!value) return undefined
  const [year, month, day] = value.split('-').map(Number)
  if (![year, month, day].every(Number.isFinite)) return undefined
  const timestamp = new Date(year, month - 1, day + (endOfDay ? 1 : 0)).getTime() / 1000
  return endOfDay ? timestamp - 0.001 : timestamp
}

type RangeKeys =
  | ['min_actual_dose', 'max_actual_dose']
  | ['min_target_dose', 'max_target_dose']
  | ['min_runtime', 'max_runtime']

type CategoricalFilter = 'sample' | 'operator' | 'zr_filter'

const otherOption = '__custom_value__'

function PresetFilter({
  label,
  filterKey,
  value,
  choices,
  showOther,
  onSelect,
  onChange,
}: {
  label: string
  filterKey: CategoricalFilter
  value: string | undefined
  choices: string[]
  showOther: boolean
  onSelect: (filterKey: CategoricalFilter, value: string) => void
  onChange: (filterKey: CategoricalFilter, value: string) => void
}) {
  const selectedValue = showOther ? otherOption : value ?? ''
  return (
    <div className="preset-filter">
      <label>{label}
        <select value={selectedValue} onChange={(event) => onSelect(filterKey, event.target.value)}>
          <option value="">Any {label.toLowerCase()}</option>
          {choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
          <option value={otherOption}>Other</option>
        </select>
      </label>
      {showOther && <label>Other {label.toLowerCase()}<input value={value ?? ''} onChange={(event) => onChange(filterKey, event.target.value)} /></label>}
    </div>
  )
}

function rangeStep(minimum: number, maximum: number): number {
  const span = maximum - minimum
  if (span <= 1) return 0.01
  if (span <= 10) return 0.1
  if (span <= 100) return 1
  return Math.max(1, Math.round(span / 100))
}

function rangeInputValue(value: number): string {
  return String(value)
}

function parseRangeInput(value: string): number | null {
  const parsed = Number(value)
  return value.trim() && Number.isFinite(parsed) ? parsed : null
}

function RangeFilter({
  label,
  minimum,
  maximum,
  value,
  onChange,
  unit,
}: {
  label: string
  minimum: number | null
  maximum: number | null
  value: [number | undefined, number | undefined]
  onChange: (value: [number, number]) => void
  unit: string
}) {
  const lowerBound = minimum ?? 0
  const upperBound = maximum ?? lowerBound
  const selectedMinimum = Math.max(lowerBound, Math.min(value[0] ?? lowerBound, upperBound))
  const selectedMaximum = Math.max(lowerBound, Math.min(value[1] ?? upperBound, upperBound))
  const selected: [number, number] = [
    selectedMinimum,
    selectedMaximum,
  ]
  const [minimumText, setMinimumText] = useState(() => rangeInputValue(selected[0]))
  const [maximumText, setMaximumText] = useState(() => rangeInputValue(selected[1]))

  useEffect(() => {
    setMinimumText(rangeInputValue(selectedMinimum))
    setMaximumText(rangeInputValue(selectedMaximum))
  }, [selectedMaximum, selectedMinimum])

  if (minimum === null || maximum === null) {
    return <div className="range-filter is-disabled"><span>{label}</span><small>No indexed values</small></div>
  }
  if (minimum === maximum) {
    return <div className="range-filter is-disabled"><span>{label}</span><small>{formatNumber(minimum)} {unit}</small></div>
  }
  const applyMinimum = (parsed: number) => {
    onChange([Math.max(minimum, Math.min(parsed, selected[1])), selected[1]])
  }
  const applyMaximum = (parsed: number) => {
    onChange([selected[0], Math.max(selected[0], Math.min(parsed, maximum))])
  }
  const commitMinimum = () => {
    const parsed = parseRangeInput(minimumText)
    if (parsed === null) setMinimumText(rangeInputValue(selected[0]))
    else applyMinimum(parsed)
  }
  const commitMaximum = () => {
    const parsed = parseRangeInput(maximumText)
    if (parsed === null) setMaximumText(rangeInputValue(selected[1]))
    else applyMaximum(parsed)
  }
  const changeMinimum = (text: string) => {
    setMinimumText(text)
    const parsed = parseRangeInput(text)
    if (parsed !== null) applyMinimum(parsed)
  }
  const changeMaximum = (text: string) => {
    setMaximumText(text)
    const parsed = parseRangeInput(text)
    if (parsed !== null) applyMaximum(parsed)
  }
  return (
    <div className="range-filter">
      <div className="range-filter-heading">
        <span>{label}</span>
        <div className="range-inputs">
          <input aria-label={`${label} minimum`} type="number" step="any" value={minimumText} onChange={(event) => changeMinimum(event.target.value)} onBlur={commitMinimum} />
          <span aria-hidden="true">–</span>
          <input aria-label={`${label} maximum`} type="number" step="any" value={maximumText} onChange={(event) => changeMaximum(event.target.value)} onBlur={commitMaximum} />
          <small>{unit}</small>
        </div>
      </div>
      <RangeSlider
        min={minimum}
        max={maximum}
        step={rangeStep(minimum, maximum)}
        value={selected}
        onChange={onChange}
        label={null}
        minRange={0}
        aria-label={label}
      />
    </div>
  )
}

function optionBounds(options: ExperimentFilterOptions | undefined, key: 'actual_dose' | 'target_dose' | 'runtime') {
  return {
    minimum: options?.[`${key}_min`] ?? null,
    maximum: options?.[`${key}_max`] ?? null,
  }
}

function pageFromQuery(search: string): number {
  const page = Number(new URLSearchParams(search).get('page') ?? '1')
  return Number.isInteger(page) && page > 0 ? page : 1
}

function pageSizeFromQuery(search: string): number {
  const pageSize = Number(new URLSearchParams(search).get('page_size') ?? '50')
  return pageSizes.includes(pageSize) ? pageSize : 50
}

function hrefFor(page: number, pageSize: number, filters: ExperimentFilters): string {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value))
  })
  return `/experiments?${params.toString()}`
}

export function ExperimentsPage() {
  const [location, setLocation] = useLocation()
  const search = location.includes('?') ? location.slice(location.indexOf('?')) : window.location.search
  const page = pageFromQuery(search)
  const pageSize = pageSizeFromQuery(search)
  const filters = filtersFromQuery(search)
  const [draft, setDraft] = useState<ExperimentFilters>(filters)
  const [selectedRuns, setSelectedRuns] = useState<Set<string>>(() => new Set())
  const [otherFilters, setOtherFilters] = useState<Set<CategoricalFilter>>(() => new Set())
  const query = useExperiments(page, pageSize, filters)
  const filterOptions = useExperimentFilterOptions()
  const actualDoseBounds = optionBounds(filterOptions.data, 'actual_dose')
  const targetDoseBounds = optionBounds(filterOptions.data, 'target_dose')
  const runtimeBounds = optionBounds(filterOptions.data, 'runtime')

  const updateDraft = (key: keyof ExperimentFilters, value: string) => {
    setDraft((current) => ({
      ...current,
      [key]: [
        'min_actual_dose',
        'max_actual_dose',
        'min_target_dose',
        'max_target_dose',
        'min_runtime',
        'max_runtime',
      ].includes(key)
        ? numberOrUndefined(value)
        : value || undefined,
    }))
  }

  const updateRange = (keys: RangeKeys, minimum: number | null, maximum: number | null, value: [number, number]) => {
    if (minimum === null || maximum === null) return
    setDraft((current) => ({
      ...current,
      [keys[0]]: value[0] <= minimum ? undefined : value[0],
      [keys[1]]: value[1] >= maximum ? undefined : value[1],
    }))
  }

  const applyFilters = () => setLocation(hrefFor(1, pageSize, draft))
  const clearFilters = () => {
    setDraft({})
    setOtherFilters(new Set())
    setLocation(hrefFor(1, pageSize, {}))
  }
  const selectPresetFilter = (key: CategoricalFilter, value: string) => {
    setOtherFilters((current) => {
      const next = new Set(current)
      if (value === otherOption) next.add(key)
      else next.delete(key)
      return next
    })
    updateDraft(key, value === otherOption ? '' : value)
  }
  const customFilter = (key: CategoricalFilter, choices: string[]) => (
    otherFilters.has(key) || Boolean(draft[key] && !choices.includes(draft[key]!))
  )
  const pageRunIds = query.data?.items.map((item) => item.run_id) ?? []
  const allPageSelected = pageRunIds.length > 0 && pageRunIds.every((runId) => selectedRuns.has(runId))
  const toggleRun = (runId: string) => setSelectedRuns((current) => {
    const next = new Set(current)
    if (next.has(runId)) next.delete(runId)
    else next.add(runId)
    return next
  })
  const togglePage = () => setSelectedRuns((current) => {
    const next = new Set(current)
    pageRunIds.forEach((runId) => {
      if (allPageSelected) next.delete(runId)
      else next.add(runId)
    })
    return next
  })
  const comparisonHref = `/experiment-analysis?${new URLSearchParams({ run_ids: [...selectedRuns].join(',') })}`

  return (
    <div className="page page-enter">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Illinois Plasma Institute Extreme Ultraviolet System</p>
          <h1>Past Exposures Database</h1>
          <p>Run records, details, and waveform analysis.</p>
        </div>
      </section>

      <section className="panel experiment-filter-panel" aria-label="Exposure filters">
        <div className="experiment-filter-grid">
          <label>Name<input value={draft.name ?? ''} onChange={(event) => updateDraft('name', event.target.value)} /></label>
          <PresetFilter label="Sample" filterKey="sample" value={draft.sample} choices={filterOptions.data?.samples ?? []} showOther={customFilter('sample', filterOptions.data?.samples ?? [])} onSelect={selectPresetFilter} onChange={updateDraft} />
          <PresetFilter label="Operator" filterKey="operator" value={draft.operator} choices={filterOptions.data?.operators ?? []} showOther={customFilter('operator', filterOptions.data?.operators ?? [])} onSelect={selectPresetFilter} onChange={updateDraft} />
          <PresetFilter label="Zr filter" filterKey="zr_filter" value={draft.zr_filter} choices={filterOptions.data?.zr_filters ?? []} showOther={customFilter('zr_filter', filterOptions.data?.zr_filters ?? [])} onSelect={selectPresetFilter} onChange={updateDraft} />
          <fieldset className="date-range-filter">
            <legend><CalendarDays size={14} aria-hidden="true" />Created date</legend>
            <label>From<input type="date" min={dateInputValue(filterOptions.data?.created_min ?? undefined)} max={dateInputValue(filterOptions.data?.created_max ?? undefined)} value={dateInputValue(draft.created_min)} onChange={(event) => setDraft((current) => ({ ...current, created_min: timestampForDate(event.target.value) }))} /></label>
            <label>Through<input type="date" min={dateInputValue(filterOptions.data?.created_min ?? undefined)} max={dateInputValue(filterOptions.data?.created_max ?? undefined)} value={dateInputValue(draft.created_max)} onChange={(event) => setDraft((current) => ({ ...current, created_max: timestampForDate(event.target.value, true) }))} /></label>
          </fieldset>
          <RangeFilter label="Actual dose" {...actualDoseBounds} value={[draft.min_actual_dose, draft.max_actual_dose]} onChange={(value) => updateRange(['min_actual_dose', 'max_actual_dose'], actualDoseBounds.minimum, actualDoseBounds.maximum, value)} unit="mJ/cm²" />
          <RangeFilter label="Target dose" {...targetDoseBounds} value={[draft.min_target_dose, draft.max_target_dose]} onChange={(value) => updateRange(['min_target_dose', 'max_target_dose'], targetDoseBounds.minimum, targetDoseBounds.maximum, value)} unit="mJ/cm²" />
          <RangeFilter label="Runtime" {...runtimeBounds} value={[draft.min_runtime, draft.max_runtime]} onChange={(value) => updateRange(['min_runtime', 'max_runtime'], runtimeBounds.minimum, runtimeBounds.maximum, value)} unit="s" />
        </div>
        {filterOptions.error && <p className="filter-options-error">Filter choices are temporarily unavailable; active URL filters still apply.</p>}
        <div className="experiment-filter-actions">
          <button type="button" className="primary-action" onClick={applyFilters}><Search size={15} aria-hidden="true" />Search</button>
          <button type="button" className="quiet-action" onClick={clearFilters}><RotateCcw size={15} aria-hidden="true" />Clear</button>
          <span><Filter size={14} aria-hidden="true" /> {query.data?.total_count ?? 0} matching runs</span>
        </div>
      </section>

      {selectedRuns.size > 0 && <section className="experiment-selection-bar" aria-label="Selected experiment actions"><span><strong>{selectedRuns.size}</strong> selected</span><button type="button" className="quiet-action" onClick={() => setSelectedRuns(new Set())}>Clear selection</button><Link className={`primary-action ${selectedRuns.size < 2 ? 'is-disabled' : ''}`} href={comparisonHref}><ChartNoAxesCombined size={15} aria-hidden="true" />Compare runs</Link></section>}

      {query.isLoading && !query.data ? (
        <ExperimentLoadingPanel title="Loading experiment index" detail="Reading indexed records and filter metadata." />
      ) : (
      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Results</p><h2>Newest first</h2></div>
          <label className="page-size-label">Rows
            <select value={pageSize} onChange={(event) => setLocation(hrefFor(1, Number(event.target.value), filters))}>
              {pageSizes.map((size) => <option key={size} value={size}>{size}</option>)}
            </select>
          </label>
        </div>
        {query.isFetching && <div className="table-refresh-marquee" aria-label="Refreshing experiment results"><span /></div>}
        {query.error && <p className="inline-notice">{query.error.message}</p>}
        <div className="table-scroll" tabIndex={0} aria-label="Exposure results">
          <table className="data-table experiment-table">
            <thead><tr><th className="selection-cell"><input type="checkbox" aria-label="Select all runs on this page" checked={allPageSelected} onChange={togglePage} /></th><th>Name</th><th>Sample</th><th>Operator</th><th>Created</th><th>Dose</th><th>Runtime</th><th>Rate</th><th>Development</th><th>Status</th></tr></thead>
            <tbody>
              {query.data?.items.map((item) => (
                <tr key={item.run_id}>
                  <td className="selection-cell"><input type="checkbox" aria-label={`Select ${item.name || item.run_id}`} checked={selectedRuns.has(item.run_id)} onChange={() => toggleRun(item.run_id)} /></td>
                  <td><Link className="experiment-link" href={`/experiments/${item.run_id}?${new URLSearchParams(search)}`}>{item.name || 'Untitled'}<small>{item.description || item.run_id.slice(-8)}</small></Link></td>
                  <td>{item.sample ?? '—'}</td>
                  <td>{item.operator ?? '—'}</td>
                  <td className="numeric-cell">{formatDate(item.created_at)}</td>
                  <td className="numeric-cell">{formatNumber(item.actual_dose)}</td>
                  <td className="numeric-cell">{formatNumber(item.runtime)}</td>
                  <td className="numeric-cell">{formatNumber(item.effective_dose_rate)}</td>
                  <td className="numeric-cell">{formatNumber(item.percent_development, 1)}{item.percent_development === null ? '' : '%'}</td>
                  <td><span className={`run-status ${item.status ? 'has-status' : ''}`}>{item.status ?? 'Unknown'}</span></td>
                </tr>
              ))}
              {query.data && query.data.items.length === 0 && <tr><td colSpan={10} className="result-cell">No indexed runs match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
        {query.data && query.data.total_pages > 1 && (
          <nav className="experiment-pagination" aria-label="Exposure pages">
            <Link className={page === 1 ? 'is-disabled' : ''} href={hrefFor(Math.max(1, page - 1), pageSize, filters)}>Previous</Link>
            <span>Page {page} of {query.data.total_pages}</span>
            <Link className={page === query.data.total_pages ? 'is-disabled' : ''} href={hrefFor(Math.min(query.data.total_pages, page + 1), pageSize, filters)}>Next</Link>
          </nav>
        )}
      </section>
      )}
    </div>
  )
}