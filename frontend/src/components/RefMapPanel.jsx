import { useState, useRef } from 'react'
import { HOPEX_REFS } from '../hopexRefs.js'
import './RefMapPanel.css'

// ── Shared case type picker (reused in flow classify) ─────────────────────────
const EXISTING_CASE_TYPES_FLOW = [
  'Policy Enrolment', 'Membership Change', 'Premium Billing & Payment',
  'Fund Transfer', 'Government Compliance Obligation', 'Policy Cancellation',
  'Change of Cover', 'Add Person to Policy', 'Remove Person from Policy',
]
const CREATE_NEW_FLOW = '__new__'

function CaseTypePicker({ value, newName, onChange }) {
  return (
    <div className="flow-ct-picker">
      <select
        className="flow-ct-select"
        value={value || ''}
        onChange={e => onChange({ value: e.target.value, newName: '' })}
      >
        <option value="">— select or create —</option>
        {EXISTING_CASE_TYPES_FLOW.map(ct => <option key={ct} value={ct}>{ct}</option>)}
        <option disabled>──────────</option>
        <option value={CREATE_NEW_FLOW}>+ Create new…</option>
      </select>
      {value === CREATE_NEW_FLOW && (
        <input
          className="flow-ct-name-input"
          type="text"
          placeholder="PascalCase case type name e.g. ManageCustomerDetails"
          value={newName || ''}
          onChange={e => onChange({ value: CREATE_NEW_FLOW, newName: e.target.value })}
          autoFocus
        />
      )}
    </div>
  )
}

