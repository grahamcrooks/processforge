import { useState, useMemo } from 'react'
import { HOPEX_REFS } from '../hopexRefs.js'
import './ProcessMapPage.css'

// ── Helpers ────────────────────────────────────────────────────────────────────

function refFromFilename(filename) {
  const m = filename.match(/^(\d+(?:\.\d+)+)/)
  return m ? m[1] : null
}

function nameFromFilename(filename) {
  const stem = filename.replace(/\.[^.]+$/, '')
  const m = stem.match(/^\d+(?:\.\d+)+\s+(.+)/)
  return m ? m[1].trim() : stem
}

function compareRefs(a, b) {
  const ka = a.split('.').map(n => parseInt(n, 10))
  const kb = b.split('.').map(n => parseInt(n, 10))
  for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
    const diff = (ka[i] ?? 0) - (kb[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

// ── Build unified ref map ──────────────────────────────────────────────────────

function buildRefMap(diagrams, refMapData) {
  const map = new Map()

  const ensure = (ref) => {
    if (!map.has(ref)) map.set(ref, { ref, name: HOPEX_REFS[ref] || '', sources: new Set(), type: null })
    return map.get(ref)
  }

  for (const [ref, name] of Object.entries(HOPEX_REFS)) {
    const node = ensure(ref)
    node.sources.add('hopex')
    if (!node.name) node.name = name
  }

  diagrams.forEach(f => {
    const ref = refFromFilename(f.name)
    if (!ref) return
    const node = ensure(ref)
    node.sources.add('uploaded')
    node.uploadedFilename = f.name
    if (!node.name) node.name = nameFromFilename(f.name)
  })

  if (refMapData?.nodes) {
    refMapData.nodes.forEach(n => {
      const node = ensure(n.source_ref)
      node.sources.add('assessed')
      node.type = n.type
      if (!node.name && n.name) node.name = n.name
    })
  }

  if (refMapData?.image_refs) {
    Object.values(refMapData.image_refs).flat().forEach(ref => ensure(ref).sources.add('seen'))
  }

  return map
}

// ── Build tree ─────────────────────────────────────────────────────────────────

function buildTree(refMap, seriesRoot) {
  const relevant = [...refMap.values()].filter(n =>
    n.ref === seriesRoot || n.ref.startsWith(seriesRoot + '.')
  )

  const nodeMap = new Map()
  relevant.forEach(n => nodeMap.set(n.ref, { ...n, sources: new Set(n.sources), children: [] }))

  relevant.forEach(n => {
    const parts = n.ref.split('.')
    for (let i = 1; i < parts.length; i++) {
      const ancestor = parts.slice(0, i).join('.')
      if (!nodeMap.has(ancestor)) {
        nodeMap.set(ancestor, {
          ref: ancestor,
          name: HOPEX_REFS[ancestor] || '',
          sources: new Set(HOPEX_REFS[ancestor] ? ['hopex'] : ['implied']),
          type: null,
          children: [],
          implied: true,
        })
      }
    }
  })

  const roots = []
  for (const [ref, node] of nodeMap) {
    const parts = ref.split('.')
    if (parts.length === 1 || ref === seriesRoot) {
      roots.push(node)
    } else {
      const parentRef = parts.slice(0, -1).join('.')
      if (nodeMap.has(parentRef)) nodeMap.get(parentRef).children.push(node)
      else roots.push(node)
    }
  }

  function sortChildren(nodes) {
    nodes.sort((a, b) => compareRefs(a.ref, b.ref))
    nodes.forEach(n => sortChildren(n.children))
  }
  sortChildren(roots)

  return roots
}

// ── Status helpers ─────────────────────────────────────────────────────────────

function getStatus(node) {
  if (node.sources.has('uploaded')) return 'uploaded'
  if (node.sources.has('assessed')) return 'assessed'
  if (node.sources.has('seen'))     return 'seen'
  if (node.implied)                 return 'implied'
  return 'hopex'
}

const STATUS_CONFIG = {
  uploaded: { label: 'Uploaded',    color: '#16a34a', bg: '#dcfce7', border: '#86efac' },
  assessed: { label: 'Assessed',    color: '#0369a1', bg: '#e0f2fe', border: '#7dd3fc' },
  seen:     { label: 'Referenced',  color: '#b45309', bg: '#fef3c7', border: '#fcd34d' },
  hopex:    { label: 'Not uploaded',color: '#64748b', bg: '#f1f5f9', border: '#cbd5e1' },
  implied:  { label: 'Implied',     color: '#9ca3af', bg: '#f9fafb', border: '#e5e7eb' },
}

const CLASS_CONFIG = {
  case_type:  { label: 'Case Type',  short: 'CT', color: '#7c3aed', bg: '#ede9fe', border: '#c4b5fd' },
  child_case: { label: 'Child Case', short: 'CC', color: '#0369a1', bg: '#dbeafe', border: '#93c5fd' },
  inline:     { label: 'Inline',     short: 'IL', color: '#374151', bg: '#f3f4f6', border: '#d1d5db' },
}

// ── Counts ─────────────────────────────────────────────────────────────────────

function countDescendants(node) {
  let total = 0
  function walk(n) { total++; n.children.forEach(walk) }
  node.children.forEach(walk)
  return total
}

function countUploaded(node) {
  let total = 0
  function walk(n) { if (n.sources.has('uploaded')) total++; n.children.forEach(walk) }
  walk(node)
  return total
}

// ── Search ─────────────────────────────────────────────────────────────────────

function nodeMatchesSearch(node, query) {
  if (!query) return true
  const q = query.toLowerCase()
  return node.ref.toLowerCase().includes(q) || node.name.toLowerCase().includes(q)
}

function treeHasMatch(node, query) {
  if (nodeMatchesSearch(node, query)) return true
  return node.children.some(c => treeHasMatch(c, query))
}

// ── Generate instructions ──────────────────────────────────────────────────────

function generateInstructions(classifications, refMap) {
  const entries = Object.entries(classifications)
    .filter(([, v]) => v !== null)
    .sort(([a], [b]) => compareRefs(a, b))

  if (entries.length === 0) return ''

  return entries.map(([ref, cls]) => {
    const name = refMap.get(ref)?.name || ref
    if (cls === 'case_type')  return `${ref} is a Case Type named ${name}`
    if (cls === 'child_case') return `${ref} is a child case named ${name}`
    if (cls === 'inline')     return `${ref} is inline`
    return null
  }).filter(Boolean).join('; ')
}

// ── Tree node ──────────────────────────────────────────────────────────────────

function TreeNode({ node, depth, searchQuery, forceExpand, classifications, onClassify }) {
  const status = getStatus(node)
  const cfg = STATUS_CONFIG[status]
  const hasChildren = node.children.length > 0
  const [open, setOpen] = useState(depth < 2)

  const isExpanded = forceExpand || open
  const visibleChildren = searchQuery
    ? node.children.filter(c => treeHasMatch(c, searchQuery))
    : node.children

  const descCount   = hasChildren ? countDescendants(node) : 0
  const uploadCount = hasChildren ? countUploaded(node) : 0
  const highlight   = searchQuery && nodeMatchesSearch(node, searchQuery)

  const classification = classifications[node.ref] ?? null
  const clsCfg = classification ? CLASS_CONFIG[classification] : null

  // Show classify controls for uploaded + assessed + seen nodes
  const canClassify = node.sources.has('uploaded') || node.sources.has('assessed') || node.sources.has('seen')

  return (
    <div className="pm-node-wrap">
      <div
        className={`pm-node${highlight ? ' pm-node--match' : ''}${node.implied ? ' pm-node--implied' : ''}`}
        style={{ '--depth': depth, '--status-color': cfg.color, '--status-bg': cfg.bg, '--status-border': cfg.border }}
      >
        <div className="pm-node-left">
          {hasChildren ? (
            <button
              className={`pm-toggle ${isExpanded ? 'pm-toggle--open' : ''}`}
              onClick={() => setOpen(v => !v)}
            >▶</button>
          ) : (
            <span className="pm-toggle pm-toggle--leaf" />
          )}
          <span className="pm-ref">{node.ref}</span>
          <span className="pm-name" title={node.name}>
            {node.name || <em className="pm-no-name">No name in HOPEX</em>}
          </span>
        </div>

        <div className="pm-node-right">
          {hasChildren && (
            <span className="pm-child-count" title={`${uploadCount} of ${descCount} uploaded`}>
              <span className="pm-child-uploaded">{uploadCount}</span>
              <span className="pm-child-sep">/</span>
              <span className="pm-child-total">{descCount}</span>
            </span>
          )}

          {canClassify && (
            <div className="pm-classify">
              {Object.entries(CLASS_CONFIG).map(([key, c]) => (
                <button
                  key={key}
                  className={`pm-cls-btn ${classification === key ? 'pm-cls-btn--active' : ''}`}
                  style={classification === key ? { color: c.color, background: c.bg, borderColor: c.border } : {}}
                  onClick={() => onClassify(node.ref, classification === key ? null : key)}
                  title={c.label}
                >{c.short}</button>
              ))}
            </div>
          )}

          {clsCfg ? (
            <span className="pm-status-badge" style={{ color: clsCfg.color, background: clsCfg.bg, borderColor: clsCfg.border }}>
              {clsCfg.label}
            </span>
          ) : (
            <span className="pm-status-badge" style={{ color: cfg.color, background: cfg.bg, borderColor: cfg.border }}>
              {cfg.label}
            </span>
          )}
        </div>
      </div>

      {isExpanded && visibleChildren.length > 0 && (
        <div className="pm-children" style={{ '--depth': depth }}>
          {visibleChildren.map(child => (
            <TreeNode
              key={child.ref}
              node={child}
              depth={depth + 1}
              searchQuery={searchQuery}
              forceExpand={forceExpand}
              classifications={classifications}
              onClassify={onClassify}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Stats bar ──────────────────────────────────────────────────────────────────

function StatsBar({ refMap, seriesRoot, classifications }) {
  const nodes = [...refMap.values()].filter(n =>
    n.ref === seriesRoot || n.ref.startsWith(seriesRoot + '.')
  )
  const uploaded    = nodes.filter(n => n.sources.has('uploaded')).length
  const assessed    = nodes.filter(n => n.sources.has('assessed') && !n.sources.has('uploaded')).length
  const seen        = nodes.filter(n => n.sources.has('seen') && !n.sources.has('uploaded') && !n.sources.has('assessed')).length
  const hopexOnly   = nodes.filter(n => !n.sources.has('uploaded') && !n.sources.has('assessed') && !n.sources.has('seen')).length
  const classified  = Object.values(classifications).filter(Boolean).length

  return (
    <div className="pm-stats">
      <div className="pm-stat pm-stat--uploaded">
        <span className="pm-stat-num">{uploaded}</span>
        <span className="pm-stat-label">Uploaded</span>
      </div>
      <div className="pm-stat pm-stat--assessed">
        <span className="pm-stat-num">{assessed}</span>
        <span className="pm-stat-label">Assessed only</span>
      </div>
      <div className="pm-stat pm-stat--seen">
        <span className="pm-stat-num">{seen}</span>
        <span className="pm-stat-label">Referenced</span>
      </div>
      <div className="pm-stat pm-stat--hopex">
        <span className="pm-stat-num">{hopexOnly}</span>
        <span className="pm-stat-label">Not uploaded</span>
      </div>
      <div className="pm-stat pm-stat--classified">
        <span className="pm-stat-num">{classified}</span>
        <span className="pm-stat-label">Classified</span>
      </div>
    </div>
  )
}

// ── Main ───────────────────────────────────────────────────────────────────────

export default function ProcessMapPage({ diagrams, refMapData, onClose, onApplyInstructions, currentInstructions }) {
  const [search,          setSearch]          = useState('')
  const [seriesFilter,    setSeriesFilter]     = useState('6')
  const [expandAll,       setExpandAll]        = useState(false)
  const [statusFilter,    setStatusFilter]     = useState('all')
  const [classifications, setClassifications]  = useState({})
  const [applied,         setApplied]          = useState(false)

  const refMap = useMemo(() => buildRefMap(diagrams, refMapData), [diagrams, refMapData])

  const topSeries = useMemo(() => {
    const s = new Set()
    for (const ref of refMap.keys()) s.add(ref.split('.')[0])
    return [...s].sort((a, b) => parseInt(a) - parseInt(b))
  }, [refMap])

  const tree = useMemo(() => buildTree(refMap, seriesFilter), [refMap, seriesFilter])

  const filteredTree = useMemo(() => {
    if (statusFilter === 'all') return tree
    function filterNodes(nodes) {
      return nodes
        .map(n => ({ ...n, children: filterNodes(n.children) }))
        .filter(n => getStatus(n) === statusFilter || n.children.length > 0)
    }
    return filterNodes(tree)
  }, [tree, statusFilter])

  const activeSearch = search.trim()

  function handleClassify(ref, value) {
    setClassifications(prev => ({ ...prev, [ref]: value }))
    setApplied(false)
  }

  function clearClassifications() {
    setClassifications({})
    setApplied(false)
  }

  const instructions = generateInstructions(classifications, refMap)
  const classifiedCount = Object.values(classifications).filter(Boolean).length

  function handleApply() {
    const existing = (currentInstructions || '').trim()
    const combined = existing ? `${existing}\n${instructions}` : instructions
    onApplyInstructions(combined)
    setApplied(true)
  }

  return (
    <div className="pm-overlay">
      <div className="pm-page">

        {/* ── Header ── */}
        <div className="pm-header">
          <div className="pm-header-left">
            <div className="pm-title">Process Map</div>
            <div className="pm-subtitle">Full Bupa process hierarchy · classify subprocesses here to generate Process Instructions</div>
          </div>
          <div className="pm-header-right">
            {classifiedCount > 0 && (
              <div className="pm-apply-bar">
                <span className="pm-apply-count">{classifiedCount} classified</span>
                <button className="pm-apply-btn" onClick={handleApply} disabled={!instructions}>
                  {applied ? '✓ Applied' : (currentInstructions?.trim() ? 'Append to Process Instructions' : 'Apply to Process Instructions')}
                </button>
                <button className="pm-clear-btn" onClick={clearClassifications} title="Clear all classifications">Clear</button>
              </div>
            )}
            <button className="pm-close" onClick={onClose} title="Close">✕</button>
          </div>
        </div>

        {/* ── Toolbar ── */}
        <div className="pm-toolbar">
          <div className="pm-toolbar-left">
            <div className="pm-series-tabs">
              {topSeries.map(s => (
                <button
                  key={s}
                  className={`pm-series-tab ${seriesFilter === s ? 'active' : ''}`}
                  onClick={() => { setSeriesFilter(s); setExpandAll(false) }}
                >{s}.x</button>
              ))}
            </div>
            <select
              className="pm-status-select"
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
            >
              <option value="all">All statuses</option>
              <option value="uploaded">Uploaded only</option>
              <option value="assessed">Assessed only</option>
              <option value="seen">Referenced only</option>
              <option value="hopex">Not yet uploaded</option>
            </select>
          </div>
          <div className="pm-toolbar-right">
            <input
              className="pm-search"
              type="text"
              placeholder="Search ref or name…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            <button
              className={`pm-expand-btn ${expandAll ? 'active' : ''}`}
              onClick={() => setExpandAll(v => !v)}
            >{expandAll ? '⊟ Collapse all' : '⊞ Expand all'}</button>
          </div>
        </div>

        {/* ── Stats ── */}
        <StatsBar refMap={refMap} seriesRoot={seriesFilter} classifications={classifications} />

        {/* ── Legend ── */}
        <div className="pm-legend">
          <span className="pm-legend-label">Status:</span>
          {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
            <span key={key} className="pm-legend-item" style={{ color: cfg.color, background: cfg.bg, borderColor: cfg.border }}>
              {cfg.label}
            </span>
          ))}
          <span className="pm-legend-divider">·</span>
          <span className="pm-legend-label">Classify:</span>
          {Object.entries(CLASS_CONFIG).map(([key, cfg]) => (
            <span key={key} className="pm-legend-item" style={{ color: cfg.color, background: cfg.bg, borderColor: cfg.border }}>
              [{cfg.short}] {cfg.label}
            </span>
          ))}
          <span className="pm-legend-hint">x/y = uploaded / total descendants</span>
        </div>

        {/* ── Tree ── */}
        <div className="pm-tree-container">
          {filteredTree.length === 0 ? (
            <div className="pm-empty">No processes found for series {seriesFilter}.x</div>
          ) : (
            filteredTree.map(node => (
              <TreeNode
                key={node.ref}
                node={node}
                depth={0}
                searchQuery={activeSearch}
                forceExpand={expandAll || !!activeSearch}
                classifications={classifications}
                onClassify={handleClassify}
              />
            ))
          )}
        </div>

        {/* ── Instructions preview (when classified) ── */}
        {instructions && (
          <div className="pm-instructions-preview">
            <div className="pm-instructions-label">Generated Process Instructions preview:</div>
            <div className="pm-instructions-text">{instructions}</div>
          </div>
        )}

      </div>
    </div>
  )
}
