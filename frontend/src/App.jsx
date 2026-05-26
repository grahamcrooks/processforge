import { useState } from 'react'
import UploadPanel      from './components/UploadPanel.jsx'
import BrandingPanel    from './components/BrandingPanel.jsx'
import ExtractionPanel  from './components/ExtractionPanel.jsx'
import RefMapPanel      from './components/RefMapPanel.jsx'
import ProcessMapPage   from './components/ProcessMapPage.jsx'
import ProgressPanel    from './components/ProgressPanel.jsx'
import LogPanel         from './components/LogPanel.jsx'
import DownloadPanel    from './components/DownloadPanel.jsx'
import ModePanel        from './components/ModePanel.jsx'
import './App.css'

const BASE_STEPS = [
  { label: 'Uploading files',               key: 'upload'  },
  { label: 'Analysing diagrams',            key: 'claude'  },
  { label: 'Generating BPMN process flows', key: 'bpmn'    },
  { label: 'Generating database schema',    key: 'ddl'     },
  { label: 'Generating OpenAPI spec',       key: 'openapi' },
]
const BPIN_STEP  = { label: 'Generating BPIN document', key: 'bpin' }
const FINAL_STEP = { label: 'Packaging artefacts',      key: 'done' }

function makeSteps(includeBpin) {
  const all = [...BASE_STEPS, ...(includeBpin ? [BPIN_STEP] : []), FINAL_STEP]
  return all.map(s => ({ ...s, status: 'pending' }))
}

