import { useState, useCallback } from 'react'
import './App.css'

const API_URL = window.location.hostname === 'localhost' ? 'http://localhost:8000' : ''

type Segment = { label: string; start: string; end: string; code: string }
type Packet = {
  emp_id: string
  employee_name: string
  work_date?: string
  actual_start_time: string
  actual_end_time: string
  scheduled_end_time: string
  scheduled_run_str: string
  notes_text: string
  alternate_driver_present: boolean
  primary_condition_text: string
  exclusion_tags: string[]
  potential_bleed?: boolean
  alternate_emp_id?: string
  alternate_name?: string
}

type Row = {
  type: 'included' | 'excluded'
  bucket: string
  packet: Packet
  segments: Segment[]
  annotation: string | null
  ot_pay_type: string
  cte_preferred: boolean
  lpi_minutes: number
  lpi_pay_type: string
  total_worked_str: string
  shape: string
  status: string
  flagged: boolean
  segments_modified?: boolean  // True when user manually edited segments
  emp_id_modified?: boolean    // True when user corrected emp_id
}

type ProcessResponse = {
  work_date: string
  summary: { detected: number; included: number; excluded: number; stopped_at_row: number }
  rows: Row[]
  is_preliminary?: boolean
  labor_codes?: Record<string, string>
}

const SEGMENT_LABELS = ['REG', 'OT', 'CTE', 'LPI', 'GUARANTEE'] as const
const SEGMENT_CODES: Record<string, string> = { REG: '1020', OT: '1013', CTE: '3002', LPI: '1013', GUARANTEE: '1000' }
const DEFAULT_LABOR_CODES: Record<string, string> = {
  SICK: '3009', 'FMLA SICK': '2024', VACATION: '3008', 'FMLA VACATION': '2025',
  'ADMIN LEAVE': '3010', 'CT PAY': '3003',
}

