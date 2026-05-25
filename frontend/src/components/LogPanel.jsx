import { useEffect, useRef } from 'react'
import './LogPanel.css'

export default function LogPanel({ entries }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  return (
    <section className="panel log-panel">
      <h2>Pipeline Log</h2>
      <div className="log-body">
        {entries.length === 0 ? (
          <span className="log-empty">Waiting for analysis to start…</span>
        ) : (
          entries.map((e, i) => (
            <div key={i} className={`log-line ${e.type || ''}`}>
              <span className="log-ts">[{e.ts}]</span>
              <span className="log-text">{e.text}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}
