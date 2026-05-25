import { useState } from 'react'
import './ExtractionPanel.css'

const RUBRIC = [
  { range: '90–100', tier: 'high',   desc: 'Excellent across all factors — extraction will be highly accurate' },
  { range: '70–89',  tier: 'high',   desc: 'Good overall; 1–2 minor issues in isolated areas — minor gaps possible' },
  { range: '50–69',  tier: 'medium', desc: 'Multiple factors impaired — several steps/labels/flows uncertain — significant extraction gaps expected' },
  { range: '30–49',  tier: 'low',    desc: 'Most factors poor — majority of content uncertain — extraction will be largely guesswork' },
  { range: '0–29',   tier: 'low',    desc: 'Unable to reliably extract — labels, flow, or swimlanes are largely unreadable' },
]

function scoreColour(score) {
  if (score >= 80) return 'high'
  if (score >= 55) return 'medium'
  return 'low'
}

function scoreLabel(score) {
  if (score >= 80) return 'High confidence'
  if (score >= 55) return 'Medium confidence'
  return 'Low confidence'
}

function scoreBand(score) {
  if (score >= 90) return { range: '90–100', desc: 'Excellent across all factors — extraction will be highly accurate' }
  if (score >= 70) return { range: '70–89', desc: 'Good overall; 1–2 minor issues in isolated areas — minor gaps possible' }
  if (score >= 50) return { range: '50–69', desc: 'Multiple factors impaired — several steps/labels/flows uncertain — significant extraction gaps expected' }
  if (score >= 30) return { range: '30–49', desc: 'Most factors poor — majority of content uncertain — extraction will be largely guesswork' }
  return { range: '0–29', desc: 'Unable to reliably extract — labels, flow, or swimlanes are largely unreadable' }
}

function readabilityIcon(r) {
  if (r === 'high')   return '🟢'
  if (r === 'medium') return '🟡'
  return '🔴'
}

function ConfidenceCard({ c }) {
  const tier  = scoreColour(c.score)
  const band  = scoreBand(c.score)
  return (
    <div className={`conf-card conf-card--${tier}`}>
      <div className="conf-card-header">
        <span className="conf-filename">{c.filename}</span>
        <span className={`conf-badge conf-badge--${tier}`}>{c.score}%</span>
      </div>
      <div className="conf-label">{scoreLabel(c.score)}</div>

      <div className="conf-band">
        <span className="conf-band-range">Band {band.range}</span>
        <span className="conf-band-desc">{band.desc}</span>
      </div>

      {(c.steps_extracted + c.lanes_identified + c.gateways_found + c.decisions_extracted) > 0 ? (
        <div className="conf-stats">
          <div className="conf-stat"><span className="stat-val">{c.steps_extracted}</span><span className="stat-key">Steps</span></div>
          <div className="conf-stat"><span className="stat-val">{c.lanes_identified}</span><span className="stat-key">Lanes</span></div>
          <div className="conf-stat"><span className="stat-val">{c.gateways_found}</span><span className="stat-key">Gateways</span></div>
          <div className="conf-stat"><span className="stat-val">{c.decisions_extracted}</span><span className="stat-key">Decisions</span></div>
        </div>
      ) : (
        <div className="conf-stats-pending">Extraction stats available after Generate Artefacts</div>
      )}

      <div className="conf-readability">
        {readabilityIcon(c.readability)} Image readability: <strong>{c.readability}</strong>
      </div>

      {tier === 'low' && (
        <div className="conf-redo-warning">
          ⚠ This diagram scored below 55% — extraction accuracy will be limited.
          We recommend improving the source image (higher resolution, split into sections)
          before generating artefacts.
        </div>
      )}

      {c.notes && <p className="conf-notes">{c.notes}</p>}

      {c.unclear_elements && c.unclear_elements.length > 0 && (
        <div className="conf-unclear">
          <div className="conf-unclear-title">⚠ Unclear elements</div>
          {c.unclear_elements.map((el, i) => <div key={i} className="conf-unclear-item">· {el}</div>)}
        </div>
      )}

      {c.warnings && c.warnings.length > 0 && (
        <div className="conf-warnings">
          {c.warnings.map((w, i) => <div key={i} className="conf-warning-item">⚠ {w}</div>)}
        </div>
      )}
    </div>
  )
}

const FACTORS = [
  { num: 1, label: 'Image resolution & sharpness',   desc: 'Is the image clear enough to read small text and thin arrows?' },
  { num: 2, label: 'Step / task label legibility',    desc: 'Can every rectangle and rounded-rect label be read with certainty?' },
  { num: 3, label: 'Flow arrow clarity',              desc: 'Are all sequence arrows unambiguous in direction and destination?' },
  { num: 4, label: 'Swimlane structure',              desc: 'Are lane borders distinct and role labels fully readable?' },
  { num: 5, label: 'Gateway & decision legibility',   desc: 'Are diamond shapes and all their branch labels fully visible?' },
  { num: 6, label: 'Process completeness',            desc: 'Is the full process visible with no cut-off edges or missing sections?' },
  { num: 7, label: 'Structural density',              desc: 'Are shapes well-separated, or do overlaps and crowding obscure the flow?' },
]