const TIME_RE = /^\d{1,2}:\d{2}$/
function toMinutes(s: string): number | null {
  if (!TIME_RE.test(s)) return null
  const [h, m] = s.split(':').map(Number)
  if (h < 0 || h > 23 || m < 0 || m > 59) return null
  return h * 60 + m
}
function formatMinutesToHrMin(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${h}:${m.toString().padStart(2, '0')}`
}
function segmentDurationMin(start: string, end: string): number | null {
  const sm = toMinutes(start)
  const em = toMinutes(end)
  if (sm == null || em == null) return null
  if (em >= sm) return em - sm
  return (24 * 60 - sm) + em
}
function segmentsTotalMinutes(segs: Segment[]): number {
  let total = 0
  for (const s of segs.filter((x) => x && x.start && x.end)) {
    const d = segmentDurationMin(s.start, s.end)
    if (d != null) total += d
  }
  return total
}
function shiftTotalMinutes(packet: Packet): number | null {
  const sm = toMinutes(packet.actual_start_time)
  const em = toMinutes(packet.actual_end_time)
  if (sm == null || em == null) return null
  if (em >= sm) return em - sm
  return (24 * 60 - sm) + em
}

function addDaysToDate(dateStr: string, days: number): string {
  if (!dateStr) return dateStr
  const parts = dateStr.split('/')
  if (parts.length !== 3) return dateStr
  const [m, d, y] = parts.map(Number)
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + days)
  return `${String(dt.getMonth() + 1).padStart(2, '0')}/${String(dt.getDate()).padStart(2, '0')}/${dt.getFullYear()}`
}
function escapeCsvCell(s: string): string {
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

function doExportToCsv(rows: Row[], workDate: string) {
  const completed = rows.filter((r) => r.status === 'completed' && r.segments.length > 0)
  if (completed.length === 0) return
  const lines: string[] = []
  for (const row of completed) {
    const segs = row.segments.filter((s) => s && (s.label || s.start || s.end))
    const dateVal = row.packet?.work_date || workDate || ''
    const dateIn = dateVal
    for (const seg of segs) {
      if (!seg.start && !seg.end) continue
      const segStartM = toMinutes(seg.start)
      const segEndM = toMinutes(seg.end)
      const segCrossesMidnight = segStartM != null && segEndM != null && segEndM < segStartM
      const outDate = segCrossesMidnight ? addDaysToDate(dateVal, 1) : dateVal
      lines.push([
        escapeCsvCell(row.packet.emp_id),
        escapeCsvCell(dateIn),
        escapeCsvCell(outDate),
        escapeCsvCell(seg.start || ''),
        escapeCsvCell(seg.end || ''),
        escapeCsvCell(seg.code || ''),
      ].join(','))
    }
  }
  const csv = '\uFEFF' + lines.join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  const dateStr = workDate?.replace(/\//g, '-') || 'segments'
  a.download = `completed_segments_${dateStr}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

function validateSegments(segs: Segment[], packet?: Packet): string[] {
  const valid = segs.filter((s) => s && (s.label || s.start || s.end))
  const issues: string[] = []
  for (let i = 0; i < valid.length; i++) {
    const s = valid[i]
    if (s.start && !TIME_RE.test(s.start)) issues.push(`Segment ${i + 1} start "${s.start}" is not HH:MM`)
    if (s.end && !TIME_RE.test(s.end)) issues.push(`Segment ${i + 1} end "${s.end}" is not HH:MM`)
    if (s.start && s.end) {
      const startM = toMinutes(s.start)
      const endM = toMinutes(s.end)
      if (startM != null && endM != null && startM >= endM)
        issues.push(`Segment ${i + 1} (${s.label}): start must be before end`)
    }
    if (i < valid.length - 1 && valid[i + 1].start && s.end) {
      if (s.end !== valid[i + 1].start)
        issues.push(`Segments should be contiguous: ${s.label} ends ${s.end}, next starts ${valid[i + 1].start}`)
    }
  }
  if (packet && valid.length > 0) {
    const segTotal = segmentsTotalMinutes(valid)
    const shiftTotal = shiftTotalMinutes(packet)
    if (shiftTotal != null && segTotal !== shiftTotal) {
      issues.push(`Segment total (${formatMinutesToHrMin(segTotal)}) doesn't match shift (${formatMinutesToHrMin(shiftTotal)}). Override if intentional.`)
    }
  }
  return issues
}

const statusLabels: Record<string, string> = { pending: 'Pending', reviewed: 'Reviewed', completed: 'Completed', skipping: 'Skipping hours' }
const bucketLabels: Record<string, string> = {
  simple: 'Simple',
  lpi: 'LPI',
  alt: 'Alt (day off)',
  exb_shine: 'EXB SHINE',
  condition_or_alternate: 'Condition/Alt',
  exb: 'EXB',
  other: 'Other',
}

function App() {
  const [data, setData] = useState<ProcessResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [bucketFilter, setBucketFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [bleedFilter, setBleedFilter] = useState<boolean>(false)
  const [dosFile, setDosFile] = useState<File | null>(null)
  const [preliminaryDosFile, setPreliminaryDosFile] = useState<File | null>(null)
  const [cteFile, setCteFile] = useState<File | null>(null)
  const [workDateOverride, setWorkDateOverride] = useState('')
  const [editingSegments, setEditingSegments] = useState<Segment[] | null>(null)
  const [confirmApply, setConfirmApply] = useState(false)
  const [exportModal, setExportModal] = useState<{ show: true } | null>(null)

  const updateRow = useCallback((index: number, updates: Partial<Row>) => {
    if (!data) return
    const newRows = [...data.rows]
    newRows[index] = { ...newRows[index], ...updates }
    setData({ ...data, rows: newRows })
  }, [data])

  const filteredRows = data?.rows.filter((row) => {
    if (bucketFilter !== 'all' && row.bucket !== bucketFilter) return false
    if (typeFilter !== 'all' && row.type !== typeFilter) return false
    if (statusFilter !== 'all' && row.status !== statusFilter) return false
    if (bleedFilter && !row.packet.potential_bleed) return false
    return true
  }) ?? []

  const selectedRow = selectedIndex !== null && data?.rows[selectedIndex]
    ? { index: selectedIndex, row: data.rows[selectedIndex] }
    : null

  // Clear edit mode when switching rows
  const handleSelectRow = useCallback((idx: number) => {
    setEditingSegments(null)
    setConfirmApply(false)
    setSelectedIndex(idx)
  }, [])


  const handleProcess = async () => {
    if (!dosFile && !preliminaryDosFile) {
      setError('Please select a DOS file (Final or Preliminary)')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const form = new FormData()
      const activeFile = dosFile || preliminaryDosFile
      if (activeFile) {
        form.append('dos_file', activeFile)
        form.append('dos_type', preliminaryDosFile ? 'preliminary' : 'final')
      }
      if (cteFile) form.append('cte_file', cteFile)
      if (workDateOverride) form.append('work_date_override', workDateOverride)
      const res = await fetch(`${API_URL}/api/process`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || res.statusText || 'Process failed')
      }
      const json: ProcessResponse = await res.json()
      setData(json)
      setSelectedIndex(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Process failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <div className="left-panel">
        <h2>DOS Primary Segment</h2>
        {data?.is_preliminary && <p className="prelim-badge">📋 Preliminary (projected)</p>}
        <div className="upload-zone"
          onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('dragover') }}
          onDragLeave={(e) => e.currentTarget.classList.remove('dragover')}
          onDrop={(e) => {
            e.preventDefault()
            e.currentTarget.classList.remove('dragover')
            const f = e.dataTransfer.files[0]
            if (f) { setDosFile(f); setPreliminaryDosFile(null) }
          }}
          onClick={() => document.getElementById('dos-input')?.click()}
        >
          <input id="dos-input" type="file" accept=".pdf,.txt,.csv,.xlsx,.xls" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setDosFile(f); setPreliminaryDosFile(null) } else setDosFile(null) }} />
          <strong>Final DOS (actual hours)</strong>
          <p style={{ margin: '4px 0', fontSize: 13, color: '#333' }}>{dosFile?.name ?? 'Drop or click'}</p>
        </div>
        <div className="upload-zone preliminary-zone"
          onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('dragover') }}
          onDragLeave={(e) => e.currentTarget.classList.remove('dragover')}
          onDrop={(e) => {
            e.preventDefault()
            e.currentTarget.classList.remove('dragover')
            const f = e.dataTransfer.files[0]
            if (f) { setPreliminaryDosFile(f); setDosFile(null) }
          }}
          onClick={() => document.getElementById('prelim-input')?.click()}
        >
          <input id="prelim-input" type="file" accept=".pdf,.txt,.csv,.xlsx,.xls" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setPreliminaryDosFile(f); setDosFile(null) } else setPreliminaryDosFile(null) }} />
          <strong>Preliminary DOS (projected hours)</strong>
          <p style={{ margin: '4px 0', fontSize: 13, color: '#333' }}>{preliminaryDosFile?.name ?? 'Drop or click'}</p>
        </div>
        <div className="upload-zone" onClick={() => document.getElementById('cte-input')?.click()}>
          <input id="cte-input" type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setCteFile(e.target.files?.[0] ?? null)} />
          <strong>CTE Config (optional)</strong>
          <p style={{ margin: '4px 0', fontSize: 13, color: '#333' }}>{cteFile?.name ?? 'Drop or click'}</p>
        </div>
        <div className="filter-group">
          <label>Work date override</label>
          <input type="text" placeholder="e.g. 02/12/2026" value={workDateOverride} onChange={(e) => setWorkDateOverride(e.target.value)}
            style={{ width: '100%', padding: 10, borderRadius: 4, border: '1px solid #666', fontSize: 14, color: '#1a1a1a' }} />
        </div>
        <button onClick={handleProcess} disabled={loading || (!dosFile && !preliminaryDosFile)}
          style={{ width: '100%', padding: '12px', background: loading ? '#666' : '#333', color: '#fff', border: 'none', borderRadius: 6, cursor: loading ? 'wait' : 'pointer', fontWeight: 600 }}>
          {loading ? 'Processing…' : 'Process DOS'}
        </button>
        {data && (
          <>
            <div className="filter-group">
              <label>Bucket</label>
              {['all', 'simple', 'lpi', 'alt', 'exb_shine', 'condition_or_alternate', 'exb', 'other'].map((b) => (
                <button key={b} className={bucketFilter === b ? 'active' : ''} onClick={() => setBucketFilter(b)}>{b === 'all' ? 'All' : bucketLabels[b] || b}</button>
              ))}
            </div>
            <div className="filter-group">
              <label>Type</label>
              {['all', 'included', 'excluded'].map((t) => (
                <button key={t} className={typeFilter === t ? 'active' : ''} onClick={() => setTypeFilter(t)}>{t.charAt(0).toUpperCase() + t.slice(1)}</button>
              ))}
            </div>
            <div className="filter-group">
              <label>Status</label>
              {['all', 'pending', 'reviewed', 'completed', 'skipping'].map((s) => (
                <button key={s} className={statusFilter === s ? 'active' : ''} onClick={() => setStatusFilter(s)}>{s === 'skipping' ? 'Skipping hours' : s.charAt(0).toUpperCase() + s.slice(1)}</button>
              ))}
            </div>
            <div className="filter-group">
              <label>Bleed</label>
              <button className={bleedFilter ? 'active' : ''} onClick={() => setBleedFilter(!bleedFilter)} title="Show only rows with possible PDF bleed">
                {bleedFilter ? '⚠️ Bleed only' : 'All rows'}
              </button>
            </div>
            <div className="summary">
              <p><strong>Detected:</strong> {data.summary.detected}</p>
              <p><strong>Included:</strong> {data.summary.included}</p>
              <p><strong>Excluded:</strong> {data.summary.excluded}</p>
              <p><strong>Stopped at row:</strong> {data.summary.stopped_at_row}</p>
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #999' }}>
                <p style={{ fontWeight: 600, marginBottom: 6 }}>By bucket</p>
                {(['simple', 'lpi', 'condition_or_alternate', 'exb', 'other'] as const).map((b) => {
                  const count = data.rows.filter((r) => r.bucket === b).length
                  return count > 0 ? <p key={b}><strong>{bucketLabels[b] || b}:</strong> {count}</p> : null
                })}
              </div>
            </div>
                        <div className="completeness-check">
              <p style={{ fontWeight: 600, marginBottom: 6 }}>PDF names in buckets</p>
              {(() => {
                const primaryIds = new Set(data.rows.map((r) => r.packet.emp_id))
                const altIds = new Set(data.rows.filter((r) => r.packet.alternate_emp_id).map((r) => r.packet.alternate_emp_id!))
                const pdfAll = [...new Set([...primaryIds, ...altIds])]
                const bucketIds = new Set(data.rows.map((r) => r.packet.emp_id))
                const missing = pdfAll.filter((id) => !bucketIds.has(id))
                if (missing.length === 0) {
                  return <p style={{ color: '#1a5a1a', fontWeight: 600 }}>✓ All {pdfAll.length} names accounted for</p>
                }
                return (
                  <p style={{ color: '#8b1a1a', fontWeight: 600 }}>
                    Missing from buckets: {missing.length} — verify PDF
                  </p>
                )
              })()}
            </div>
            
            <div className="filter-group" style={{ marginTop: 16 }}>
              <label>Export</label>
              <button
                disabled={data.rows.filter((r) => r.status === 'completed' && r.segments?.length > 0).length === 0}
                onClick={() => setExportModal({ show: true })}
                style={{ width: '100%', padding: 10 }}
              >
                Export completed to CSV (UTF-8)
              </button>
              <p style={{ fontSize: 11, color: '#666', marginTop: 4 }}>One row per segment: emp_number, date_in, date_out, time_in, time_out, labor_code.</p>
            </div>
          </>
        )}
      </div>
      <div className="center-panel">
        {error && <div className="error">{error}</div>}
        {loading && <div className="loading">Processing DOS…</div>}
        {!loading && !data && !error && <div className="empty-state"><p>Upload a DOS file and click Process</p></div>}
        {!loading && data && (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 40 }}></th>
                  <th>Emp #</th>
                  <th>Name</th>
                  <th>Bucket</th>
                  <th>CTE</th>
                  <th>Type</th>
                  <th>Scheduled / Actual End</th>
                  <th>Status</th>
                  <th style={{ width: 50 }}>Bleed</th>
                  <th style={{ width: 50 }}>⚠/✏️</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => {
                  const idx = data!.rows.indexOf(row)
                  return (
                    <tr key={idx} tabIndex={0} className={selectedIndex === idx ? 'selected' : ''} onClick={() => handleSelectRow(idx)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSelectRow(idx) } }}>
                      <td>{idx + 1}</td>
                      <td><strong>{row.packet.emp_id}</strong>{row.emp_id_modified && <span title="Emp # corrected"> ✏️</span>}</td>
                      <td>{row.packet.employee_name}</td>
                      <td><span className={`bucket-badge bucket-${row.bucket}`}>{bucketLabels[row.bucket] || row.bucket}</span></td>
                      <td>{row.cte_preferred ? <span style={{ color: '#0d5a0d', fontWeight: 700 }}>✓ CTE</span> : '—'}</td>
                      <td><span className={`type-badge type-${row.type}`}>{row.type}</span></td>
                      <td style={{ fontFamily: 'monospace', fontSize: 13, color: '#1a1a1a' }}>{row.packet.scheduled_end_time} / {row.packet.actual_end_time}</td>
                      <td className={`status-${row.status}`}>{statusLabels[row.status] || row.status}</td>
                      <td>{row.packet.potential_bleed && (
                        <span className="bleed-badge" title="Possible PDF row bleed — verify notes">⚠️ BLEED</span>
                      )}</td>
                      <td>
                        {row.segments_modified && <span title="Segments modified">✏️</span>}
                        <button tabIndex={-1} className={`flag-btn ${row.flagged ? 'flagged' : ''}`} title="Flag for review" onClick={(e) => { e.stopPropagation(); updateRow(idx, { flagged: !row.flagged }) }}>{row.flagged ? '⚠' : '○'}</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="right-panel">
        {!selectedRow ? <div className="empty-state"><p>Select a row to view details</p></div> : (
          <>
            <h3>{selectedRow.row.packet.employee_name} ({selectedRow.row.packet.emp_id}){selectedRow.row.emp_id_modified && <span style={{ marginLeft: 8, fontSize: 12, color: '#666' }} title="Emp # corrected">✏️</span>}</h3>
            <div className="detail-section">
              <h4>Emp # (for export)</h4>
              <input type="text" value={selectedRow.row.packet.emp_id} onChange={(e) => {
                const v = e.target.value
                updateRow(selectedRow.index, { packet: { ...selectedRow.row.packet, emp_id: v }, emp_id_modified: true })
              }} style={{ width: '100%', padding: 8, fontSize: 14 }} placeholder="Correct emp number" />
            </div>
            {selectedRow.row.packet.potential_bleed && (
              <div className="bleed-alert-banner">
                <strong>⚠️ PDF ROW BLEED — Verify</strong><br />
                Notes may contain text from another row. Check the PDF before data entry.
              </div>
            )}
            <div className="detail-section">
              <h4>Scheduled run</h4>
              <p>{selectedRow.row.packet.scheduled_run_str || '—'}</p>
              <h4>Comparison</h4>
              <p>Scheduled end: {selectedRow.row.packet.scheduled_end_time}</p>
              <p>Actual end: {selectedRow.row.packet.actual_end_time}</p>
              <h4>Shift</h4>
              <p>{selectedRow.row.packet.actual_start_time} – {selectedRow.row.packet.actual_end_time} ({selectedRow.row.total_worked_str || '—'})</p>
              <h4>CTE Preferred</h4>
              <p>{selectedRow.row.cte_preferred ? '✓ Yes — OT segments use code 3002' : 'No — OT segments use code 1013'}</p>
              {selectedRow.row.packet.notes_text && <><h4>Notes</h4><p>{selectedRow.row.packet.notes_text}</p></>}
{selectedRow.row.packet.primary_condition_text && <><h4>Primary condition</h4><p>{selectedRow.row.packet.primary_condition_text}</p></>}
              {selectedRow.row.packet.exclusion_tags?.length > 0 && <><h4>Exclusion tags</h4><p>{selectedRow.row.packet.exclusion_tags.join(', ')}</p></>}
            </div>
            {(selectedRow.row.segments.length > 0 || editingSegments || (selectedRow.row.type === 'excluded' && selectedRow.row.segments.length === 0)) && (
              <div className="detail-section">
                <h4>Segments (enter into TimeClock){selectedRow.row.segments_modified ? ' ✏️ Modified' : ''}</h4>
                {editingSegments ? (
                  <>
                    {Array.from({ length: selectedRow.row.type === 'excluded' ? 5 : 3 }, (_, i) => i).map((i) => (
                      <div key={i} className="segment-edit-row">
                        <select value={editingSegments[i]?.label || ''} onChange={(e) => {
                          const v = e.target.value
                          const next = [...editingSegments]
                          if (!next[i]) next[i] = { label: '', start: '', end: '', code: '' }
                          const codes = { ...SEGMENT_CODES, ...DEFAULT_LABOR_CODES }
                          next[i] = { ...next[i], label: v, code: v ? (codes[v] || '') : '' }
                          setEditingSegments(next)
                        }} style={{ width: 130, padding: 4 }}>
                          <option value="">—</option>
                          {SEGMENT_LABELS.map((l) => <option key={l} value={l}>{l}</option>)}
                          {Object.keys(DEFAULT_LABOR_CODES).map((l) => <option key={l} value={l}>{l}</option>)}
                        </select>
                        <input type="text" placeholder="Start (HH:MM)" value={editingSegments[i]?.start || ''} onChange={(e) => {
                          const next = [...editingSegments]
                          if (!next[i]) next[i] = { label: '', start: '', end: '', code: '' }
                          next[i] = { ...next[i], start: e.target.value }
                          setEditingSegments(next)
                        }} style={{ width: 70, padding: 4 }} />
                        <input type="text" placeholder="End (HH:MM)" value={editingSegments[i]?.end || ''} onChange={(e) => {
                          const next = [...editingSegments]
                          if (!next[i]) next[i] = { label: '', start: '', end: '', code: '' }
                          next[i] = { ...next[i], end: e.target.value }
                          setEditingSegments(next)
                        }} style={{ width: 70, padding: 4 }} />
                        <input type="text" placeholder="Code" value={editingSegments[i]?.code || ''} onChange={(e) => {
                          const next = [...editingSegments]
                          if (!next[i]) next[i] = { label: '', start: '', end: '', code: '' }
                          next[i] = { ...next[i], code: e.target.value }
                          setEditingSegments(next)
                        }} style={{ width: 50, padding: 4 }} />
                      </div>
                    ))}
                    <p style={{ fontSize: 12, color: '#666', marginTop: 8 }}>Leave unused slots blank.</p>
                    {(() => {
                      const valid = editingSegments.filter((s) => s && (s.label || s.start || s.end))
                      const liveIssues = valid.length > 0 ? validateSegments(valid, selectedRow.row.type === 'included' ? selectedRow.row.packet : undefined) : []
                      return liveIssues.length > 0 && (
                        <div className="segment-validation-hint">
                          <strong>⚠️</strong> {liveIssues[0]}
                        </div>
                      )
                    })()}
                    {confirmApply ? (
                      <div className="confirm-box">
                        {(() => {
                          const valid = editingSegments.filter((s) => s && (s.label || s.start || s.end))
                          const issues = validateSegments(valid, selectedRow.row.packet)
                          return (
                            <>
                              {issues.length > 0 ? (
                                <>
                                  <p className="segment-safety-warning">⚠️ Check segments before applying:</p>
                                  <ul className="segment-safety-list">
                                    {issues.map((msg, i) => <li key={i}>{msg}</li>)}
                                  </ul>
                                  <p style={{ fontSize: 13, marginTop: 8 }}>Apply anyway?</p>
                                  <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                                    <button className="danger" onClick={() => {
                                      const v = editingSegments.filter((s) => s && (s.label || s.start || s.end))
                                      updateRow(selectedRow.index, { segments: v, segments_modified: true })
                                      setEditingSegments(null)
                                      setConfirmApply(false)
                                    }}>Yes, apply anyway</button>
                                    <button onClick={() => setConfirmApply(false)}>Go back and fix</button>
                                  </div>
                                </>
                              ) : (
                                <>
                                  <p>Apply these segment changes? This will flag the row as modified.</p>
                                  <button className="primary" onClick={() => {
                                    const v = editingSegments.filter((s) => s && (s.label || s.start || s.end))
                                    updateRow(selectedRow.index, { segments: v, segments_modified: true })
                                    setEditingSegments(null)
                                    setConfirmApply(false)
                                  }}>Yes, apply</button>
                                  <button onClick={() => setConfirmApply(false)}>Cancel</button>
                                </>
                              )}
                            </>
                          )
                        })()}
                      </div>
                    ) : (
                      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                        <button className="primary" onClick={() => setConfirmApply(true)}>Apply changes</button>
                        <button onClick={() => { setEditingSegments(null); setConfirmApply(false) }}>Cancel</button>
                      </div>
                    )}
                  </>
                ) : selectedRow.row.segments.length > 0 ? (
                  <>
                    {selectedRow.row.segments.map((s, i) => (
                      <div key={i} className="segment-row">
                        <span className="segment-label">{s.label}</span>
                        {s.code && <span className="segment-code">({s.code})</span>}
                        <span className="segment-time">{s.start} → {s.end}</span>
                      </div>
                    ))}
                    {selectedRow.row.annotation && <p style={{ marginTop: 8, fontStyle: 'italic', color: '#333' }}>{selectedRow.row.annotation}</p>}
                    <button style={{ marginTop: 12 }} onClick={() => setEditingSegments(() => {
                      const segs = selectedRow.row.segments
                      const maxSlots = selectedRow.row.type === 'excluded' ? 5 : 3
                      const slots: Segment[] = []
                      for (let i = 0; i < maxSlots; i++) slots.push(segs[i] ? { ...segs[i] } : { label: '', start: '', end: '', code: '' })
                      return slots
                    })}>Edit segments</button>
                  </>
                ) : (
                  <p style={{ marginTop: 8 }}>
                    <button className="primary" onClick={() => setEditingSegments(() =>
                      Array.from({ length: 5 }, () => ({ label: '', start: '', end: '', code: '' }))
                    )}>Add segments</button>
                    {' '}Add leave hours (SICK, VACATION, etc.) for excluded employee.
                  </p>
                )}
              </div>
            )}
            <div className="action-buttons">
              <button onClick={() => updateRow(selectedRow.index, { status: 'reviewed' })}>Mark Reviewed</button>
              <button onClick={() => updateRow(selectedRow.index, { status: 'completed' })}>Mark Completed</button>
              <button onClick={() => updateRow(selectedRow.index, { status: 'skipping' })}>Skipping hours</button>
              <button className={selectedRow.row.flagged ? 'danger' : ''} onClick={() => updateRow(selectedRow.index, { flagged: !selectedRow.row.flagged })}>{selectedRow.row.flagged ? 'Unflag' : 'Flag for review'}</button>
            </div>
          </>
        )}
      </div>

      {exportModal && data && (() => {
        const primaryIds = new Set(data.rows.map((r) => r.packet.emp_id))
        const altIds = new Set(data.rows.filter((r) => r.packet.alternate_emp_id).map((r) => r.packet.alternate_emp_id))
        const accountedIds = [...new Set([...primaryIds, ...altIds])]
        const completed = data.rows.filter((r) => r.status === 'completed' && r.segments.length > 0)
        const exportIds = new Set(completed.map((r) => r.packet.emp_id))
        const skippedIds = accountedIds.filter((id): id is string => !!id && !exportIds.has(id))
        const skippedList = skippedIds.map((id) => {
          const r = data.rows.find((row) => row.packet.emp_id === id) || data.rows.find((row) => row.packet.alternate_emp_id === id)
          return { id, name: r?.packet.employee_name || r?.packet.alternate_name || '' }
        })
        return (
          <div className="modal-overlay" onClick={() => setExportModal(null)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <h3>Export to CSV</h3>
              <p><strong>{exportIds.size}</strong> unique emp_ids will be exported.</p>
              <p><strong>{accountedIds.length}</strong> emp accounted for in total.</p>
              {skippedList.length > 0 ? (
                <>
                  <p style={{ color: '#8b1a1a', fontWeight: 600 }}>You are skipping {skippedList.length} emp:</p>
                  <ul style={{ margin: '12px 0', paddingLeft: 20, maxHeight: 200, overflowY: 'auto' }}>
                    {skippedList.map((s) => (
                      <li key={s.id}>{s.id} — {s.name || '(name unknown)'}</li>
                    ))}
                  </ul>
                  <p style={{ fontSize: 13, color: '#666' }}>Export anyway?</p>
                </>
              ) : (
                <p style={{ color: '#1a5a1a', fontWeight: 600 }}>All accounted emp are in the export.</p>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                <button className="primary" onClick={() => { doExportToCsv(data.rows, data.work_date || ''); setExportModal(null) }}>Export</button>
                <button onClick={() => setExportModal(null)}>Cancel</button>
              </div>
            </div>
          </div>
        )
      })()}

    </div>
  )
}

export default App
