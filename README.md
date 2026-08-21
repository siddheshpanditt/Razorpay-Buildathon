# AI Revenue Recovery

An agent that detects revenue at risk, diagnoses root cause, selects an intervention, executes a bounded recovery workflow, and produces a full audit trail.

Built for the Razorpay AI Buildathon.

## Scope (v1)

| Leak type | Detector | Root causes | Interventions |
|---|---|---|---|
| Payment failure | `detectors/payment_failure.py` | insufficient_funds, expired_card, issuer_decline, gateway_timeout, fraud_flagged, unknown | retry_now, retry_scheduled, request_payment_update, offer_alternate_method, escalate_human, suppress |
| Checkout abandonment | `detectors/checkout_abandonment.py` | price_hesitation, otp_friction, payment_method_missing, comparison_shopping, technical_error, unknown | reminder_nudge, discount_offer, simplify_checkout_flag, escalate_human, suppress |

## Repo layout

```
ai-revenue-recovery/
  data/              # SQLite schema + synthetic event generators
  detectors/         # one file per leak type
  diagnosis/         # Claude API call with structured JSON output + rule-based mock mode
  interventions/     # intervention selection + message templates
  rules_engine/      # stopping rules, cool-downs, DNC, compliance — NO LLM dependency
  executor/          # bounded workflow runner + mocked channel stubs
  audit/             # audit log writer + query helpers
  dashboard/         # Streamlit batch results view
  tests/             # pytest — rules_engine tests are mandatory
  config.yaml        # all tuneable knobs (recovery rates, thresholds, contact window)
  run_batch.py       # CLI entry point
  .env.example
  requirements.txt
```

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo>
cd ai-revenue-recovery
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY (a real key — see note below on running without one)
```

### 4. Run the batch recovery agent

The database is created automatically on first run — no separate init step needed.

```bash
# Generate synthetic events and process them in one go
python run_batch.py --generate 40
```

Prints a summary table and writes every case + rule check to the audit log in SQLite.

### 5. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

## Running without an Anthropic API key

The diagnosis step normally calls Claude for root-cause classification. If you don't have a working API key (or hit a quota/auth error), pass `--mock-diagnosis` to use a deterministic, rule-based diagnosis instead — no network call, no key required:

```bash
python run_batch.py --generate 40 --mock-diagnosis
```

This maps each event's real fields (`gateway_response_code` for payment failures, `stage_reached` for checkout abandonment) to a plausible root cause and intervention from the same fixed enums the real Claude call uses, so the rest of the pipeline — rules engine, execution, audit trail, dashboard — runs identically either way. Swap back to real diagnosis at any time by dropping the flag once a valid key is set.

## CLI reference

```bash
python run_batch.py                        # process all unprocessed events
python run_batch.py --limit 20              # cap at 20 events this run
python run_batch.py --dry-run               # detect + diagnose only, no execution
python run_batch.py --generate 40           # seed 40 synthetic events of each type first
python run_batch.py --suppress id1,id2      # add case/event IDs to the suppress list
python run_batch.py --mock-diagnosis        # skip the Claude API, use rule-based mock diagnosis
```

Flags can be combined, e.g. `python run_batch.py --generate 40 --dry-run --mock-diagnosis`.

## Configuration

All tuneable knobs live in `config.yaml` — nothing is hardcoded elsewhere:

| Key | Default | Description |
|---|---|---|
| `MAX_ATTEMPTS_PER_CASE` | 3 | Hard cap on contact/retry attempts per case |
| `COOLDOWN_HOURS` | 4 | Minimum hours between attempts |
| `HIGH_VALUE_ESCALATION_THRESHOLD_INR` | 50000 | Auto-escalate if amount exceeds this |
| `CONTACT_WINDOW_START_HOUR` | 9 | IST hour (inclusive) |
| `CONTACT_WINDOW_END_HOUR` | 21 | IST hour (exclusive) |
| `CONTACT_WINDOW_DAYS` | Mon–Sat | 0=Mon, 6=Sun |
| `RECOVERY_RATES.*` | per intervention | Simulator probability; `escalate_human` and `suppress` are 0.0 |

## Stopping rules (plain code, no LLM)

Enforced in `rules_engine/` before every action:

1. `do_not_contact` flag — hard block, no override
2. `customer_contact_opt_in` — must be true
3. Max attempts per case
4. Cool-down between attempts
5. Contact window (IST 9 AM – 9 PM, Mon–Sat)
6. High-value auto-escalation
7. Suppress list (disputed / legal-hold cases)

Every rule check (pass or fail) is written to the audit log regardless of outcome. `run_rules()` always evaluates all 7 checks — it never short-circuits on the first failure — so the audit trail has a complete picture even for suppressed cases.

## Audit trail — how to read it

Every case leaves a distinguishable trail in the audit log:

| Signal | Where | Meaning |
|---|---|---|
| `stage=diagnosis, result=warn` | audit_log | LLM output was invalid and silently corrected to `unknown`/`suppress` |
| `stage=rule_check, result=fail, rule_name=<x>` | audit_log | A stopping rule blocked the case (e.g. `do_not_contact`, `max_attempts`) |
| `stage=rule_check, result=pass, rule_name=high_value_escalation` | audit_log | Escalation triggered — `detail` distinguishes rules-engine-forced vs LLM-flagged |

The dashboard's case drill-down shows the full trail for any `case_id`.

## Running tests

```bash
pytest tests/ -v
```

Rules engine tests (29 total) run with zero LLM or network dependency.

## Data flow

```
synthetic event
      │
  detector          ← validates schema, emits a Case
      │
  diagnosis          ← Claude API (structured JSON, fixed enums) OR --mock-diagnosis
      │
  rules_engine       ← plain-code gate; writes every check to audit log
      │
  executor            ← mocked channel stub (email/SMS/webhook)
      │
  audit log           ← full per-case trail in SQLite
      │
  reporter             ← summary table + dashboard
```

## Known limitations (v1)

- Recovery outcomes are simulated (`RECOVERY_RATES` in `config.yaml`), not connected to a real payment gateway or CRM.
- Only two leak types are implemented: payment failure and checkout abandonment. Failed-subscription dunning, B2B receivables, mandate retry, and promise-to-pay tracking are out of scope for v1.
- Channels (`executor/channels.py`) are stubs that print/log rather than actually sending email/SMS/webhooks.