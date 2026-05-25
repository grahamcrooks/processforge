import { useState } from 'react'
import UploadPanel      from './components/UploadPanel.jsx'
import BrandingPanel    from './components/BrandingPanel.jsx'
import ExtractionPanel  from './components/ExtractionPanel.jsx'
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

  const [isGenerating, setIsGenerating]     = useState(false)
  const [isAssessing, setIsAssessing]       = useState(false)
  const [assessmentOnly, setAssessmentOnly] = useState(false)
  const [steps, setSteps]                   = useState([])
  const [log, setLog]                       = useState([])
  const [files, setFiles]                   = useState([])
  const [warnings, setWarnings]             = useState([])
  const [genError, setGenError]             = useState(null)
  const [confidenceScores, setConfidenceScores] = useState([])

  function addLog(text, type = '') {
    setLog(prev => [...prev, { ts: nowTs(), text, type }])
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
          const tiling = payload.tiling ? ` (${payload.tiling})` : ''
          addLog(`Processing ${payload.filename}${tiling}`, 'detail')
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

  function handleRestart() {
    setFiles([])
    setWarnings([])
    setGenError(null)
    setSteps([])
    setLog([])
    setConfidenceScores([])
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
            <div className="header-title">Process Forge — Policy</div>
            <div className="header-sub">AI-powered artefact generation for Policy Management processes</div>
          </div>
        </div>
      </header>

      <main className="app-main">

        <div className="left-col">
          <ModePanel />
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
          <ExtractionPanel
            confidenceScores={confidenceScores}
            isGenerating={isGenerating}
            isAssessing={isAssessing}
            assessmentOnly={assessmentOnly}
          />

          <div className="generate-row">
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
            {isDone ? (
              <button className="restart-btn" onClick={handleRestart}>
                ↺ Run Again
              </button>
            ) : diagrams.length === 0 ? (
              <span className="generate-hint">Upload at least one PNG diagram to begin</span>
            ) : null}
          </div>

          <ProgressPanel steps={steps} warnings={warnings} error={genError} />

          {(busy || log.length > 0) && <LogPanel entries={log} />}

          <DownloadPanel files={files} />
        </div>

      </main>

      <footer className="app-footer">
        Process Forge — Policy · powered by Claude claude-sonnet-4-6
      </footer>
    </div>
  )
}
