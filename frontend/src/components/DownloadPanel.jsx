import './DownloadPanel.css'

// Match by extension for BPMN since the filename is dynamic (bpmn_<process_name>.bpmn)
function getFileMeta(filename) {
  if (filename.endsWith('.bpmn')) return { icon: '🔄', label: 'BPMN Process Flows', desc: 'Available for import to Blueprint' }
  if (filename === 'schema.sql')  return { icon: '🗄️',  label: 'PostgreSQL DDL',  desc: 'Available for import to Blueprint' }
  if (filename === 'api-spec.yaml') return { icon: '📡', label: 'OpenAPI Spec',  desc: 'Available for import to Blueprint' }
  if (filename === 'process-analysis-summary.docx') return { icon: '📄', label: 'Process Analysis Summary', desc: 'Stakeholder Word doc' }
  if (filename === 'extraction-log.json') return { icon: '📋', label: 'Pipeline Log', desc: 'Confidence scores, tiling info & build stats (JSON)' }
  return { icon: '📁', label: filename, desc: '' }
}

function downloadFile(filename, base64Content, mediaType) {
  const bytes = atob(base64Content)
  const buffer = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i)
  const blob = new Blob([buffer], { type: mediaType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function DownloadCard({ file }) {
  const meta = getFileMeta(file.filename)

  return (
    <div className="download-card">
      <div className="card-icon">{meta.icon}</div>
      <div className="card-info">
        <div className="card-label">{meta.label}</div>
        <div className="card-filename">{file.filename}</div>
        <div className="card-desc">{meta.desc}</div>
      </div>
      <button
        className="download-btn"
        onClick={() => downloadFile(file.filename, file.content_base64, file.media_type)}
      >
        ↓ Download
      </button>
    </div>
  )
}

export default function DownloadPanel({ files }) {
  if (!files || files.length === 0) return null

  const downloadAll = () => files.forEach(f =>
    downloadFile(f.filename, f.content_base64, f.media_type)
  )

  return (
    <section className="panel download-panel">
      <div className="download-header">
        <h2>Generated Artefacts</h2>
        <button className="download-all-btn" onClick={downloadAll}>↓ Download all</button>
      </div>
      <div className="download-grid">
        {files.map(f => <DownloadCard key={f.filename} file={f} />)}
      </div>
    </section>
  )
}
