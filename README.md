# ERP Assistant

A WhatsApp-based workforce management chatbot for the Hong Kong construction and field services industry. Workers and managers interact entirely through WhatsApp — no app to install, no portal to log into.

---

## Overview

ERP Assistant connects a Twilio WhatsApp webhook to a LangGraph-powered AI pipeline backed by MongoDB, Redis, and Temporal.io. A message arrives, the system classifies intent, extracts entities, runs business logic, and replies — all in the worker's preferred language (English or Traditional Chinese).

**Supported roles:** Worker · Manager · Admin

**Core flows:**

| Flow | Description |
|---|---|
| Worker registration | Upload ID card image → OCR extracts details → account created |
| GPS check-in / check-out | Worker shares location → system validates against project geofence → attendance logged |
| Image check-in | Worker sends photo → image stored → attendance record created |
| Leave application | Natural-language request ("take sick leave next Monday morning") → parsed → submitted |
| Medical certificate upload | Attach MC image to an existing sick leave application |
| Payslip generation | Manager requests monthly payslip → Excel report generated and sent |
| Project management | Create / update / delete projects with GPS coordinates |
| Attendance reports | Query today's situation or full attendance records as PDF |
| Worker card batch upload | Send multiple ID/work-permit images → all processed in one flow |
| Lunch overtime | Log overtime hours via chat |

---

## Architecture

```
WhatsApp (Twilio)
       │  webhook POST
       ▼
 ┌─────────────┐
 │  FastAPI app │  ← main.py
 └──────┬──────┘
        │
        ▼
 ┌─────────────────────────────────────────────┐
 │              LangGraph Pipeline              │
 │                                             │
 │  image_collect → intent_classify            │
 │      → entity_extract → validate            │
 │      → db_execute → respond → cleanup       │
 └──────┬──────────────────────────┬───────────┘
        │                          │
        ▼                          ▼
  ┌──────────┐              ┌──────────────┐
  │ MongoDB  │              │    Redis      │
  │(Beanie)  │              │(conversation  │
  │          │              │  state +      │
  │ Users    │              │  image buffer)│
  │ Projects │              └──────────────┘
  │ Attendance│
  │ Leave    │
  └──────────┘

 ┌──────────────────────────────┐
 │      Temporal.io Workers     │
 │                              │
 │  • Attendance workflows      │
 │  • Image-processing workflows│
 │  • Scheduled reminders       │
 │  • Monthly report generation │
 └──────────────────────────────┘

 ┌──────────────────────────────┐
 │       External Services      │
 │                              │
 │  OpenRouter  — LLM inference │
 │  Google DocumentAI — OCR     │
 │  Google Maps — GPS validation│
 └──────────────────────────────┘
```

---

## Tech Stack

