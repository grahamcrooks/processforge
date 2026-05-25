import { useEffect, useState } from 'react'
import './ExtractionResultsPanel.css'

// Confidence per diagram slot — slot 3 is the complex one
const CONF = { 1: 96, 2: 94, 3: 87, 4: 93 }
const getConf = (i) => CONF[i] || 93

const RESULTS = [
  {
    id: 'lanes',
    icon: '🏊',
    label: 'Swim Lanes Detected',
    score: 97,
    color: 'green',
    tags: ['Support Specialists', 'Digital Consultants', 'Retail Consultant', 'Partnership Solutions', 'Customer'],
  },
  {
    id: 'tasks',
    icon: '⬡',
    label: 'Tasks & Decision Gateways',
    score: 94,
    color: 'blue',
    tags: ['28 User Tasks', '14 Exclusive Gateways', '3 Parallel Gateways', '6 Staged SubProcesses'],
  },
  {
    id: 'systems',
    icon: '🔗',
    label: 'Systems & Integrations Identified',
    score: 88,
    color: 'amber',
    tags: ['Core Policy System', 'Claims Engine', 'Identity Platform', 'Contact Centre', 'Member Portal', 'Notification Service', 'Document Store', 'Rules Engine', 'Audit Log'],
    warning: '2 annotations partially obscured — confidence estimated',
  },
  {
    id: 'callacts',
    icon: '📋',
    label: 'Sub-Process Call Activities Found',
    score: 92,
    color: 'indigo',
    tags: ['Add Person to Policy', 'Rebate Registration', 'Loading Calculation', 'Manage Portability', 'Employee Premium', '+ 13 more'],
  },
]

function ConfCell({ idx, diagrams, visible }) {
  const conf = getConf(idx)
  const isAmber = conf < 90
  const name = diagrams[idx - 1]?.name
    ? diagrams[idx - 1].name.replace(/\.[^.]+$/, '').substring(0, 22)
    : `Diagram ${idx}`

  return (
    <div className={`er-icc er-icc-${isAmber ? 'amber' : 'green'}${visible ? ' show' : ''}`}>
      <div className="er-icc-score">{conf}%</div>
      <div className="er-icc-meta">
        <div className="er-icc-name" title={name}>{name}</div>
        <div className="er-icc-bar">
          <div
            className={`er-icc-fill er-icc-fill-${isAmber ? 'amber' : 'green'}`}
            style={{ width: visible ? `${conf}%` : '0%' }}
          />
        </div>
      </div>
      {isAmber && <span className="er-icc-warn" title="Annotations partially obscured">⚠️</span>}
    </div>
  )
}

function ResultRow({ result, visible }) {
  return (
    <div className={`er-row er-row-${result.color}${visible ? ' show' : ''}`}>
      <div className="er-row-icon">{result.icon}</div>
      <div className="er-row-body">
        <div className="er-row-label">{result.label}</div>
        <div className="er-row-tags">
          {result.tags.map(t => (
            <span key={t} className={`er-tag er-tag-${result.color}`}>{t}</span>
          ))}
        </div>
        {result.warning && (
          <div className="er-row-warning">⚠ {result.warning}</div>
        )}
      </div>
      <div className="er-row-score">
        <div className={`er-score er-score-${result.color}`}>{result.score}%</div>
        <div className="er-score-lbl">Confidence</div>
        <div className="er-score-bar">
          <div
            className={`er-score-fill er-score-fill-${result.color}`}
            style={{ width: visible ? `${result.score}%` : '0%' }}
          />
        </div>
      </div>
    </div>
  )
}

export default function ExtractionResultsPanel({ diagrams }) {
  const [visible, setVisible] = useState(false)

  // Animate in after mount
  useEffect(() => {
    const t = setTimeout(() => setVisible(true), 80)
    return () => clearTimeout(t)
  }, [])

  const overall = Math.round(
    diagrams.reduce((sum, _, i) => sum + getConf(i + 1), 0) / diagrams.length
  )
  const hasIssues = diagrams.some((_, i) => getConf(i + 1) < 90)

  return (
    <section className="panel er-panel">
      <div className="er-header">
        <h2>Extraction Results</h2>
        <div className={`er-overall${visible ? ' show' : ''}`}>
          <div className="er-overall-lbl">Overall Confidence</div>
          <div className={`er-overall-score ${hasIssues ? 'amber' : 'green'}`}>{overall}%</div>
          <div className={`er-overall-tag ${hasIssues ? 'amber' : 'green'}`}>
            {hasIssues ? '⚠ Review flagged diagram' : '✓ High Confidence'}
          </div>
        </div>
      </div>

      {/* Per-diagram confidence */}
      <div className="er-icc-section">
        <div className="er-icc-title">Per-Diagram Confidence Score</div>
        <div className="er-icc-grid">
          {diagrams.map((_, i) => (
            <ConfCell key={i} idx={i + 1} diagrams={diagrams} visible={visible} />
          ))}
        </div>
        {hasIssues && (
          <div className="er-icc-note">
            ⚠ Diagram 3 — 2 system annotations partially obscured. Confidence estimated at 87%. Review recommended before Blueprint import.
          </div>
        )}
      </div>

      {/* Extraction result rows */}
      <div className="er-rows">
        {RESULTS.map((r, i) => (
          <ResultRow key={r.id} result={r} visible={visible} />
        ))}
      </div>
    </section>
  )
}
