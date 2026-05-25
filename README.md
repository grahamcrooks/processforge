# bupa-blueprint-app

Automatically generate Blueprint-ready technical artefacts from Bupa Health Insurance process flow diagrams using the Claude API.

---

## What It Does

Upload one or more PNG process flow diagrams and the app will analyse them using Claude's vision capability and generate:

| Artefact | File | Description |
|---|---|---|
| BPMN process model | `.bpmn` | Import-ready for Blueprint |
| PostgreSQL DDL | `.sql` | Delta schema (gap analysis if Pega model provided) |
| OpenAPI spec | `.yaml` | Integration API definition |
| BPIN document *(optional)* | `.docx` | Stakeholder presentation Word doc |

---

## Inputs

| Input | Required | Description |
|---|---|---|
| PNG process flow diagrams | **Yes** | One or more diagrams to analyse |
| Pega data model export | No | `.xlsx` file — enables delta DDL generation |
| Branding config | No | Org name, primary colour, logo — applied to BPIN doc |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Frontend | React 18 + Vite |
| AI | Claude API (`claude-sonnet-4-6`) |
| Word generation | `python-docx` |
| Containerisation | Docker Compose |

---

## Project Structure

```
bupa-blueprint-app/
├── backend/
│   ├── api/
│   │   ├── models/        # Pydantic request/response schemas
│   │   └── routes/        # FastAPI route handlers
│   ├── services/          # Core logic
│   │   ├── claude_service.py     # PNG → structured data via Claude vision
│   │   ├── bpmn_generator.py     # Generates .bpmn XML
│   │   ├── ddl_generator.py      # Generates PostgreSQL DDL
│   │   ├── openapi_generator.py  # Generates OpenAPI YAML
│   │   └── docx_generator.py     # Generates BPIN .docx
│   ├── utils/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── UploadPanel.jsx    # Drag-and-drop PNG upload
│   │   │   ├── BrandingPanel.jsx  # Org name, colour, logo
│   │   │   ├── ProgressPanel.jsx  # Live step-by-step progress
│   │   │   └── DownloadPanel.jsx  # Per-file download buttons
│   │   └── App.jsx
│   └── Dockerfile
├── docs/
│   └── architecture.md
├── docker-compose.yml
├── .env                   # ANTHROPIC_API_KEY goes here
└── .gitignore
```

---

## Quick Start

### Prerequisites
- Docker Desktop
- An Anthropic API key

### 1. Add your API key

```bash
echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" >> .env
```

### 2. Start the app

```bash
docker compose up --build
```

### 3. Open the UI

```
http://localhost:5173
```

The backend API runs on `http://localhost:8000`.

---

## Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key (`sk-ant-...`) |

---

## Stages

- [x] Stage 1 — Project structure & README
- [x] Stage 2 — Backend foundation (FastAPI)
- [x] Stage 3 — Claude API integration
- [x] Stage 4 — File generators (BPMN, DDL, OpenAPI, BPIN)
- [x] Stage 5 — React frontend
- [x] Stage 6 — Docker Compose integration
