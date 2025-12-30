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
- **Payer Intelligence**: Learn payer-specific patterns to improve approval rates

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Input Layer    │     │  Processing      │     │  Output         │
├─────────────────┤     ├──────────────────┤     ├─────────────────┤
│ • Denial letter │────▶│ • Extract denial │────▶│ • Appeal letter │
│   (PDF/fax)     │     │   reason codes   │     │ • Supporting    │
│ • Patient chart │     │ • Match to payer │     │   doc checklist │
│   (FHIR/CCD)    │     │   requirements   │     │ • Submission    │
│ • CPT/ICD codes │     │ • Generate appeal│     │   ready package │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Tech Stack

- **Backend**: Python / FastAPI
- **Document Processing**: AWS Textract / Azure Document Intelligence
- **LLM**: Claude API for appeal generation
- **Database**: PostgreSQL
- **Queue**: Redis (for async processing)

## Project Structure

```
prior-auth-assistant/
├── src/
│   ├── api/            # FastAPI routes
│   ├── core/           # Business logic
│   ├── integrations/   # External services (OCR, LLM, FHIR)
│   └── templates/      # Appeal letter templates
├── tests/
├── docs/
└── README.md
```

## Getting Started

```bash
# Clone the repository
git clone https://github.com/Dnakitare/prior-auth-assistant.git
cd prior-auth-assistant

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env

# Run the development server
uvicorn src.api.main:app --reload
```

## Environment Variables

```
ANTHROPIC_API_KEY=       # Claude API key
AWS_ACCESS_KEY_ID=       # For Textract
AWS_SECRET_ACCESS_KEY=
DATABASE_URL=            # PostgreSQL connection string
REDIS_URL=               # Redis connection string
```

## Roadmap

### MVP (Phase 1)
- [ ] PDF upload and OCR extraction
- [ ] Basic denial reason code parsing
- [ ] Appeal letter generation for top 5 denial reasons
- [ ] Web UI for upload and review

### Phase 2
- [ ] Payer-specific templates
- [ ] FHIR integration for clinical data
- [ ] Denial pattern analytics
- [ ] Batch processing

### Phase 3
- [ ] Direct payer portal submission
- [ ] EHR integrations (Epic, Cerner)
- [ ] Success rate tracking and optimization

## License

MIT
