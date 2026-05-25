import './ProgressPanel.css'

const STATUS_ICON = {
  pending:    <span className="step-icon pending">○</span>,
  active:     <span className="step-icon active" aria-label="In progress">
                <span className="spinner" />
              </span>,
  done:       <span className="step-icon done">✓</span>,
  error:      <span className="step-icon error">✕</span>,
}

export default function ProgressPanel({ steps, warnings, error }) {
  if (!steps || steps.length === 0) return null

  return (
    <section className="panel progress-panel">
      <h2>Progress</h2>

      <ol className="step-list">
        {steps.map((step, i) => (
          <li key={i} className={`step-item ${step.status}`}>
            {STATUS_ICON[step.status] || STATUS_ICON.pending}
            <span className="step-label">{step.label}</span>
          </li>
        ))}
      </ol>

      {warnings && warnings.length > 0 && (
        <div className="warnings">
          <div className="warnings-title">⚠ Warnings</div>
          {warnings.map((w, i) => (
            <div key={i} className="warning-item">{w}</div>
          ))}
        </div>
      )}

      {error && (
        <div className="error-box">
          <strong>Error: </strong>{error}
        </div>
      )}
    </section>
  )
}