function nowTs() {
  return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function App() {
  const [diagrams, setDiagrams]         = useState([])
  const [pegaModel, setPegaModel]       = useState(null)
  const [instructions, setInstructions] = useState('')
  const [generateBpin, setGenerateBpin] = useState(false)
  const [branding, setBranding]         = useState({
    org_name: '', primary_colour: '#0057B8', logo_base64: null, logo_name: null,
  })

  const [mode, setMode]                     = useState('score')
  const [isGenerating, setIsGenerating]     = useState(false)
  const [isAssessing, setIsAssessing]       = useState(false)
  const [assessmentOnly, setAssessmentOnly] = useState(false)
  const [steps, setSteps]                   = useState([])
  const [log, setLog]                       = useState([])
  const [files, setFiles]                   = useState([])
  const [warnings, setWarnings]             = useState([])
  const [genError, setGenError]             = useState(null)
  const [confidenceScores, setConfidenceScores] = useState([])
  const [refMapData, setRefMapData]         = useState(null)
  const [showProcessMap, setShowProcessMap] = useState(false)

  function addLog(text, type = '') {
    setLog(prev => [...prev, { ts: nowTs(), text, type }])
  }

  function formatTiling(t) {
    if (!t) return ''
    if (typeof t === 'string') return ` (${t})`
    const dims = t.width && t.height ? ` · ${t.width}×${t.height}px` : ''
    return t.tiled ? ` (${t.tile_count} tiles${dims})` : dims ? ` (${dims.slice(3)})` : ''
  }

  function markStep(key, allSteps) {
    setSteps(prev => {
      const idx = prev.findIndex(s => s.key === key)
      if (idx === -1) return prev
      return prev.map((s, i) => {
        if (i < idx)   return { ...s, status: 'done' }
        if (i === idx) return { ...s, status: 'active' }
        return s
      })
    })
    const label = allSteps.find(s => s.key === key)?.label
    if (label) addLog(label, 'step')
  }

  function updateConfidence(c) {
    setConfidenceScores(prev => {
      const exists = prev.some(x => x.filename === c.filename)
      return exists
        ? prev.map(x => x.filename === c.filename ? c : x)
        : [...prev, c]
    })
  }

  async function readSseStream(res, onEvent) {
    const reader  = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer    = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        let payload
        try { payload = JSON.parse(line.slice(6)) } catch { continue }
        onEvent(payload)
      }
    }
  }

  const handleAssess = async () => {
    if (diagrams.length === 0) return
    setIsAssessing(true)
    setAssessmentOnly(true)
    setConfidenceScores([])
    setLog([])
    addLog('Starting quality assessment…', 'step')

    try {
      const formData = new FormData()
      diagrams.forEach(f => formData.append('diagrams', f))

      const res = await fetch('/api/assess', { method: 'POST', body: formData })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail?.detail || `Server error ${res.status}`)
      }

      await readSseStream(res, payload => {
        if (payload.type === 'confidence') {
          updateConfidence(payload.data)
          addLog(`${payload.data.filename} — ${payload.data.score}% confidence`, 'detail')
        } else if (payload.type === 'ref_map') {
          setRefMapData(payload.data)
          addLog('Reference map built ✓', 'success')
        } else if (payload.type === 'complete') {
          addLog('Assessment complete ✓', 'success')
        } else if (payload.type === 'error') {
          throw new Error(payload.message)
        }
      })
    } catch (err) {
      addLog(`Error: ${err.message}`, 'error')
    } finally {
      setIsAssessing(false)
    }
  }

  const handleGenerate = async () => {
    if (diagrams.length === 0) return
    // Capture cached scores before clearing state — passed to backend to skip re-assessment
    const cachedScores = assessmentOnly && confidenceScores.length > 0
      ? Object.fromEntries(confidenceScores.map(c => [c.filename, c]))
      : null

    setIsGenerating(true)
    setAssessmentOnly(false)
    setFiles([])
    setWarnings([])
    setGenError(null)
    setLog([])

    const initialSteps = makeSteps(generateBpin)
    setSteps(initialSteps)
    setSteps(prev => prev.map((s, i) => i === 0 ? { ...s, status: 'done' } : s))
    addLog('Files uploaded — starting pipeline', 'step')

    try {
      const formData = new FormData()
      diagrams.forEach(f => formData.append('diagrams', f))
      if (pegaModel) formData.append('pega_model', pegaModel)
      formData.append('generate_bpin_doc', generateBpin ? 'true' : 'false')
      if (instructions.trim()) formData.append('process_instructions', instructions.trim())
      if (cachedScores) formData.append('cached_confidence_json', JSON.stringify(cachedScores))

      const b = branding
      if (b.org_name || b.primary_colour !== '#0057B8' || b.logo_base64) {
        formData.append('branding_json', JSON.stringify({
          org_name:       b.org_name || null,
          primary_colour: b.primary_colour || null,
          logo_base64:    b.logo_base64 || null,
        }))
      }

      const res = await fetch('/api/generate', { method: 'POST', body: formData })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail?.detail || `Server error ${res.status}`)
      }

      let completed = false

      await readSseStream(res, payload => {
        if (payload.type === 'step') {
          markStep(payload.key, initialSteps)
        } else if (payload.type === 'image_start') {
          addLog(`Processing ${payload.filename}${formatTiling(payload.tiling)}`, 'detail')
        } else if (payload.type === 'confidence') {
          updateConfidence(payload.data)
          addLog(`  ↳ ${payload.data.filename} — ${payload.data.score}% confidence`, 'detail')
        } else if (payload.type === 'detail') {
          addLog(payload.message, 'detail')
        } else if (payload.type === 'complete') {
          completed = true
          setSteps(prev => prev.map(s => ({ ...s, status: 'done' })))
          addLog('Pipeline complete ✓', 'success')
          setFiles(payload.data.files || [])
          setWarnings(payload.data.warnings || [])
          setIsGenerating(false)
        } else if (payload.type === 'error') {
          throw new Error(payload.message)
        }
      })

      if (!completed) throw new Error('Stream ended without completing — check the backend.')

    } catch (err) {
      setGenError(err.message || 'Unexpected error — check the backend.')
      setSteps(prev => prev.map(s => s.status === 'active' ? { ...s, status: 'error' } : s))
      addLog(`Error: ${err.message}`, 'error')
      setIsGenerating(false)
    }
  }

  function handleApplyOrder(orderedFilenames) {
    setDiagrams(prev => {
      const byName = Object.fromEntries(prev.map(f => [f.name, f]))
      const reordered = orderedFilenames.filter(fn => byName[fn]).map(fn => byName[fn])
      const remaining = prev.filter(f => !orderedFilenames.includes(f.name))
      return [...reordered, ...remaining]
    })
  }

  const BPMN_STEPS = [
    { label: 'Uploading files',               key: 'upload'  },
    { label: 'Analysing diagrams',            key: 'claude'  },
    { label: 'Generating BPMN process flows', key: 'bpmn'    },
    { label: 'Generating database schema',    key: 'ddl'     },
    { label: 'Generating OpenAPI spec',       key: 'openapi' },
    { label: 'Packaging artefacts',           key: 'done'    },
  ]

  const handleGenerateBpmn = async () => {
    if (diagrams.length === 0) return
    setIsGenerating(true)
    setAssessmentOnly(false)
    setFiles([])
    setWarnings([])
    setGenError(null)
    setLog([])

    const initialSteps = BPMN_STEPS.map(s => ({ ...s, status: 'pending' }))
    setSteps(initialSteps)
    setSteps(prev => prev.map((s, i) => i === 0 ? { ...s, status: 'done' } : s))
    addLog('Files uploaded — starting BPMN pipeline', 'step')

    try {
      const formData = new FormData()
      diagrams.forEach(f => formData.append('diagrams', f))
      if (instructions.trim()) formData.append('process_instructions', instructions.trim())

      const res = await fetch('/api/generate-bpmn', { method: 'POST', body: formData })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail?.detail || `Server error ${res.status}`)
      }

      let completed = false
      await readSseStream(res, payload => {
        if (payload.type === 'step') {
          markStep(payload.key, BPMN_STEPS)
        } else if (payload.type === 'image_start') {
          addLog(`Processing ${payload.filename}${formatTiling(payload.tiling)}`, 'detail')
        } else if (payload.type === 'confidence') {
          updateConfidence(payload.data)
          addLog(`  ↳ ${payload.data.filename} — ${payload.data.score}% confidence`, 'detail')
        } else if (payload.type === 'detail') {
          addLog(payload.message, 'detail')
        } else if (payload.type === 'complete') {
          completed = true
          setSteps(prev => prev.map(s => ({ ...s, status: 'done' })))
          addLog('BPMN generation complete ✓', 'success')
          setFiles(payload.data.files || [])
          setWarnings(payload.data.warnings || [])
          setIsGenerating(false)
        } else if (payload.type === 'error') {
          throw new Error(payload.message)
        }
      })

      if (!completed) throw new Error('Stream ended without completing — check the backend.')
    } catch (err) {
      setGenError(err.message || 'Unexpected error — check the backend.')
      setSteps(prev => prev.map(s => s.status === 'active' ? { ...s, status: 'error' } : s))
      addLog(`Error: ${err.message}`, 'error')
      setIsGenerating(false)
    }
  }

  function handleRestart() {
    setFiles([])
    setWarnings([])
    setGenError(null)
    setSteps([])
    setLog([])
    setConfidenceScores([])
    setRefMapData(null)
    setAssessmentOnly(false)
  }

  const busy        = isGenerating || isAssessing
  const canAssess   = diagrams.length > 0 && !busy
  const canGenerate = diagrams.length > 0 && !busy
  const isDone      = files.length > 0 && !busy

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="header-logo">⚙️</div>
          <div>
            <div className="header-title">Process Forge</div>
            <div className="header-sub">AI-powered artefact generation from process diagrams</div>
          </div>
        </div>
        {diagrams.length > 0 && (
          <button className="process-map-btn" onClick={() => setShowProcessMap(true)}>
            🗺 Process Map
          </button>
        )}
      </header>

      <main className="app-main">

        <div className="left-col">
          <ModePanel />
          <div className="action-card">
            <div className="mode-tabs">
              <button
                className={`mode-tab${mode === 'score' ? ' active' : ''}`}
                onClick={() => setMode('score')}
              >Score &amp; Extract</button>
              <button
                className={`mode-tab${mode === 'bpmn' ? ' active' : ''}`}
                onClick={() => setMode('bpmn')}
              >BPMN Generation</button>
            </div>
            <div className="generate-row">
              {mode === 'score' ? (
                <>
                  <button
                    className="assess-btn"
                    disabled={!canAssess}
                    data-active={isAssessing || undefined}
                    onClick={handleAssess}
                  >
                    {isAssessing
                      ? <><span className="btn-spinner" /> Assessing…</>
                      : '🔍 Assess Quality'
                    }
                  </button>
                  <button
                    className="generate-btn"
                    disabled={!canGenerate}
                    data-active={isGenerating || undefined}
                    onClick={handleGenerate}
                  >
                    {isGenerating
                      ? <><span className="btn-spinner" /> Generating…</>
                      : '⚡ Generate Artefacts'
                    }
                  </button>
                </>
              ) : (
                <button
                  className="generate-btn"
                  disabled={!canGenerate}
                  data-active={isGenerating || undefined}
                  onClick={handleGenerateBpmn}
                  style={{ gridColumn: '1 / -1' }}
                >
                  {isGenerating
                    ? <><span className="btn-spinner" /> Generating…</>
                    : '⚡ Generate Artefacts'
                  }
                </button>
              )}
              {isDone ? (
                <button className="restart-btn" onClick={handleRestart}>
                  ↺ Run Again
                </button>
              ) : diagrams.length === 0 ? (
                <span className="generate-hint">Upload diagrams to begin</span>
              ) : null}
            </div>
          </div>
          <UploadPanel
            diagrams={diagrams}
            setDiagrams={setDiagrams}
            pegaModel={pegaModel}
            setPegaModel={setPegaModel}
            instructions={instructions}
            setInstructions={setInstructions}
          />
          <BrandingPanel
            branding={branding}
            setBranding={setBranding}
            generateBpin={generateBpin}
            setGenerateBpin={setGenerateBpin}
          />
        </div>

        <div className="right-col">
          {mode === 'score' && (
            <ExtractionPanel
              confidenceScores={confidenceScores}
              isGenerating={isGenerating}
              isAssessing={isAssessing}
              assessmentOnly={assessmentOnly}
            />
          )}

          <RefMapPanel
            refMapData={refMapData}
            onApplyInstructions={setInstructions}
            onApplyOrder={handleApplyOrder}
            currentOrder={diagrams.map(f => f.name)}
            currentInstructions={instructions}
          />

          <ProgressPanel steps={steps} warnings={warnings} error={genError} />

          {(busy || log.length > 0) && <LogPanel entries={log} />}

          <DownloadPanel files={files} />
        </div>

      </main>

      <footer className="app-footer">
        Process Forge · powered by Claude claude-sonnet-4-6
      </footer>

      {showProcessMap && (
        <ProcessMapPage
          diagrams={diagrams}
          refMapData={refMapData}
          onClose={() => setShowProcessMap(false)}
          onApplyInstructions={setInstructions}
          currentInstructions={instructions}
        />
      )}
    </div>
  )
}
