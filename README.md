# Prior Authorization Assistant

AI-powered tool that automates healthcare prior authorization appeals and documentation.

## Problem

- Prior authorizations cost the US healthcare system ~$31B annually in administrative burden
- Average PA takes 45 minutes of staff time
- 35% initial denial rate, but many denials are overturned on appeal
- Appeals require compiling clinical documentation and writing medical necessity letters

## Solution

Upload a denial letter and patient information → get a draft appeal letter with supporting documentation checklist.

## Features

- **Denial Analysis**: OCR and extract denial reason codes from payer letters
- **Appeal Generation**: Create medical necessity appeal letters tailored to payer requirements
- **Documentation Checklist**: Identify required clinical evidence to support appeals
- **Payer Intelligence**: Payer-specific rules and requirements database
- **Modern Web UI**: React-based interface for easy document upload and preview

## Screenshots

### Upload Interface
Drag and drop denial letters or paste text directly:
- Supports PDF, PNG, JPEG, TIFF
- Optional patient context for personalized appeals
- Real-time processing feedback

### Appeal Preview
Review generated appeals with:
- Extracted denial information
- Confidence scoring
- Required documents checklist
- One-click copy/download

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Input Layer    │     │  Processing      │     │  Output         │
├─────────────────┤     ├──────────────────┤     ├─────────────────┤
│ • Denial letter │────▶│ • OCR extraction │────▶│ • Appeal letter │
│   (PDF/image)   │     │ • LLM parsing    │     │ • Required docs │
│ • Patient info  │     │ • Template match │     │ • Payer info    │
│ • Clinical notes│     │ • Appeal generate│     │ • Confidence    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Tech Stack

- **Backend**: Python / FastAPI
- **Frontend**: React / TypeScript / Tailwind CSS
- **Document Processing**: AWS Textract (with mock provider for development)
- **LLM**: Claude API for extraction and appeal generation
- **Database**: PostgreSQL (with SQLAlchemy async)
- **Cache/Queue**: Redis
- **Containerization**: Docker Compose

## Project Structure

```
prior-auth-assistant/
├── src/
│   ├── api/
│   │   ├── main.py              # FastAPI app
│   │   └── routes/
│   │       ├── appeals.py       # Appeal generation endpoints
│   │       ├── payers.py        # Payer info endpoints
│   │       └── health.py        # Health check
│   ├── core/
│   │   ├── config.py            # Settings
│   │   ├── models.py            # Pydantic models
│   │   ├── db_models.py         # SQLAlchemy models
│   │   ├── database.py          # DB connection
│   │   ├── repositories.py      # Data access
│   │   └── services.py          # Business logic
│   ├── integrations/
│   │   ├── ocr.py               # AWS Textract / Mock
│   │   └── llm.py               # Claude API
│   └── templates/
│       └── appeal_templates.py  # Letter templates
├── frontend/
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── api.ts               # API client
│   │   └── types.ts             # TypeScript types
│   └── package.json
├── tests/
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/Dnakitare/prior-auth-assistant.git
cd prior-auth-assistant

# Set up environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Start all services
docker-compose up -d

# Access the app
# Frontend: http://localhost:3000
# API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

### Option 2: Local Development

```bash
# Clone the repository
git clone https://github.com/Dnakitare/prior-auth-assistant.git
cd prior-auth-assistant

# Backend setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Start backend
uvicorn src.api.main:app --reload

# Frontend setup (new terminal)
cd frontend
npm install
npm run dev

# Access the app
# Frontend: http://localhost:3000
# API: http://localhost:8000
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/v1/appeals/upload` | POST | Upload denial document |
| `/api/v1/appeals/text` | POST | Submit denial text |
| `/api/v1/appeals/{id}` | GET | Retrieve appeal |
| `/api/v1/payers` | GET | List payers |
| `/api/v1/payers/{name}/requirements` | GET | Payer requirements |

## Supported Denial Reasons

The system generates specialized appeal templates for:

- **Medical Necessity** - Lack of documented need
- **Step Therapy Required** - Must try alternatives first
- **Not Covered** - Benefit coverage disputes
- **Out of Network** - Network exception requests
- **Missing Information** - Documentation gaps
- **Experimental Treatment** - Coverage for new treatments
- **Quantity Limits** - Exceeds allowed quantities
- **Prior Auth Required** - Retroactive authorization

## Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=         # Claude API key

# Optional (AWS Textract - uses mock if not set)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1

# Database (Docker Compose sets these)
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/prior_auth
REDIS_URL=redis://localhost:6379/0

# Application
APP_ENV=development
DEBUG=true
LOG_LEVEL=INFO
```

## Roadmap

### Phase 1 (MVP) ✅
- [x] PDF upload and OCR extraction
- [x] Denial reason code parsing (8 types)
- [x] Appeal letter generation with templates
- [x] Web UI for upload and review
- [x] Payer database with requirements

### Phase 2 (In Progress)
- [ ] PostgreSQL persistence for appeals
- [ ] Appeal history and tracking
- [ ] Batch processing for multiple denials
- [ ] Analytics dashboard

### Phase 3 (Future)
- [ ] FHIR integration for clinical data
- [ ] Direct payer portal submission
- [ ] EHR integrations (Epic, Cerner)
- [ ] Success rate optimization with ML

## License

MIT
