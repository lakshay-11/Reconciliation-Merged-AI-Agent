Government AI Financial Intelligence Platform — Reconciliation (Merged) Module

Project Overview
This is the Reconciliation (Merged) AI Agent, Use Case 5 of the DOF RFP (AI Government Financial Intelligence).
Source: DOF - RFP AI Government Financial Intelligence.pdf

The full platform has 7 modules; this workspace implements only Reconciliation:
- Document Retrieval Assistant
- Settlement Workflow
- **

 (this module)**
- Budget Intelligence
- Revenue Assurance
- Tax Intelligence
- Treasury and Cash Management

RFP Functional Requirements (FR-05 to FR-09)
FR-05  Multi-Source Transaction Ingestion — banks, DOF systems, batch + incremental, structured + semi-structured
FR-06  Automated Matching Engine — rule-based + AI-assisted, 1:1/1:many/many:many, confidence scoring, invoice-milestone matching
FR-07  Exception Handling — unmatched/low-confidence queue, priority by value/risk, manual resolution workflow
FR-08  Agentic Task Automation — LLM tool-calling, auto follow-ups, suggested actions, data entry
FR-09  Audit & Performance Reporting — auto-reconciliation rate, time-to-close, immutable audit trail

KPI Targets (from RFP)
Auto-reconciled rate:  >=80% MVP  |  >=90-95% target  |  >=98% stretch
Matching accuracy:     >=95% MVP  |  >=98% target      |  >=99.5% stretch
Manual effort reduction: >=40%   |  >=60-70%           |  >=85%
Time-to-close:         -3 days   |  -5 to -7 days      |  -10 days
Batch SLA:             <=5-10 minutes per reconciliation run

Constraints
- On-premises (Dubai Pulse), UAE data residency mandatory
- DESC-compliant, bilingual (Arabic + English) UI mandatory
- Human-in-the-loop required for all critical decisions — no autonomous approvals
- Every AI output must include a SHAP-based human-readable explanation
- Immutable audit log, RBAC, encryption in transit and at rest

TECH STACK

Data layer
PostgreSQL + pandas, CSV/Excel/PDF ingestion

ML engines
Isolation Forest (anomaly), SHAP (explainability), AI fuzzy matching (sentence-transformers or similar)

Agent / orchestration
LLM tool-calling (Claude API), routes exceptions to engines and human reviewers

API layer
FastAPI, JWT auth, RBAC, audit logging on every action

Dashboard
Streamlit (PoC), React (production) — bilingual Arabic/English

Processing Pipeline
Source A (bank statement) + Source B (ledger/ERP)
  -> ingestion/  : validate, normalize, store
  -> matching/   : rule_matcher -> ai_matcher -> confidence score
  -> Auto-reconciled (high confidence) | Exception queue (low confidence / unmatched)
  -> agent/      : suggest actions, trigger follow-ups
  -> workflow/   : human approves or rejects
  -> audit/      : immutable log of every decision

Folder Structure (app/)
  config.py          — env vars, settings
  db.py              — PostgreSQL models and connection
  auth.py            — JWT, RBAC
  main.py            — FastAPI entry point, mounts all routers
  ingestion/         — FR-05: bank_reader, ledger_reader, validator, normalizer
  matching/          — FR-06: match_engine, rule_matcher, ai_matcher, confidence
  exceptions/        — FR-07: exception_queue, prioritizer, resolution
  agent/             — FR-08: agent, tools, prompts
  analytics/         — anomaly detection (Isolation Forest), explainability (SHAP)
  audit/             — FR-09: audit trail, KPI metrics
  workflow/          — approval workflow, notifications (human-in-the-loop)
  api/               — FastAPI routers: reconciliation, exceptions, reports, admin

