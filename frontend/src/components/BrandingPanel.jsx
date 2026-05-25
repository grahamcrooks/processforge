import { useRef, useState } from 'react'
import './BrandingPanel.css'

export default function BrandingPanel({ branding, setBranding, generateBpin, setGenerateBpin }) {
  const [expanded, setExpanded] = useState(false)
  const logoRef = useRef(null)

  const update = (key, value) => setBranding(prev => ({ ...prev, [key]: value }))

  const handleLogo = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      // Strip data URL prefix — we only want the base64 part
      const b64 = reader.result.split(',')[1]
      update('logo_base64', b64)
      update('logo_name', file.name)
    }
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  return (
    <section className="panel branding-panel">
      <h2>Options</h2>

      {/* BPIN toggle */}
      <label className="toggle-row">
        <div className="toggle-info">
          <span className="toggle-title">Generate Process Analysis Summary</span>
          <span className="toggle-sub">Stakeholder-ready .docx with cover page, process tables and next steps</span>
        </div>
        <div
          className={`toggle-switch${generateBpin ? ' on' : ''}`}
          onClick={() => setGenerateBpin(v => !v)}
          role="switch"
          aria-checked={generateBpin}
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && setGenerateBpin(v => !v)}
        >
          <div className="toggle-thumb" />
        </div>
      </label>

      {/* Branding accordion */}
      <button
        className="branding-toggle"
        onClick={() => setExpanded(v => !v)}
        aria-expanded={expanded}
      >
        <span>Branding</span>
        <span className="branding-caret">{expanded ? '▲' : '▼'}</span>
        <span className="branding-note">optional — applied to Process Analysis Summary</span>
      </button>

      {expanded && (
        <div className="branding-fields">
          <label className="field-row">
            <span className="field-label">Organisation name</span>
            <input
              type="text"
              className="field-input"
              placeholder="e.g. Bupa Australia"
              value={branding.org_name || ''}
              onChange={e => update('org_name', e.target.value)}
            />
          </label>

          <label className="field-row">
            <span className="field-label">Primary colour</span>
            <div className="colour-row">
              <input
                type="color"
                className="colour-picker"
                value={branding.primary_colour || '#0057B8'}
                onChange={e => update('primary_colour', e.target.value)}
              />
              <input
                type="text"
                className="field-input colour-hex"
                value={branding.primary_colour || '#0057B8'}
                onChange={e => update('primary_colour', e.target.value)}
                maxLength={7}
              />
            </div>
          </label>

          <div className="field-row">
            <span className="field-label">Logo</span>
            <div className="logo-row">
              {branding.logo_name && (
                <span className="logo-name">{branding.logo_name}</span>
              )}
              <button
                className="logo-btn"
                onClick={() => logoRef.current?.click()}
              >
                {branding.logo_base64 ? 'Change logo' : 'Upload logo'}
              </button>
              {branding.logo_base64 && (
                <button
                  className="logo-remove"
                  onClick={() => { update('logo_base64', null); update('logo_name', null) }}
                >Remove</button>
              )}
              <input
                ref={logoRef}
                type="file"
                accept="image/*"
                style={{ display: 'none' }}
                onChange={handleLogo}
              />
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
