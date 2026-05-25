import { useRef, useState } from 'react'
import './UploadPanel.css'

const MIN_WIDTH = 1500  // pixels — below this we flag the image

function readDimensions(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload  = () => { URL.revokeObjectURL(url); resolve({ width: img.naturalWidth, height: img.naturalHeight }) }
    img.onerror = () => { URL.revokeObjectURL(url); resolve(null) }
    img.src = url
  })
}

function ResolutionBadge({ dims }) {
  if (!dims) return null
  const low = dims.width < MIN_WIDTH
  return (
    <span className={`res-badge ${low ? 'res-badge--low' : 'res-badge--ok'}`} title={low ? 'Low resolution — may reduce extraction accuracy' : 'Resolution looks good'}>
      {dims.width}×{dims.height}{low ? ' ⚠' : ''}
    </span>
  )
}

function DiagramList({ files, dims, onRemove, onMoveUp, onMoveDown }) {
  if (files.length === 0) return null
  return (
    <div className="diagram-list">
      <div className="diagram-list-header">
        <span>Processing order — use arrows to reorder</span>
      </div>
      {files.map((f, i) => (
        <div key={f.name + f.size} className="diagram-row">
          <span className="diagram-seq">{i + 1}</span>
          <span className="diagram-name" title={f.name}>{f.name}</span>
          <ResolutionBadge dims={dims[f.name + f.size]} />
          <div className="diagram-actions">
            <button className="order-btn" disabled={i === 0} onClick={() => onMoveUp(i)} title="Move up">↑</button>
            <button className="order-btn" disabled={i === files.length - 1} onClick={() => onMoveDown(i)} title="Move down">↓</button>
            <button className="chip-remove" onClick={() => onRemove(f)} title="Remove">×</button>
          </div>
        </div>
      ))}
    </div>
  )
}

// Recursively read all files from a DataTransferEntry (handles folders)
async function readFilesFromEntry(entry) {
  if (entry.isFile) {
    return new Promise((resolve) => entry.file(resolve, () => resolve(null)))
  }
  if (entry.isDirectory) {
    const reader = entry.createReader()
    // readEntries only returns up to 100 at a time — loop until exhausted
    const allEntries = []
    const readBatch = () => new Promise((resolve) => reader.readEntries(resolve, () => resolve([])))
    let batch
    do {
      batch = await readBatch()
      allEntries.push(...batch)
    } while (batch.length > 0)
    const nested = await Promise.all(allEntries.map(readFilesFromEntry))
    return nested.flat().filter(Boolean)
  }
  return []
}

function DropZone({ label, accept, multiple, hasFiles, onFiles, hint, children }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  const handleDrop = async (e) => {
    e.preventDefault()
    setDragging(false)

    // Use items API so we can recurse into folders
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      const entries = [...e.dataTransfer.items]
        .map(item => item.webkitGetAsEntry?.())
        .filter(Boolean)

      const hasFolder = entries.some(entry => entry.isDirectory)
      if (hasFolder) {
        const files = (await Promise.all(entries.map(readFilesFromEntry))).flat().filter(Boolean)
        onFiles(files)
        return
      }
    }

    onFiles(Array.from(e.dataTransfer.files))
  }

  const handleInput = (e) => {
    onFiles(Array.from(e.target.files))
    e.target.value = ''
  }

  return (
    <div
      className={`drop-zone${dragging ? ' dragging' : ''}${hasFiles ? ' has-files' : ''}`}
      onClick={() => !hasFiles && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
    >
      <input ref={inputRef} type="file" accept={accept} multiple={multiple}
        style={{ display: 'none' }} onChange={handleInput} />

      {hasFiles ? children : (
        <>
          <div className="drop-icon">📂</div>
          <div className="drop-label">{label}</div>
          {hint && <div className="drop-hint">{hint}</div>}
        </>
      )}
    </div>
  )
}

