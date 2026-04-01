# AI Agent — Integration Instructions

The `ai_agent` app is fully isolated. You need to make **two small additions**
to existing files (not modifications to business logic):

---

## 1. Add to `config/settings.py`

Add `"ai_agent"` to `INSTALLED_APPS` and configure the Groq key:

```python
INSTALLED_APPS = [
    # ... existing apps ...
    "ai_agent",          # ← add this line
]

# ── AI Agent (Financial Assistant) ───────────────────────────────────────────
GROQ_API_KEY         = config("GROQ_API_KEY", default="")
GROQ_MODEL           = config("GROQ_MODEL", default="llama3-8b-8192")
AGENT_API_BASE_URL   = config("AGENT_API_BASE_URL", default="http://localhost:8000")
AGENT_API_TIMEOUT    = config("AGENT_API_TIMEOUT", default=10, cast=int)
```

---

## 2. Add to `config/urls.py`

```python
urlpatterns = [
    # ... existing urls ...
    path("ai-agent/", include("ai_agent.urls")),   # ← add this line
]
```

---

## 3. Add to `.env`

```env
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama3-8b-8192
AGENT_API_BASE_URL=http://localhost:8000
```

Get your free API key at: https://console.groq.com

---

## 4. Install dependency

```bash
pip install groq
```

Or add to `requirements.txt`:

```
groq>=0.9.0
```

---

## 5. Run tests

```bash
python manage.py test ai_agent
```

---

## 6. Usage

```bash
# Start the server
python manage.py runserver

# Authenticate via session (login endpoint) first, then:
curl -c cookies.txt -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "student_user", "password": "testpass123"}'

curl -b cookies.txt -X POST http://localhost:8000/ai-agent/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "What is my current balance?"}'
```

Expected response:

```json
{
  "success": true,
  "response": "Your current balance is 1,200 EGP as of today.",
  "intent": "balance"
}
```

---

## Supported Queries

| Query Type      | Example                            |
| --------------- | ---------------------------------- |
| Balance         | "What is my balance?"              |
| Transactions    | "Show my last 5 payments"          |
| Fees            | "How much do I owe this semester?" |
| Failed payments | "Why did my last payment fail?"    |
| Out of scope    | Returns polite redirection message |

## Blocked Queries (Security)

Any message containing payment-execution keywords (`pay`, `transfer`, `initiate`, etc.) returns:

```json
{
  "success": false,
  "error": "This assistant cannot perform payments. Read-only access."
}
```