// ── Call graph text view ───────────────────────────────────────────────────────
function CallGraphView({ callGraph, nodes, suggestedOrder, branchFilter,
                         classifications, onClassify, onApply, onClear, currentInstructions }) {
  const refFromFn = fn => { const m = fn.match(/^(\d+(?:\.\d+)+)/); return m ? m[1] : null }
  const nameMap   = Object.fromEntries(nodes.map(n => [n.source_ref, n.name]))
  const getName   = ref => nameMap[ref] || HOPEX_REFS[ref] || ''

  const allRefs = suggestedOrder
    .map(refFromFn).filter(Boolean)
    .sort((a, b) => {
      const ka = a.split('.').map(Number), kb = b.split('.').map(Number)
      for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
        const d = (ka[i] ?? 0) - (kb[i] ?? 0); if (d !== 0) return d
      }
      return 0
    })

  const f = branchFilter.trim()
  const visibleRefs = f ? allRefs.filter(r => r === f || r.startsWith(f + '.')) : allRefs

  if (visibleRefs.length === 0) return (
    <div className="refmap-flow-empty">
      <div className="refmap-flow-empty-title">No uploaded diagrams match "{f}"</div>
    </div>
  )

  const calledBy = {}
  for (const [caller, callees] of Object.entries(callGraph)) {
    for (const callee of callees) {
      if (!calledBy[callee]) calledBy[callee] = []
      calledBy[callee].push(caller)
    }
  }

  const classifiedCount = Object.values(classifications).filter(c => c?.role).length
  const instructions = buildFlowInstructions(classifications, getName)

  return (
    <div className="flow-list">
      {/* ── Apply bar ── */}
      {classifiedCount > 0 && (
        <div className="flow-apply-bar">
          <span className="flow-apply-count">{classifiedCount} classified</span>
          <button className="flow-apply-btn" onClick={() => onApply(instructions)}>
            {currentInstructions?.trim() ? 'Append to Process Instructions' : 'Apply to Process Instructions'}
          </button>
          <button className="flow-clear-btn" onClick={onClear}>Clear all</button>
          {instructions && <span className="flow-apply-preview">{instructions}</span>}
        </div>
      )}

      {visibleRefs.map(ref => {
        const calls   = (callGraph[ref] || []).filter(r => allRefs.includes(r))
        const callers = (calledBy[ref]  || []).filter(r => allRefs.includes(r))
        const name    = getName(ref)
        const cls     = classifications[ref] || {}
        const isCT    = cls.role === 'case_type'
        const isIL    = cls.role === 'inline'

        return (
          <div key={ref} className={`flow-node${isCT ? ' flow-node--ct' : ''}`}>

            {/* Header row: ref + name + CT/IL buttons */}
            <div className="flow-node-header">
              <span className="flow-node-ref">{ref}</span>
              {name && <span className="flow-node-name">{name}</span>}
              <div className="flow-cls-btns">
                <button
                  className={`flow-cls-btn ${isCT ? 'flow-cls-btn--ct-active' : ''}`}
                  onClick={() => onClassify(ref, isCT ? null : 'case_type', calls)}
                  title="Mark as Case Type — this process becomes its own Pega case"
                >Case Type</button>
                <button
                  className={`flow-cls-btn ${isIL ? 'flow-cls-btn--il-active' : ''}`}
                  onClick={() => onClassify(ref, isIL ? null : 'inline', [])}
                  title="Mark as Inline — embedded steps in the parent case"
                >Inline</button>
              </div>
            </div>

            {/* Case type name picker — shown when CT selected */}
            {isCT && (
              <CaseTypePicker
                value={cls.ctValue || ''}
                newName={cls.ctNewName || ''}
                onChange={({ value, newName }) =>
                  onClassify(ref, 'case_type', calls, { ctValue: value, ctNewName: newName })
                }
              />
            )}

            {/* Called-by row */}
            {callers.length > 0 && (
              <div className="flow-node-row flow-node-row--callers">
                <span className="flow-node-arrow flow-node-arrow--in">↙ called by</span>
                <span className="flow-node-refs">
                  {callers.map(r => (
                    <span key={r} className="flow-ref-chip flow-ref-chip--caller">
                      {r}{getName(r) ? ` · ${getName(r).slice(0, 28)}` : ''}
                    </span>
                  ))}
                </span>
              </div>
            )}

            {/* Calls row — chips get CC/IL buttons when parent is CT */}
            {calls.length > 0 && (
              <div className="flow-node-row flow-node-row--calls">
                <span className="flow-node-arrow flow-node-arrow--out">↗ calls</span>
                <div className="flow-node-refs">
                  {calls.map(r => {
                    const childCls = classifications[r]?.role
                    const isCC = childCls === 'child_case'
                    const isChildIL = childCls === 'inline'
                    return (
                      <div key={r} className="flow-callee-wrap">
                        <span className={`flow-ref-chip flow-ref-chip--callee${isCC ? ' flow-ref-chip--cc' : ''}${isChildIL ? ' flow-ref-chip--il' : ''}`}>
                          {r}{getName(r) ? ` · ${getName(r).slice(0, 25)}` : ''}
                        </span>
                        {isCT && (
                          <span className="flow-callee-btns">
                            <button
                              className={`flow-mini-btn ${isCC ? 'flow-mini-btn--cc' : ''}`}
                              onClick={() => onClassify(r, isCC ? 'inline' : 'child_case', [])}
                              title="Child Case — independent Pega case called from parent"
                            >CC</button>
                            <button
                              className={`flow-mini-btn ${isChildIL ? 'flow-mini-btn--il' : ''}`}
                              onClick={() => onClassify(r, isChildIL ? 'inline' : 'inline', [])}
                              title="Inline — embedded within parent case"
                            >IL</button>
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {callers.length === 0 && calls.length === 0 && (
              <div className="flow-node-row flow-node-isolated">no connections detected</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Instruction builder for flow classifications ───────────────────────────────
function buildFlowInstructions(classifications, getName) {
  const entries = Object.entries(classifications)
    .filter(([, c]) => c?.role)
    .sort(([a], [b]) => {
      const ka = a.split('.').map(Number), kb = b.split('.').map(Number)
      for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
        const d = (ka[i] ?? 0) - (kb[i] ?? 0); if (d !== 0) return d
      }
      return 0
    })

  return entries.map(([ref, c]) => {
    const name = (c.ctValue === CREATE_NEW_FLOW ? c.ctNewName : c.ctValue) || getName(ref) || ref
    if (c.role === 'case_type')  return `${ref} is a Case Type named ${name}`
    if (c.role === 'child_case') return `${ref} is a child case`
    if (c.role === 'inline')     return `${ref} is inline`
    return null
  }).filter(Boolean).join('; ')
}

const TYPE_LABELS = {
  subprocess: 'Subprocess',
  task:       'Task',
  gateway:    'Gateway',
  event:      'Event',
  unknown:    'Mentioned',
}

// Known Bupa / Pega case types for the existing case type dropdown
const EXISTING_CASE_TYPES = [
  'Policy Enrolment',
  'Membership Change',
  'Premium Billing & Payment',
  'Fund Transfer',
  'Government Compliance Obligation',
  'Policy Cancellation',
  'Change of Cover',
  'Add Person to Policy',
  'Remove Person from Policy',
]

function buildInstructions(nodes, tags, childDetails) {
  const subprocesses = nodes.filter(n => n.type === 'subprocess')
  if (subprocesses.length === 0) return ''

  return subprocesses.map(node => {
    const tag     = tags[node.source_ref] || 'inline'
    const details = childDetails[node.source_ref] || {}

    if (tag === 'child_case') {
      const selected = details.selected || ''
      const newName  = (details.newName || '').trim()
      const isNew    = selected === CREATE_NEW

      if (isNew && newName) {
        return `${node.source_ref} is a new child case named "${newName}"`
      }
      if (!isNew && selected) {
        return `${node.source_ref} is an existing child case named "${selected}"`
      }
      return `${node.source_ref} is a child case`
    }
    return `${node.source_ref} is an inline subprocess`
  }).join('; ')
}

// ── Child case detail expander ─────────────────────────────────────────────

const CREATE_NEW = '__create_new__'

function ChildCaseDetail({ sourceRef, details, onChange }) {
  const selected  = details.selected || ''   // value from the dropdown
  const newName   = details.newName  || ''   // typed name when creating new
  const isCreating = selected === CREATE_NEW

  function handleSelect(e) {
    onChange(sourceRef, { selected: e.target.value, newName: '' })
  }

  function handleNewName(e) {
    onChange(sourceRef, { selected, newName: e.target.value })
  }

  return (
    <div className="child-case-detail">
      <div className="child-case-field">
        <label className="child-case-label">Case type</label>
        <select
          className="child-case-select"
          value={selected}
          onChange={handleSelect}
        >
          <option value="">— select or create —</option>
          {EXISTING_CASE_TYPES.map(ct => (
            <option key={ct} value={ct}>{ct}</option>
          ))}
          <option disabled>──────────────</option>
          <option value={CREATE_NEW}>+ Create new case type…</option>
        </select>
      </div>

      {isCreating && (
        <div className="child-case-field">
          <label className="child-case-label">New case type name</label>
          <input
            className="child-case-name-input"
            type="text"
            placeholder="e.g. PolicyChangeOfCover"
            value={newName}
            onChange={handleNewName}
            autoFocus
          />
          <span className="child-case-hint">Use PascalCase, no spaces — this becomes the Pega case type ID</span>
        </div>
      )}
    </div>
  )
}

// ── Tree view ──────────────────────────────────────────────────────────────

function TreeNode({ node, tags, childDetails, onToggle, onChildDetail }) {
  const indent    = node.depth * 20
  const isSub     = node.type === 'subprocess'
  const isChild   = (tags[node.source_ref] || 'inline') === 'child_case'

  return (
    <div className="refmap-tree-node-wrap" style={{ paddingLeft: `${indent + 8}px` }}>
      <div className="refmap-tree-node">
        {node.depth > 0 && <span className="refmap-tree-connector">└─</span>}
        <span className="refmap-ref">{node.source_ref}</span>
        <span className="refmap-name" title={node.name}>{node.name || '—'}</span>
        <span className={`refmap-type-badge refmap-type-badge--${node.type}`}>
          {TYPE_LABELS[node.type] || node.type}
        </span>
        {isSub && (
          <div className="refmap-toggle">
            <button
              className={`refmap-toggle-btn ${isChild ? 'active-child' : ''}`}
              onClick={() => onToggle(node.source_ref, 'child_case')}
              title="Independent Pega case — maps to <callActivity>"
            >Child case</button>
            <button
              className={`refmap-toggle-btn ${!isChild ? 'active-inline' : ''}`}
              onClick={() => onToggle(node.source_ref, 'inline')}
              title="Embedded in parent case — maps to <subProcess>"
            >Inline</button>
          </div>
        )}
      </div>
      {isSub && isChild && (
        <ChildCaseDetail
          sourceRef={node.source_ref}
          details={childDetails[node.source_ref] || {}}
          onChange={onChildDetail}
        />
      )}
    </div>
  )
}

// ── Checklist view ─────────────────────────────────────────────────────────

function CheckRow({ node, tags, childDetails, onToggle, onChildDetail }) {
  const isSub   = node.type === 'subprocess'
  const isChild = (tags[node.source_ref] || 'inline') === 'child_case'

  return (
    <div className={`refmap-check-wrap${isSub ? ' refmap-check-wrap--subprocess' : ''}`}>
      <div className={`refmap-check-row${isSub ? ' refmap-check-row--subprocess' : ''}`}>
        <span className="refmap-check-ref">{node.source_ref}</span>
        <span className={`refmap-type-badge refmap-type-badge--${node.type}`}>
          {TYPE_LABELS[node.type] || node.type}
        </span>
        <span className="refmap-check-name" title={node.name}>{node.name || '—'}</span>
        {isSub && (
          <div className="refmap-toggle">
            <button
              className={`refmap-toggle-btn ${isChild ? 'active-child' : ''}`}
              onClick={() => onToggle(node.source_ref, 'child_case')}
              title="Independent Pega case — maps to <callActivity>"
            >Child case</button>
            <button
              className={`refmap-toggle-btn ${!isChild ? 'active-inline' : ''}`}
              onClick={() => onToggle(node.source_ref, 'inline')}
              title="Embedded in parent case — maps to <subProcess>"
            >Inline</button>
          </div>
        )}
      </div>
      {isSub && isChild && (
        <ChildCaseDetail
          sourceRef={node.source_ref}
          details={childDetails[node.source_ref] || {}}
          onChange={onChildDetail}
        />
      )}
    </div>
  )
}

// ── Main panel ─────────────────────────────────────────────────────────────

export default function RefMapPanel({ refMapData, onApplyInstructions, onApplyOrder, currentOrder, currentInstructions }) {
  const [activeTab,    setActiveTab]    = useState('wizard')
  const [tags,         setTags]         = useState({})
  const [childDetails, setChildDetails] = useState({})
  const [applied,      setApplied]      = useState(false)
  const [orderApplied, setOrderApplied] = useState(false)
  const [collapsed,    setCollapsed]    = useState(false)
  const [startingRef,  setStartingRef]  = useState('')
  const [flowBranch,         setFlowBranch]         = useState('')
  const [flowClassifications, setFlowClassifications] = useState({})

  // ── Wizard state ────────────────────────────────────────────────────────────
  const wizInit = {
    step: 0,                // 0=idle 1=set-root 2=classify-children 3=drill-into-case 4=done
    rootRef: '',
    rootName: '',
    inputRef: '',
    inputRootName: '',
    rootError: '',
    decisions: {},          // { [source_ref]: { classification, name } }
    caseTypeQueue: [],      // source_refs of step-2 children classified as case_type
    currentCaseTypeIdx: 0,
    extraRefs: {},          // { [parentRef]: [manually added source_refs] }
    addRefInput: '',        // controlled input for manual ref addition
    rowOrder: {},           // { [parentRef]: [source_refs in display order] }
  }
  const dragItem     = useRef(null)
  const dragOverItem = useRef(null)
  const [wiz, setWiz] = useState(wizInit)
  const wizPatch = patch => setWiz(prev => ({ ...prev, ...patch }))

  // Direct children of parentRef: hierarchical children (parentRef.N) PLUS
  // any cross-series subprocess calls from the call graph (e.g. 6.2.2.9 called
  // by 6.2.3.1.1 even though it's a different series).
  function getDirectChildren(parentRef) {
    const depth = parentRef.split('.').length
    const hierarchical = nodes.filter(n =>
      n.source_ref.startsWith(parentRef + '.') &&
      n.source_ref.split('.').length === depth + 1
    )
    const hierarchicalRefs = new Set(hierarchical.map(n => n.source_ref))

    // Add call-graph edges not already covered by hierarchical children
    const calledRefs = call_graph[parentRef] || []
    const crossSeries = calledRefs
      .filter(ref => !hierarchicalRefs.has(ref))
      .map(ref => nodes.find(n => n.source_ref === ref) || {
        source_ref: ref, name: '', type: 'subprocess', depth: 0
      })

    // Add manually entered refs
    const manualRefs = (wiz.extraRefs[parentRef] || [])
      .filter(ref => !hierarchicalRefs.has(ref) && !calledRefs.includes(ref))
      .map(ref => nodes.find(n => n.source_ref === ref) || {
        source_ref: ref, name: '', type: 'subprocess', depth: 0
      })

    return [...hierarchical, ...crossSeries, ...manualRefs]
  }

  function buildWizardInstructions(rootRef, rootName, decisions) {
    const prefix = `Root: ${rootRef} (${rootName}).`
    const parts = Object.entries(decisions)
      .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
      .map(([ref, d]) => {
        if (d.classification === 'case_type')  return `${ref} is a Case Type named ${d.name || ref}`
        if (d.classification === 'child_case') return `${ref} is a child case named ${d.name || ref}`
        return `${ref} is inline`
      })
    return parts.length ? `${prefix} ${parts.join('; ')}` : prefix
  }

  function getOrderedChildren(parentRef) {
    const children = getDirectChildren(parentRef)
    const storedOrder = wiz.rowOrder[parentRef]
    if (!storedOrder) return children
    const byRef = Object.fromEntries(children.map(n => [n.source_ref, n]))
    const ordered = storedOrder.filter(r => byRef[r]).map(r => byRef[r])
    const remaining = children.filter(n => !storedOrder.includes(n.source_ref))
    return [...ordered, ...remaining]
  }

  function handleDragSort(parentRef) {
    if (!dragItem.current || !dragOverItem.current || dragItem.current === dragOverItem.current) return
    const refs = getOrderedChildren(parentRef).map(n => n.source_ref)
    const from = refs.indexOf(dragItem.current)
    const to   = refs.indexOf(dragOverItem.current)
    if (from === -1 || to === -1) return
    const newOrder = [...refs]
    newOrder.splice(from, 1)
    newOrder.splice(to, 0, dragItem.current)
    wizPatch({ rowOrder: { ...wiz.rowOrder, [parentRef]: newOrder } })
    dragItem.current = null
    dragOverItem.current = null
  }

  function wizDecide(sourceRef, classification, name = '') {
    wizPatch({ decisions: { ...wiz.decisions, [sourceRef]: { classification, name } } })
  }

  function wizNextFromStep2() {
    const queue = getDirectChildren(wiz.rootRef)
      .filter(n => wiz.decisions[n.source_ref]?.classification === 'case_type')
      .map(n => n.source_ref)
    if (queue.length === 0) {
      wizPatch({ step: 4, caseTypeQueue: [] })
    } else {
      wizPatch({ step: 3, caseTypeQueue: queue, currentCaseTypeIdx: 0 })
    }
  }

  function wizNextFromStep3() {
    const next = wiz.currentCaseTypeIdx + 1
    if (next < wiz.caseTypeQueue.length) {
      wizPatch({ currentCaseTypeIdx: next })
    } else {
      wizPatch({ step: 4 })
    }
  }

  function wizConfirmRoot() {
    const ref = wiz.inputRef.trim()
    const node = nodes.find(n => n.source_ref === ref)
    if (!node && ref) {
      wizPatch({ rootError: `"${ref}" not found in extracted refs — check the reference number.` })
      return
    }
    wizPatch({
      rootRef: ref,
      rootName: wiz.inputRootName.trim() || node?.name || ref,
      rootError: '',
      decisions: {},
      caseTypeQueue: [],
      currentCaseTypeIdx: 0,
      step: 2,
    })
  }

  function renderWizardChildRows(parentRef, step) {
    const children = getOrderedChildren(parentRef)
    if (children.length === 0) return (
      <div className="wizard-empty">No child refs found for {parentRef} in the extracted data.</div>
    )
    return children.map(node => {
      const dec = wiz.decisions[node.source_ref]
      const isCaseType  = dec?.classification === 'case_type'
      const isChildCase = dec?.classification === 'child_case'
      const isInline    = dec?.classification === 'inline'
      return (
        <div
          key={node.source_ref}
          className="wizard-child-row"
          draggable
          onDragStart={() => { dragItem.current = node.source_ref }}
          onDragEnter={() => { dragOverItem.current = node.source_ref }}
          onDragEnd={() => handleDragSort(parentRef)}
          onDragOver={e => e.preventDefault()}
        >
          <div className="wizard-child-row-main">
            <span className="wizard-drag-handle">⠿</span>
            <span className="refmap-ref">{node.source_ref}</span>
            <span className="wizard-child-node-name" title={node.name}>{node.name || '—'}</span>
            <div className="refmap-toggle" style={{ marginLeft: 'auto', flexShrink: 0 }}>
              {step === 2 ? (<>
                <button
                  className={`refmap-toggle-btn ${isCaseType ? 'active-child' : ''}`}
                  onClick={() => wizDecide(node.source_ref, 'case_type', dec?.name ?? node.name ?? '')}
                >Case Type</button>
                <button
                  className={`refmap-toggle-btn ${isInline ? 'active-inline' : ''}`}
                  onClick={() => wizDecide(node.source_ref, 'inline', '')}
                >Inline</button>
              </>) : (<>
                <button
                  className={`refmap-toggle-btn ${isChildCase ? 'active-child' : ''}`}
                  onClick={() => wizDecide(node.source_ref, 'child_case', dec?.name ?? node.name ?? '')}
                >Child Case</button>
                <button
                  className={`refmap-toggle-btn ${isInline ? 'active-inline' : ''}`}
                  onClick={() => wizDecide(node.source_ref, 'inline', '')}
                >Inline</button>
              </>)}
            </div>
          </div>
          {(isCaseType || isChildCase) && (
            <div className="wizard-child-row-name-wrap">
              <input
                className="wizard-child-row-name-input"
                type="text"
                placeholder={`Business name for ${node.source_ref}…`}
                value={dec?.name || ''}
                onChange={e => wizDecide(node.source_ref, dec.classification, e.target.value)}
                autoFocus
              />
            </div>
          )}
        </div>
      )
    })
  }

  function renderWizard() {
    // Step 0 — idle
    if (wiz.step === 0) return (
      <div className="wizard-idle">
        <div className="wizard-idle-title">Architecture Wizard</div>
        <div className="wizard-idle-body">
          Work through your process hierarchy level by level — classify each subprocess
          as a Case Type, Child Case, or Inline before generating the BPMN.
        </div>
        <button className="wizard-btn-primary" onClick={() => wizPatch({ step: 1 })}>
          Start Wizard
        </button>
      </div>
    )

    // Step 1 — set root
    if (wiz.step === 1) return (
      <div className="wizard-step">
        <div className="wizard-step-header">Step 1 — Set starting Case Type</div>
        <div className="wizard-step-sub">Enter the top-level process ref you are working on.</div>
        <div className="wizard-field">
          <label className="wizard-label">Process ref</label>
          <input
            className="wizard-input"
            type="text"
            placeholder="e.g. 6.2.3.1"
            value={wiz.inputRef}
            onChange={e => wizPatch({ inputRef: e.target.value, rootError: '' })}
          />
        </div>
        <div className="wizard-field">
          <label className="wizard-label">Business name</label>
          <input
            className="wizard-input"
            type="text"
            placeholder="e.g. Change Policy Information"
            value={wiz.inputRootName}
            onChange={e => wizPatch({ inputRootName: e.target.value })}
          />
        </div>
        {wiz.rootError && <div className="wizard-error">{wiz.rootError}</div>}
        <div className="wizard-actions">
          <button className="wizard-btn-primary" onClick={wizConfirmRoot}
            disabled={!wiz.inputRef.trim()}>
            Next →
          </button>
          <button className="wizard-btn-secondary" onClick={() => wizPatch({ step: 0 })}>
            Cancel
          </button>
        </div>
      </div>
    )

    // Step 2 — classify root's direct children
    if (wiz.step === 2) {
      const children = getDirectChildren(wiz.rootRef)
      const decided  = children.filter(n => wiz.decisions[n.source_ref]).length
      const allDone  = decided === children.length && children.length > 0
      return (
        <div className="wizard-step">
          <div className="wizard-breadcrumb">
            <span>{wiz.rootRef}</span>
            <span className="wizard-breadcrumb-sep">·</span>
            <span style={{ color: '#0D1B3E', fontWeight: 700 }}>{wiz.rootName}</span>
          </div>
          <div className="wizard-step-header">Step 2 — Classify direct children</div>
          <div className="wizard-step-sub">
            Is each subprocess a standalone <strong>Case Type</strong> or embedded <strong>Inline</strong>?
            <span className="wizard-progress"> {decided}/{children.length} decided</span>
          </div>
          <div className="wizard-child-rows">
            {renderWizardChildRows(wiz.rootRef, 2)}
          </div>
          <div className="wizard-actions">
            <button className="wizard-btn-primary" onClick={wizNextFromStep2} disabled={!allDone}>
              Next →
            </button>
            <button className="wizard-btn-secondary" onClick={() => wizPatch({ step: 1 })}>
              ← Back
            </button>
          </div>
        </div>
      )
    }

    // Step 3 — drill into each case type
    if (wiz.step === 3) {
      const currentRef  = wiz.caseTypeQueue[wiz.currentCaseTypeIdx]
      const currentName = wiz.decisions[currentRef]?.name || currentRef
      const children    = getDirectChildren(currentRef)
      const decided     = children.filter(n => wiz.decisions[n.source_ref]).length
      const allDone     = decided === children.length && children.length > 0
      const isLast      = wiz.currentCaseTypeIdx === wiz.caseTypeQueue.length - 1
      return (
        <div className="wizard-step">
          <div className="wizard-breadcrumb">
            <span>{wiz.rootRef}</span>
            <span className="wizard-breadcrumb-sep">›</span>
            <span style={{ color: '#0369a1', fontWeight: 700 }}>{currentRef}</span>
          </div>
          <div className="wizard-step-header">
            {currentRef} — {currentName}
            <span className="wizard-queue-pos"> ({wiz.currentCaseTypeIdx + 1} of {wiz.caseTypeQueue.length})</span>
          </div>
          <div className="wizard-step-sub">
            For each subprocess: is it a standalone <strong>Child Case</strong> or embedded <strong>Inline</strong>?
            <span className="wizard-progress"> {decided}/{children.length} decided</span>
            <div className="wizard-inline-note">Steps without a reference number (e.g. View customer details) are not listed here — they are automatically treated as inline in the BPMN output.</div>
          </div>
          <div className="wizard-child-rows">
            {renderWizardChildRows(currentRef, 3)}
          </div>
          <div className="wizard-add-ref">
            <input
              className="wizard-input wizard-add-ref-input"
              type="text"
              placeholder="Add missing ref (e.g. 6.2.2.9)"
              value={wiz.addRefInput}
              onChange={e => wizPatch({ addRefInput: e.target.value })}
              onKeyDown={e => {
                if (e.key === 'Enter' && wiz.addRefInput.trim()) {
                  const ref = wiz.addRefInput.trim()
                  const existing = wiz.extraRefs[currentRef] || []
                  if (!existing.includes(ref)) {
                    wizPatch({ extraRefs: { ...wiz.extraRefs, [currentRef]: [...existing, ref] }, addRefInput: '' })
                  }
                }
              }}
            />
            <button className="wizard-btn-secondary" onClick={() => {
              const ref = wiz.addRefInput.trim()
              if (!ref) return
              const existing = wiz.extraRefs[currentRef] || []
              if (!existing.includes(ref)) {
                wizPatch({ extraRefs: { ...wiz.extraRefs, [currentRef]: [...existing, ref] }, addRefInput: '' })
              }
            }}>+ Add</button>
          </div>
          <div className="wizard-actions">
            <button className="wizard-btn-primary" onClick={wizNextFromStep3} disabled={!allDone}>
              {isLast ? 'Finish →' : `Next: ${wiz.caseTypeQueue[wiz.currentCaseTypeIdx + 1]} →`}
            </button>
            <button className="wizard-btn-secondary"
              onClick={() => wiz.currentCaseTypeIdx > 0
                ? wizPatch({ currentCaseTypeIdx: wiz.currentCaseTypeIdx - 1 })
                : wizPatch({ step: 2 })}>
              ← Back
            </button>
          </div>
        </div>
      )
    }

    // Step 4 — done
    if (wiz.step === 4) {
      const instructions = buildWizardInstructions(wiz.rootRef, wiz.rootName, wiz.decisions)
      return (
        <div className="wizard-step">
          <div className="wizard-step-header">✓ Wizard complete</div>
          <div className="wizard-step-sub">Review the generated Process Instructions below, then apply.</div>
          <pre className="wizard-instructions-preview">{instructions}</pre>
          <div className="wizard-done-actions">
            <button className="wizard-btn-primary" onClick={() => {
              const existing = (currentInstructions || '').trim()
              const combined = existing ? `${existing}\n${instructions}` : instructions
              onApplyInstructions(combined)
              wizPatch({ step: 0, ...wizInit })
            }}>
              {currentInstructions?.trim() ? 'Append to Process Instructions' : 'Apply to Process Instructions'}
            </button>
            <button className="wizard-btn-secondary" onClick={() => wizPatch({ step: 3, currentCaseTypeIdx: wiz.caseTypeQueue.length - 1 })}>
              ← Back
            </button>
            <button className="wizard-btn-secondary" onClick={() => setWiz(wizInit)}>
              Start Over
            </button>
          </div>
        </div>
      )
    }
  }

  if (!refMapData) return null
  const { nodes = [], gaps = [], suggested_order = [], image_refs = {}, call_graph = {} } = refMapData
  if (nodes.length === 0) return null

  const subprocessCount  = nodes.filter(n => n.type === 'subprocess').length
  const unknownCount     = nodes.filter(n => n.type === 'unknown').length
  const isFallback       = unknownCount > 0 && unknownCount === nodes.length

  // Extract leading ref from filename e.g. "6.2.3.1 Change Policy.png" → "6.2.3.1"
  function refFromFilename(fn) {
    const m = fn.match(/^(\d+(?:\.\d+)+)/)
    return m ? m[1] : null
  }

  // Pin the user-specified starting ref to position 1, keep call-graph order for the rest
  function getDisplayOrder() {
    const trimmed = startingRef.trim()
    if (!trimmed) return suggested_order
    const target = suggested_order.find(fn => {
      const fnRef = refFromFilename(fn)
      if (fnRef && (fnRef === trimmed || fnRef.startsWith(trimmed + '.'))) return true
      return (image_refs[fn] || []).some(r => r === trimmed || r.startsWith(trimmed + '.'))
    })
    if (!target) return suggested_order
    return [target, ...suggested_order.filter(fn => fn !== target)]
  }
  const display_order = getDisplayOrder()

  // Check if suggested order differs from current upload order
  const orderDiffers = display_order.length > 1 &&
    JSON.stringify(display_order) !== JSON.stringify(currentOrder.filter(fn => display_order.includes(fn)))

  function handleApplyOrder() {
    onApplyOrder(display_order)
    setOrderApplied(true)
  }

  function handleToggle(sourceRef, value) {
    setTags(prev => ({ ...prev, [sourceRef]: value }))
    setApplied(false)
  }

  function handleChildDetail(sourceRef, details) {
    setChildDetails(prev => ({ ...prev, [sourceRef]: details }))
    setApplied(false)
  }

  function handleApply() {
    const text = buildInstructions(nodes, tags, childDetails)
    onApplyInstructions(text)
    setApplied(true)
  }

  const instructions = buildInstructions(nodes, tags, childDetails)

  return (
    <section className="panel refmap-panel">
      <div className="refmap-header">
        <h2>
          Reference Map
          <span className="refmap-count">{nodes.length} refs</span>
          {gaps.length > 0 && (
            <span className="refmap-count refmap-count--gaps">{gaps.length} gap{gaps.length > 1 ? 's' : ''}</span>
          )}
        </h2>
        <button className="panel-collapse-btn" onClick={() => setCollapsed(v => !v)} title={collapsed ? 'Expand' : 'Collapse'}>
          {collapsed ? '▶' : '▼'}
        </button>
      </div>

      {collapsed && null}

      {!collapsed && isFallback && (
        <div className="refmap-info-banner">
          <div className="refmap-info-title">ℹ Reference numbers extracted from confidence notes</div>
          <div className="refmap-info-body">
            These refs were mentioned in the assessment but too small to read with full confidence.
            Shown for completeness — run Generate to extract names and types.
          </div>
        </div>
      )}

      {!collapsed && !isFallback && gaps.length > 0 && (
        <div className="refmap-gaps">
          <div className="refmap-gaps-title">⚠ {gaps.length} gap{gaps.length > 1 ? 's' : ''} detected</div>
          {gaps.map((g, i) => {
            // Extract the missing ref from the gap string so we can look up its name
            // Formats: "Missing parent: X.X (required by ...)" | "Gap: X.X not found (...)"
            const refMatch = g.match(/^(?:Missing parent|Gap):\s*([\d.]+)/)
            const missingRef = refMatch?.[1]
            const refName = missingRef ? HOPEX_REFS[missingRef] : null
            return (
              <div key={i} className="refmap-gap-item">
                <span className="refmap-gap-bullet">·</span>
                <span>
                  {g}
                  {refName && <span className="refmap-gap-desc"> — {refName}</span>}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {!collapsed && (
        <>
          <div className="refmap-tabs">
            <button
              className={`refmap-tab ${activeTab === 'wizard' ? 'active' : ''}`}
              onClick={() => setActiveTab('wizard')}
            >Wizard</button>
            <button
              className={`refmap-tab ${activeTab === 'hierarchy' ? 'active' : ''}`}
              onClick={() => setActiveTab('hierarchy')}
            >Hierarchy</button>
            <button
              className={`refmap-tab ${activeTab === 'checklist' ? 'active' : ''}`}
              onClick={() => setActiveTab('checklist')}
            >Checklist</button>
            <button
              className={`refmap-tab ${activeTab === 'flow' ? 'active' : ''}`}
              onClick={() => setActiveTab('flow')}
            >Flow</button>
          </div>

          {activeTab === 'hierarchy' && (
            <div className="refmap-tree">
              {nodes.map(node => (
                <TreeNode
                  key={node.source_ref}
                  node={node}
                  tags={tags}
                  childDetails={childDetails}
                  onToggle={handleToggle}
                  onChildDetail={handleChildDetail}
                />
              ))}
            </div>
          )}

          {activeTab === 'checklist' && (
            <div className="refmap-checklist">
              {nodes.map(node => (
                <CheckRow
                  key={node.source_ref}
                  node={node}
                  tags={tags}
                  childDetails={childDetails}
                  onToggle={handleToggle}
                  onChildDetail={handleChildDetail}
                />
              ))}
            </div>
          )}

          {activeTab === 'flow' && (
            <div className="refmap-flow">
              <div className="refmap-flow-toolbar">
                <input
                  className="refmap-flow-filter"
                  type="text"
                  placeholder="Filter to branch e.g. 6.2.3"
                  value={flowBranch}
                  onChange={e => setFlowBranch(e.target.value)}
                />
                {flowBranch && (
                  <button className="refmap-flow-clear" onClick={() => setFlowBranch('')}>✕ Show all</button>
                )}
                <span className="refmap-flow-hint">
                  {flowBranch
                    ? `Showing refs within ${flowBranch}`
                    : `${suggested_order.length} processes — enter a branch ref to focus`}
                </span>
              </div>
              <CallGraphView
                callGraph={call_graph}
                nodes={nodes}
                suggestedOrder={suggested_order}
                branchFilter={flowBranch}
                classifications={flowClassifications}
                currentInstructions={currentInstructions}
                onClassify={(ref, role, calledRefs, extra = {}) => {
                  setFlowClassifications(prev => {
                    const next = { ...prev }
                    if (role === null) {
                      // Clear this node
                      delete next[ref]
                    } else {
                      next[ref] = { ...(prev[ref] || {}), role, ...extra }
                      // When marking CT, auto-set all called refs to inline (if not already set)
                      if (role === 'case_type') {
                        calledRefs.forEach(r => {
                          if (!next[r]?.role) next[r] = { role: 'inline' }
                        })
                      }
                    }
                    return next
                  })
                }}
                onApply={instructions => {
                  const existing = (currentInstructions || '').trim()
                  onApplyInstructions(existing ? `${existing}\n${instructions}` : instructions)
                  setFlowClassifications({})
                }}
                onClear={() => setFlowClassifications({})}
              />
            </div>
          )}

          {activeTab === 'wizard' && (
            <div className="wizard-tab">
              {renderWizard()}
            </div>
          )}

          {subprocessCount > 0 && activeTab !== 'wizard' && (
            <div className="refmap-footer">
              <button
                className="refmap-apply-btn"
                onClick={handleApply}
                disabled={!instructions}
              >
                Apply to Process Instructions
              </button>
              {applied
                ? <span className="refmap-applied-msg">✓ Applied</span>
                : <span className="refmap-apply-hint">
                    {subprocessCount} subprocess{subprocessCount > 1 ? 'es' : ''} — default is inline
                  </span>
              }
            </div>
          )}
        </>
      )}
    </section>
  )
}