export default function UploadPanel({ diagrams, setDiagrams, pegaModel, setPegaModel, instructions, setInstructions }) {
  const [dims, setDims] = useState({})   // keyed by file.name + file.size
  const [collapsed, setCollapsed] = useState(false)

  const addDiagrams = async (newFiles) => {
    const imgs = newFiles.filter(f =>
      f.type.startsWith('image/') ||
      /\.(png|jpg|jpeg|gif|webp)$/i.test(f.name)
    )
    // Read dimensions in parallel
    const entries = await Promise.all(
      imgs.map(async f => [f.name + f.size, await readDimensions(f)])
    )
    setDims(prev => ({ ...prev, ...Object.fromEntries(entries) }))
    setDiagrams(prev => {
      const names = new Set(prev.map(f => f.name))
      return [...prev, ...imgs.filter(f => !names.has(f.name))]
    })
  }

  const removeDiagram = (file) => setDiagrams(prev => prev.filter(f => f !== file))

  const moveUp = (i) => setDiagrams(prev => {
    const next = [...prev]
    ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
    return next
  })

  const moveDown = (i) => setDiagrams(prev => {
    const next = [...prev]
    ;[next[i], next[i + 1]] = [next[i + 1], next[i]]
    return next
  })

  const addPega = (files) => {
    const xlsx = files.find(f =>
      f.name.endsWith('.xlsx') || f.name.endsWith('.xls') ||
      f.type.includes('spreadsheet')
    )
    if (xlsx) setPegaModel(xlsx)
  }

  return (
    <section className="panel upload-panel">
      <div className="upload-panel-header">
        <div className="upload-panel-title">
          <h2>Images</h2>
          {diagrams.length > 0 && (
            <span className="upload-summary-chip">{diagrams.length} image{diagrams.length !== 1 ? 's' : ''}</span>
          )}
          {pegaModel && (
            <span className="upload-summary-chip upload-summary-chip--pega">Pega model</span>
          )}
          {instructions?.trim() && (
            <span className="upload-summary-chip upload-summary-chip--instr">Instructions</span>
          )}
        </div>
        <button className="panel-collapse-btn" onClick={() => setCollapsed(v => !v)} title={collapsed ? 'Expand' : 'Collapse'}>
          {collapsed ? '▶' : '▼'}
        </button>
      </div>

      {!collapsed && (
        <>
      <p className="panel-sub">
        Upload one or more process flow images. If your workflow spans multiple images,
        upload them all — they will be analysed as one sequential end-to-end process.
        Use the arrows to set the correct order.
      </p>

      <DropZone
        label="Drag & drop process flow diagrams here, or click to browse"
        accept="image/png,image/jpeg,image/gif,image/webp"
        multiple
        hasFiles={diagrams.length > 0}
        onFiles={addDiagrams}
        hint="Files or folders supported · order matters for multi-diagram workflows"
      >
        <DiagramList
          files={diagrams}
          dims={dims}
          onRemove={removeDiagram}
          onMoveUp={moveUp}
          onMoveDown={moveDown}
        />
        <div className="add-more-row">
          <button className="add-more" onClick={(e) => { e.stopPropagation() }}
            onClickCapture={(e) => { e.stopPropagation(); e.currentTarget.closest('.drop-zone').querySelector('input').click() }}>
            + Add more
          </button>
        </div>
      </DropZone>
      <p className="file-types-note">Supported formats: PNG · JPG / JPEG · GIF · WebP</p>

      <div className="optional-label">Optional — Pega data model export</div>
      <DropZone
        label="Drag & drop Pega .xlsx here for delta DDL generation"
        accept=".xlsx,.xls"
        multiple={false}
        hasFiles={!!pegaModel}
        onFiles={addPega}
        hint=".xlsx — enables delta mode: only new tables emitted"
      >
        <div className="chip-list" style={{padding: '12px'}}>
          <span className="file-chip">
            <span className="chip-name">{pegaModel?.name}</span>
            <span className="chip-size">({pegaModel ? (pegaModel.size/1024).toFixed(0) : 0} KB)</span>
            <button className="chip-remove" onClick={(e) => { e.stopPropagation(); setPegaModel(null) }}>×</button>
          </span>
        </div>
      </DropZone>

      <div className="optional-label" style={{marginTop: '8px'}}>Optional — Process instructions</div>
      <textarea
        className="instructions-input"
        placeholder="e.g. 6.2.3.1.1 is a child case; 6.2.3.1.2 and 6.2.3.1.3 are inline subprocesses of the parent case"
        value={instructions}
        onChange={e => setInstructions(e.target.value)}
        rows={3}
      />
      <p className="instructions-hint">
        Use this field to tell the model how to classify subprocesses — which reference numbers are
        child cases (<code>&lt;callActivity&gt;</code>) and which are inline (<code>&lt;subProcess&gt;</code>).
      </p>
        </>
      )}
    </section>
  )
}