function RubricTable() {
  return (
    <div className="rubric-section">
      <div className="rubric-subtitle">What is scored — 7 factors (averaged)</div>
      <table className="rubric-table rubric-table--factors">
        <tbody>
          {FACTORS.map(f => (
            <tr key={f.num}>
              <td className="factor-num">{f.num}</td>
              <td className="factor-label">{f.label}</td>
              <td className="factor-desc">{f.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="rubric-subtitle" style={{ marginTop: '12px' }}>Score bands</div>
      <table className="rubric-table">
        <thead>
          <tr>
            <th>Band</th>
            <th>What it means</th>
          </tr>
        </thead>
        <tbody>
          {RUBRIC.map(r => (
            <tr key={r.range}>
              <td><span className={`rubric-badge rubric-badge--${r.tier}`}>{r.range}</span></td>
              <td>{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AssessmentBanner({ scores }) {
  const lowScores  = scores.filter(c => c.score < 55)
  const anyLow     = lowScores.length > 0
  const allGood    = !anyLow && scores.every(c => c.score >= 75)
  const avg        = Math.round(scores.reduce((s, c) => s + c.score, 0) / scores.length)

  if (anyLow) {
    return (
      <div className="assess-banner assess-banner--warn">
        <span className="assess-banner-icon">⚠️</span>
        <div>
          <strong>{lowScores.length} diagram{lowScores.length > 1 ? 's' : ''} scored below 55%</strong> — extraction accuracy will be significantly limited.<br />
          <span style={{fontWeight: 400}}>
            Export at higher resolution (300 DPI+), or split the diagram into smaller sections
            and re-upload before generating artefacts.
          </span>
        </div>
      </div>
    )
  }

  if (allGood) {
    return (
      <div className="assess-banner assess-banner--good">
        <span className="assess-banner-icon">✅</span>
        <span>All diagrams look good — proceed to Generate Artefacts.</span>
      </div>
    )
  }

  // Amber — calibrate message to actual severity
  if (avg < 68) {
    return (
      <div className="assess-banner assess-banner--amber">
        <span className="assess-banner-icon">🔶</span>
        <div>
          <strong>Overall score of {avg}% indicates significant extraction gaps are likely.</strong><br />
          <span style={{fontWeight: 400}}>
            Review the unclear elements flagged below. Consider improving source images
            (higher resolution, split large diagrams) before generating artefacts.
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="assess-banner assess-banner--amber">
      <span className="assess-banner-icon">🔶</span>
      <span>Some diagrams have areas that may affect extraction accuracy — review the scores below before generating.</span>
    </div>
  )
}

export default function ExtractionPanel({ confidenceScores, isGenerating, isAssessing, assessmentOnly }) {
  const [showRubric, setShowRubric] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  const busy = isGenerating || isAssessing

  if (!busy && (!confidenceScores || confidenceScores.length === 0)) {
    return (
      <section className="panel extraction-panel extraction-panel--empty">
        <div className="extraction-header">
          <h2>Extraction Results</h2>
          <button className="rubric-toggle" onClick={() => setShowRubric(v => !v)}>
            {showRubric ? '✕ Hide criteria' : '? Scoring criteria'}
          </button>
        </div>
        {showRubric && <RubricTable />}
        <p className="empty-hint">Assess diagram quality or generate artefacts — results appear here.</p>
      </section>
    )
  }

  if (busy && (!confidenceScores || confidenceScores.length === 0)) {
    return (
      <section className="panel extraction-panel extraction-panel--loading">
        <h2>{isGenerating ? 'Analysing & Building Artefacts' : 'Extraction Results'}</h2>
        <div className="extraction-loading">
          <span className="extraction-spinner" />
          {isAssessing ? 'Assessing diagram quality…' : 'Extracting process data and generating artefacts…'}
        </div>
      </section>
    )
  }

  const avg = Math.round(confidenceScores.reduce((s, c) => s + c.score, 0) / confidenceScores.length)
  const avgTier = scoreColour(avg)

  return (
    <section className="panel extraction-panel">
      <div className="extraction-header">
        <h2>{isGenerating ? 'Analysing & Building Artefacts' : 'Extraction Results'}</h2>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {collapsed && (
            <span className="extraction-summary-chips">
              {confidenceScores.map((c, i) => (
                <span key={i} className={`conf-badge conf-badge--${scoreColour(c.score)}`} title={c.filename}>
                  {c.filename.replace(/\.[^.]+$/, '').slice(0, 20)}: {c.score}%
                </span>
              ))}
            </span>
          )}
          <div className={`overall-badge overall-badge--${avgTier}`}>
            Overall: {avg}%
          </div>
          {!collapsed && (
            <button className="rubric-toggle" onClick={() => setShowRubric(v => !v)}>
              {showRubric ? '✕ Hide criteria' : '? Scoring criteria'}
            </button>
          )}
          <button className="panel-collapse-btn" onClick={() => setCollapsed(v => !v)} title={collapsed ? 'Expand' : 'Collapse'}>
            {collapsed ? '▶' : '▼'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <>
          {showRubric && <RubricTable />}

          {assessmentOnly && !isAssessing && (
            <AssessmentBanner scores={confidenceScores} />
          )}

          <div className="conf-cards">
            {confidenceScores.map((c, i) => <ConfidenceCard key={i} c={c} />)}
          </div>

          {isAssessing && confidenceScores.length > 0 && (
            <div className="extraction-loading" style={{ marginTop: 12 }}>
              <span className="extraction-spinner" />
              Assessing next diagram…
            </div>
          )}
        </>
      )}
    </section>
  )
}
