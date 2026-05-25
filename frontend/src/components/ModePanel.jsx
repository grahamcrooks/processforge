import { useEffect, useState } from 'react'
import './ModePanel.css'

export default function ModePanel() {
  const [mode, setMode]       = useState(null)   // 'live' | 'mock'
  const [loading, setLoading] = useState(true)
  const [open, setOpen]       = useState(false)
  const [pin, setPin]         = useState('')
  const [error, setError]     = useState('')
  const [saving, setSaving]   = useState(false)

  useEffect(() => { fetchMode() }, [])

  async function fetchMode() {
    try {
      const res = await fetch('/api/mode')
      const data = await res.json()
      setMode(data.mode)
    } catch {
      setMode('unknown')
    } finally {
      setLoading(false)
    }
  }

  async function switchMode(newMode) {
    setError('')
    setSaving(true)
    try {
      const res = await fetch('/api/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: newMode, pin }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || 'Incorrect PIN')
        setSaving(false)
        return
      }
      setMode(data.mode)
      setOpen(false)
      setPin('')
    } catch {
      setError('Could not reach server')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return null

  const isLive = mode === 'live'

  return (
    <div className="mode-bar">
      <div className={`mode-indicator ${isLive ? 'live' : 'mock'}`}>
        <span className="mode-dot" />
        <span className="mode-label">
          {isLive ? 'Live mode — using real Claude API' : 'Mock mode — no API tokens used'}
        </span>
      </div>

      <button className="mode-toggle-btn" onClick={() => { setOpen(v => !v); setError(''); setPin('') }}>
        Switch to {isLive ? 'Mock' : 'Live'} ▾
      </button>

      {open && (
        <div className="mode-popover">
          <div className="mode-popover-title">
            Switch to <strong>{isLive ? 'Mock' : 'Live'}</strong> mode
          </div>
          <div className="mode-popover-desc">
            {isLive
              ? 'Mock mode returns sample data instantly — no API tokens consumed. Good for testing and demos.'
              : 'Live mode calls Claude for real analysis. Uses API tokens — please use responsibly.'}
          </div>
          <input
            className="mode-pin-input"
            type="password"
            placeholder="Enter PIN to confirm"
            value={pin}
            onChange={e => { setPin(e.target.value); setError('') }}
            onKeyDown={e => e.key === 'Enter' && switchMode(isLive ? 'mock' : 'live')}
            autoFocus
          />
          {error && <div className="mode-error">{error}</div>}
          <div className="mode-popover-actions">
            <button className="mode-cancel" onClick={() => { setOpen(false); setPin(''); setError('') }}>
              Cancel
            </button>
            <button
              className={`mode-confirm ${isLive ? 'to-mock' : 'to-live'}`}
              onClick={() => switchMode(isLive ? 'mock' : 'live')}
              disabled={saving || !pin}
            >
              {saving ? 'Switching…' : `Switch to ${isLive ? 'Mock' : 'Live'}`}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
