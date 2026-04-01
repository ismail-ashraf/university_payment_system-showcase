# University Payment System

A production-minded university payment system built with **Django** and **Django REST Framework**, designed to support a complete payment workflow for both **students** and **administrators**.

This project goes beyond a simple payment page and focuses on the workflow logic required to make student payments reliable, traceable, and operationally usable end to end.

---

## Overview

Many universities still rely on manual or unclear payment processes. This project was built to provide a more structured digital workflow where:

* students can verify identity and understand their payment state clearly
* payments follow controlled lifecycle rules
* admins can monitor transactions and operational status
* the system remains reliable under repeated requests, retries, and webhook events

The goal was to build a system that is not only functional at the UI level, but also dependable at the backend workflow level.

---

## Core Features

### Student-facing flow

* Student verification flow
* Payment eligibility checks
* Open payment tracking
* Current payment status visibility
* Next-step guidance through the payment flow
* Student payment history and detail endpoints

### Admin-facing operations

* Payment monitoring
* Recent transactions view
* Payment detail visibility
* Lifecycle-aware operational oversight
* Reporting-oriented admin endpoints
* Read-only audit visibility in admin surfaces

### Backend reliability features

* Payment lifecycle management
* Idempotency and duplicate prevention
* Verified webhook processing
* Audit logging for key payment events
* Role-aware access flows for students and admins
* Provider abstraction for multiple payment gateways
* Rate limiting and CSRF protection on sensitive flows
* Production-minded configuration and safety checks

### AI assistant support

* Session-authenticated AI assistant integration
* Read-only-by-default boundaries
* Redaction-aware context handling

---

## Tech Stack

### Backend

* Python
* Django
* Django REST Framework
* SQLite for local development
* PostgreSQL-ready patterns for stronger production workflows

### Frontend / client integration

* Frontend-ready REST APIs
* Student and admin flows designed to support a real UI

### Development / operations

* Git + GitHub
* Structured logging
* Environment-based settings
* Automated test coverage across critical flows

---

## Architecture

The backend follows a layered structure to keep business logic centralized and maintainable.

```text
views -> services -> gateways -> utils -> models
```

### Main design principles

* Keep business rules centralized in the service layer
* Separate provider-specific gateway logic from payment orchestration
* Preserve idempotency, auditability, and role boundaries
* Return structured service results instead of relying on normal-flow exceptions

### Core payment orchestration

Most payment business logic is centralized in:

```text
payments/services/payment_service.py
```

This service layer coordinates:

* payment initiation
* submission handling
* webhook processing
* lifecycle transitions
* duplicate protection
* audit log creation

---

## Supported Payment Providers

The system is designed to support multiple gateways through a provider abstraction layer.

Current providers in the project structure include:

* Fawry
* Vodafone
* Bank

This makes it easier to extend or harden provider integrations without rewriting core payment workflow logic.

---

## Payment Workflow

### Student flow

1. Student verifies identity
2. System checks whether a payment can be started
3. If eligible, the student starts a payment
4. The student can view current payment status and next action
5. The payment moves through lifecycle states until completion or terminal resolution

### Admin flow

1. Admin monitors payments and transaction activity
2. Admin reviews recent transactions and payment details
3. Admin uses status visibility and audit information for operational tracking

### Reliability considerations

The workflow is designed to behave correctly when:

* actions are repeated
* duplicate submissions occur
* webhooks are retried
* terminal states should not be reversed incorrectly
* local cancellation or expiry interacts with later provider success events

---

## Security and Reliability Highlights

This project puts strong emphasis on backend correctness and operational safety.

### Examples of reliability protections

* idempotent payment behavior
* duplicate webhook no-op handling
* terminal-state safety rules
* replay protection for webhooks
* row-locking for conflict-sensitive updates

### Examples of security protections

* CSRF enforcement on sensitive session flows
* signature verification for payment webhooks
* trusted-proxy-aware IP handling
* rate limiting on login and payment endpoints
* production startup checks for unsafe settings

### Audit integrity

Audit logging is treated as an immutable operational record:

* edits to existing audit rows are blocked
* deletion is blocked
* bulk mutation shortcuts are blocked

---

## Key API Areas

### Student APIs

Examples of supported student-facing API capabilities:

* verification status
* payment eligibility / status snapshot
* payment history
* payment detail view
* next-action guidance

### Admin APIs

Examples of supported admin-facing API capabilities:

* payments summary
* recent payments
* payment list and detail views
* audit-oriented visibility

### AI APIs

* session-authenticated chat endpoint
* read-only assistant behavior for safer system interaction

---

## Project Structure

```text
university_payment_system/
├── payments/
├── students/
├── auth_api/
├── ai_agent/
├── config/
├── frontend/
├── docs/
└── manage.py
```

> Exact structure may vary slightly depending on local setup and active work branches.

---

## Running Locally

### 1) Clone the repository

```bash
git clone <your-repository-url>
cd university_payment_system
```

### 2) Create and activate a virtual environment

```bash
python -m venv .venv
```

#### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
```

#### macOS / Linux

```bash
source .venv/bin/activate
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Configure environment variables

Create a `.env` file or configure environment variables for your local setup.

Typical values may include:

* `DEBUG`
* `SECRET_KEY`
* `ALLOWED_HOSTS`
* `REDIS_URL` (if used)
* payment gateway webhook secrets
* AI provider settings

### 5) Apply migrations

```bash
python manage.py migrate
```

### 6) Create a superuser

```bash
python manage.py createsuperuser
```

### 7) Run the development server

```bash
python manage.py runserver
```

---

## Running Tests

Example:

```bash
python manage.py test
```

Focused test runs can be executed for specific apps or modules, for example:

```bash
python manage.py test payments.tests
python manage.py test students.tests
python manage.py test ai_agent.tests
python manage.py test config.tests
```

For some local test environments, environment variables such as `DEBUG=1` and a non-default `SECRET_KEY` may be required.

---

## What This Project Demonstrates

This project was built to demonstrate more than UI development.

It highlights experience with:

* backend architecture design
* workflow-oriented system design
* transactional reliability concerns
* API design for real frontend usage
* payment lifecycle handling
* operational visibility and auditability
* security hardening practices

---

## Demo

This repository is accompanied by a demo showing the system working end to end across student and admin flows.

You can add here:

* LinkedIn post link
* demo video link
* screenshots / GIFs

---

## Future Improvements

Possible next steps include:

* stronger production gateway integrations
* expanded admin dashboard and reporting
* richer frontend UX polish
* broader deployment / infrastructure setup
* deeper AI assistant capabilities within defined safety boundaries

---

## Status

This project is currently in a strong end-to-end usable state for demonstration and iterative improvement, with a clear separation between implemented workflow logic and future production-hardening enhancements.

---

## Author

Built by **Ismail Ashraf**.

If you'd like, you can connect this section to:

* LinkedIn
* GitHub profile
* portfolio website

---

## License

You can add a license here if you plan to open-source the repository.

For example:

* MIT License
* Apache 2.0
* All Rights Reserved