**Backend**
- [FastAPI](https://fastapi.tiangolo.com/) — async REST API and Twilio webhook handler
- [LangGraph](https://github.com/langchain-ai/langgraph) — stateful multi-step AI workflow
- [Temporal.io](https://temporal.io/) — durable background workflows (reminders, scheduled reports)

**AI / NLP**
- [LangChain](https://python.langchain.com/) + OpenRouter — LLM intent classification and entity extraction
- [Google Cloud DocumentAI](https://cloud.google.com/document-ai) — OCR for ID cards, work permits, banking cards
- Custom temporal-word parser — handles mixed English/Chinese date expressions ("下星期一", "next Monday morning")

**Data**
- [MongoDB](https://www.mongodb.com/) + [Beanie](https://beanie-odm.dev/) — primary datastore (users, projects, attendance, leave)
- [Redis](https://redis.io/) — conversation state and multi-image collection buffer

**Messaging**
- [Twilio](https://www.twilio.com/whatsapp) — WhatsApp Business API (inbound webhooks + outbound messages)

**Document generation**
- ReportLab / FPDF — attendance record PDFs
- XlsxWriter / openpyxl — payslip Excel files
- python-docx / docxtpl — employee contracts

**Infrastructure**
- Docker + docker-compose — full local and production stack
- Nginx — reverse proxy + TLS termination
- Ansible — remote deployment playbooks
- Gunicorn + Uvicorn — production ASGI server

---

## Project Structure

```
erp-assistant/
├── main.py                          # FastAPI app, Twilio webhook, startup lifecycle
├── src/
│   ├── chatbot_service/
│   │   ├── langgraph/               # 6-node LangGraph pipeline (agent.py, nodes/)
│   │   ├── llm_prompts/             # System prompts per intent and role
│   │   ├── llm_executions/          # Response handlers for each intent
│   │   └── chatbot_helpers/         # Intent registry, conversation state manager
│   ├── models/                      # Beanie ODM models (user, project, attendance, leave…)
│   ├── models_business_logic/       # Domain logic separate from data models
│   ├── routes/                      # REST API route handlers (12 modules)
│   ├── nlp_helpers/                 # Temporal-word extraction (English + Traditional Chinese)
│   ├── tools/                       # OCR tools (ID card, work permit, banking card)
│   ├── pdf_templates/               # PDF and Excel report generators
│   ├── message_templates/           # WhatsApp reply message builders
│   └── utils/                       # Timezone helpers, HK holidays, language detection
├── temporal_app/
│   ├── workflows/                   # Durable workflow definitions
│   ├── activities/                  # Individual task implementations
│   ├── schedules/                   # Cron-based scheduled tasks
│   └── worker.py                    # Temporal worker registration
├── infrastructure/
│   ├── database/                    # MongoDB connection and config
│   └── redis_connection/            # Redis client and state manager
└── deployment/
    ├── docker-compose.yml           # Full stack: app, worker, Temporal, MongoDB, Redis, Nginx
    ├── Dockerfile / Dockerfile.temporal
    ├── nginx.conf
    └── deploy.yml                   # Ansible playbook for remote deployment
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- [Poetry](https://python.python-poetry.org/docs/)
- Docker and docker-compose
- A [Twilio](https://www.twilio.com/) account with WhatsApp sandbox or Business API enabled
- A [MongoDB Atlas](https://www.mongodb.com/atlas) cluster (or local MongoDB)
- An [OpenRouter](https://openrouter.ai/) API key
- Google Cloud project with Document AI processors enabled (for OCR features)

### Installation

```bash
git clone https://github.com/your-org/erp-assistant.git
cd erp-assistant

# Install dependencies
poetry install

# Copy and fill in environment variables
cp .env.example .env
```

### Configuration

Edit `.env` with your credentials. See [`.env.example`](.env.example) for all required variables, grouped by service.

### Run locally (Docker)

```bash
cd deployment
docker-compose up --build
```

This starts: FastAPI app · Temporal server + worker · MongoDB · Redis · Nginx

The API will be available at `http://localhost:8080`. Interactive API docs are at `http://localhost:8080/docs`.

### Run locally (without Docker)

```bash
# Start the FastAPI app
poetry run uvicorn main:app --reload --port 8000

# In a separate terminal, start the Temporal worker
poetry run python temporal_app/worker.py
```

Point your Twilio WhatsApp webhook at your server's `/webhook` endpoint (use [ngrok](https://ngrok.com/) for local development).

---

## API Documentation

FastAPI auto-generates OpenAPI docs at `/docs` (Swagger UI) and `/redoc` (ReDoc) when the server is running.

Key endpoint groups:

| Prefix | Description |
|---|---|
| `POST /webhook` | Twilio WhatsApp inbound message handler |
| `/users` | User registration and profile management |
| `/workers` | Worker-specific operations |
| `/projects` | Project CRUD and GPS management |
| `/attendance/gps` | GPS-based attendance records |
| `/attendance/image` | Image-based attendance records |
| `/leave` | Leave applications and approvals |
| `/shift-config` | Shift schedule configuration |
| `/payslip` | Monthly payslip generation |
| `/contracts` | Employee contract generation |

---

## Environment Variables

| Variable | Description |
|---|---|
| `ACCOUNT_SID` | Twilio account SID |
| `AUTH_TOKEN` | Twilio auth token |
| `WHATSAPP_NUMBER` | Twilio WhatsApp sender number |
| `OPENROUTER_API_KEY` | LLM inference API key |
| `DATABASE_URL` | MongoDB connection string |
| `SECRET_KEY` | JWT signing secret |
| `BASE_URL` | Public-facing base URL (used in GPS check-in links) |
| `REDIS_HOST / REDIS_PORT` | Redis connection |
| `TEMPORAL_NAMESPACE` | Temporal namespace (default: `default`) |
| `TEMPORAL_TASK_QUEUE_NAME` | Temporal task queue name |
| `*_DOCUMENTAI_CREDENTIALS` | Paths to Google Cloud service account JSON files |

See `.env.example` for the full list.

---

## Authors

Jing Wang — [jingwang.official@gmail.com](mailto:jingwang.official@gmail.com)
