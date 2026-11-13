# Slack Approval Proxy (MVP)
## System Design, Collaboration Rules, and Deployment Guide

---

## 1. Project Overview

### 1.1 Background and Goals
In multi-system integrations, business systems (ERP, CRM, OA, and similar) often need a human approval step. A lightweight **Slack Approval Proxy** takes an approval request from an external system, posts it to a company Slack channel, and lets a manager decide by clicking **Approve** or **Reject** on the Slack card. The proxy then notifies the original system asynchronously through an outbound webhook.

This document is the behavior contract. Diagrams, tables, and endpoint sections describe the same rules.

### 1.2 Core Stack
* **Framework**: Python FastAPI, one Uvicorn worker
* **Persistence**: SQLite file `approvals.db`. Integration message trace is core infrastructure: a message exchange, an HTTP call log, and a business audit log, in three tables
* **Scheduler**: APScheduler, one scan per minute, started from the FastAPI lifespan
* **Slack**: Web API (`chat.postMessage`, `chat.update`, `conversations.history`) and Block Kit
* **Delivery**: one in-process async callback runner shared by the interactive handler and the scheduler
* **Security**: `X-API-Key` on inbound routes; HMAC-SHA256 on the raw Slack body

Run a single process. The per-id lock, the callback runner, and the scheduler live in that process. `--workers` greater than 1 is outside this contract.

### 1.3 Integration Control Tower

The running service is the first slice of an **Integration Control Tower**: a small enterprise integration gateway for API calls, message trace, approval workflow, and audit. The console brand is **Integration Hub**. The product line under it is **Enterprise Integration Gateway**.

The slice demonstrates system handoff, message exchange, human approval, failure retry, and a full chain for one business id. It is a boundary that can be started and shown. It does not replace an ESB, Kafka, or an iPaaS product.

Six responsibilities sit in this one process:

| Responsibility | In this MVP |
|---|---|
| Control tower | Read-only console in `static/`. Screens are `doc/integration_control_tower_frontend.md` |
| Gateway | `X-API-Key` on inbound approval and trace reads. Slack uses HMAC. Parameter checks are §5.9 |
| Integration core | Idempotency on `request_id`, and the four orchestrators |
| Message trace | `message_exchanges`, `http_call_logs`, `business_audit_logs` |
| Workflow | Approval status machine, deadline, callback retry |
| Adapters | `slack` posts and updates cards. The approval workflow does not call the Slack Web API itself. The callback POST is the webhook adapter toward the caller's `callback_url` |

ERP, MES, and any later caller are external systems. They enter through `POST /api/v1/approvals` and leave through `callback_url`. This MVP does not add a system registry, a rate limiter, a second adapter, or a separate outbox table. `callback_state` plus one `message_exchanges` row per delivery attempt is the outbox.

Names in a broader integration glossary map onto this contract as follows. The columns in §4 stay the stored names.

| Glossary | This contract |
|---|---|
| `business_id` | `request_id` |
| `interface_code` | `operation` |
| `business_status` | `business_outcome` |
| `INBOUND` / `OUTBOUND` | `inbound` / `outbound` |
| Exchange time | `sent_at` |
| Delivery attempt | `attempt`, and a separate `message_exchanges` row per send |

A retry does not overwrite the previous attempt. Each send inserts its own exchange row before the bytes go out. The response, the timeout, or the transport failure updates that same row. `response_body` stays null when no response arrived. `http_status` and `business_outcome` are both stored. HTTP 200 does not set business success by itself. Bodies stay the original text, which may be JSON or any other text the caller sent. `Content-Type` remains inside the masked headers. This MVP does not add a body-hash column.

Delivery order for implementation:

| Phase | Deliverable | Where it is specified |
|---|---|---|
| P1 | Schema and message-trace writes | §4.5, §5.10 |
| P2 | Inbound auth and validation already in §3 and §5.9 | System registry and rate limits are outside this contract |
| P3 | Slack adapter and the approval workflow | §5 |
| P4 | Callback attempts, timeout, scanner | §5.5, §5.6 |
| P5 | Control-tower screens | `doc/integration_control_tower_frontend.md` |
| P6 | Docker, Nginx, and a demo seed | Outside this contract |

---

## 2. Collaboration Diagram and Architecture

### 2.1 Architecture Topology

The proxy commits a `posting` row before it calls Slack. `pending` means the channel id and message `ts` are already stored.

```mermaid
sequenceDiagram
  participant Ext as External business system
  participant Proxy as FastAPI Approval Proxy
  participant DB as SQLite approvals.db
  participant Slack as Slack
  Ext->>Proxy: 1. POST /api/v1/approvals (X-API-Key)
  Proxy->>DB: 2. Insert status=posting
  Proxy->>Slack: 3. POST chat.postMessage
  Proxy->>DB: 4. Store ts, set status=pending
  Proxy-->>Ext: 5. 200 result=created
  Slack->>Proxy: 6. Click Approve / Reject, POST /api/v1/slack/interactive
  Proxy->>DB: 7. Conditional status update
  Proxy->>Slack: 8. chat.update (remove buttons)
  Proxy-->>Ext: 9. Callback runner (retry 2s / 5s / 10s)
```

A definite Slack `ok: false` sets the row to `failed` and step 5 becomes `502`. A timeout or a dropped connection leaves the row at `posting` and step 5 becomes `502` with an unknown-outcome message. The caller retries the same `POST`.

### 2.2 End-to-End Sequence

```mermaid
sequenceDiagram
  participant Ext as External System
  participant Proxy as FastAPI Proxy
  participant DB as SQLite DB
  participant Slack as Slack App / API
  participant Approver as Approver
  Ext->>Proxy: 1. Create Request
  Proxy->>DB: 2. Insert posting
  Proxy->>Slack: 3. Post Card
  Proxy->>DB: 4. Save ts, pending
  Proxy-->>Ext: 5. 200 created
  Slack->>Approver: 6. Render Card
  Approver->>Slack: 7. Click Button
  Slack->>Proxy: 8. Interactive callback
  Proxy->>DB: 9. UPDATE if still open
  Proxy->>Slack: 10. Replace card
  Proxy--)Ext: 11. Webhook (async)
  Proxy-->>Slack: 12. 200 empty
```

Step 11 starts after the winning update and does not delay step 10 or step 12. Only the database update that changed the row schedules a webhook.

---

## 3. Keys and Configuration

### 3.1 Environment Variables (`.env`)

```ini
# ==========================================
# 1. Slack API credentials
# ==========================================
# Bot User OAuth Token (xoxb-). Scopes: chat:write, channels:history, groups:history.
# The bot must be a member of SLACK_CHANNEL_ID.
SLACK_BOT_TOKEN="xoxb-your-slack-bot-token"

# Basic Information -> App Credentials -> Signing Secret
SLACK_SIGNING_SECRET="your-slack-signing-secret"

# Channel that receives cards (for example C01234567)
SLACK_CHANNEL_ID="C01234567"

# ==========================================
# 2. Inbound API security
# ==========================================
PROXY_API_KEY="erp-system-secret-key-123"

# ==========================================
# 3. Database and runtime
# ==========================================
DATABASE_URL="sqlite:///./approvals.db"
PORT=8000
```

Compare `X-API-Key` to `PROXY_API_KEY` with a constant-time compare. Missing or different values return `401` on `/api/v1/approvals` only. `/api/v1/slack/interactive` does not use the API key.

---

## 4. Database

### 4.1 Table `approval_requests`

```sql
CREATE TABLE IF NOT EXISTS approval_requests (
    request_id TEXT PRIMARY KEY,               -- Caller idempotency key
    correlation_id TEXT NOT NULL,             -- Stable chain id for every exchange of this request
    system_source TEXT NOT NULL,
    callback_url TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,                             -- JSON object string, or null
    status TEXT NOT NULL,                     -- posting, pending, approved, rejected, expired, failed
    slack_channel_id TEXT,
    slack_message_ts TEXT,                    -- ts of the one live card
    decided_by TEXT,                          -- Slack user id; set only for approved or rejected
    decided_at TEXT,                          -- UTC ISO 8601; set only for approved, rejected, expired
    expires_at TEXT NOT NULL,                 -- UTC ISO 8601
    created_at TEXT NOT NULL,                 -- UTC ISO 8601; reset when a failed row is re-driven
    callback_state TEXT,                      -- null, pending, delivered, exhausted
    callback_delivered_at TEXT,               -- UTC ISO 8601 of the first 2xx callback
    callback_error_log TEXT,                  -- last failure after a finished retry wave
    card_updated_at TEXT                      -- UTC ISO 8601 when the Slack message matched the row
);
```

All timestamps use a `Z` suffix. `decided_at` stays null for `posting`, `pending`, and `failed`.

### 4.2 Status

| Status | Meaning |
|---|---|
| `posting` | Row is committed. Slack has not confirmed a `ts`, or the confirmation is not stored yet. |
| `pending` | `slack_message_ts` is stored and that message is the live card. |
| `approved` | The winning click was Approve, and the click was inside the deadline. |
| `rejected` | The winning click was Reject, and the click was inside the deadline. |
| `expired` | The deadline passed with no decision. |
| `failed` | Slack returned `ok: false` for the post. That attempt has no card. `GET` shows `failed` until a later `POST` re-drives the same id. |

A re-drive replaces that row with a new `posting` attempt and keeps the same `correlation_id`. The service does not keep a second approval row. The Slack exchange that caused `failed` stays in `message_exchanges` until retention deletes it (§4.5, §5.10). After re-drive, `GET` shows the new attempt.

### 4.3 Callback and Card Columns

| Column | When it changes |
|---|---|
| `callback_state` | Null while `posting`, `pending`, or `failed`. Set to `pending` in the same update that enters `approved`, `rejected`, or `expired`. `delivered` after a callback 2xx. `exhausted` after four failed attempts. |
| `callback_delivered_at` | Set when a callback returns 2xx. Cleared when a new terminal update starts a new callback. |
| `callback_error_log` | Set when a four-attempt wave finishes without a 2xx. Cleared on delivery and on re-drive. This column is what callers read on the approval. Each attempt remains its own `message_exchanges` row (§5.10). |
| `card_updated_at` | Set when `chat.postMessage` or `chat.update` has made the visible message match the row. Cleared in the update that enters a terminal status, then set again after the matching `chat.update`. |

### 4.4 Transitions

The conditional update in §5.4 is the only way to leave `posting`, `pending`, or `failed` for a decision. A transition that changes zero rows leaves the stored decision as it is.

| From | Event | To |
|---|---|---|
| no row | `POST` create | `posting` |
| `posting` | Slack `ok: true`, `ts` stored, still inside the deadline | `pending` |
| `posting` | Slack `ok: true`, `ts` stored, already past due | `expired` |
| `posting` | Slack `ok: false` | `failed` |
| `posting` | Timeout, connection loss, HTTP 5xx, or process death before `ts` is stored | `posting` |
| `posting` | Reconcile finds the message, still inside the deadline | `pending` |
| `posting` | Reconcile finds the message, already past due | `expired` |
| `posting` | Reconcile does not find the message | `failed` |
| `failed` | `POST` re-drive begins | `posting` |
| `pending` | Winning Approve | `approved` |
| `pending` | Winning Reject | `rejected` |
| `pending` | Winning expiry, from a click or from the scanner | `expired` |
| `posting` or `failed` | Winning in-time click on a real card | `approved` or `rejected` |
| `posting` or `failed` | Winning late click | `expired` |
| `approved`, `rejected`, `expired` | Later `POST` or click | unchanged |

### 4.5 Integration message trace

Three tables. None of them replaces another. Re-drive does not delete them. `callback_error_log` remains the short field on the approval row.

`message_exchanges` is the paired request and response. One row is one exchange. `exchange_id` is unique. `correlation_id` is the chain, shared with `approval_requests.correlation_id` and with the business `request_id`.

```sql
CREATE TABLE IF NOT EXISTS message_exchanges (
    exchange_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    request_id TEXT,
    direction TEXT NOT NULL,                  -- inbound, outbound
    source_system TEXT NOT NULL,
    target_system TEXT NOT NULL,
    operation TEXT NOT NULL,
    http_method TEXT NOT NULL,
    url TEXT NOT NULL,                        -- method path or Slack method; no query string
    request_headers TEXT NOT NULL,            -- masked JSON object
    request_body TEXT,
    sent_at TEXT NOT NULL,
    exchange_status TEXT NOT NULL,            -- received, sent, completed, timeout, transport_failed
    http_status INTEGER,
    response_headers TEXT,                    -- masked JSON object; null until a response arrives
    response_body TEXT,                       -- null until a response arrives; never invented
    received_at TEXT,
    duration_ms INTEGER,
    business_outcome TEXT,                    -- succeeded, failed, unknown
    error_message TEXT,
    body_truncated INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_exchanges_request_id ON message_exchanges (request_id);
CREATE INDEX IF NOT EXISTS idx_message_exchanges_correlation_id ON message_exchanges (correlation_id);
```

`http_call_logs` records who called which interface, and when. It does not store bodies.

```sql
CREATE TABLE IF NOT EXISTS http_call_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id TEXT,
    correlation_id TEXT,
    request_id TEXT,
    direction TEXT NOT NULL,
    source_system TEXT NOT NULL,
    target_system TEXT NOT NULL,
    operation TEXT NOT NULL,
    http_method TEXT NOT NULL,
    url TEXT NOT NULL,
    http_status INTEGER,
    duration_ms INTEGER,
    error_message TEXT,
    called_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_http_call_logs_request_id ON http_call_logs (request_id);
CREATE INDEX IF NOT EXISTS idx_http_call_logs_called_at ON http_call_logs (called_at);
```

`business_audit_logs` records approval state changes only.

```sql
CREATE TABLE IF NOT EXISTS business_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,                      -- Slack user id, or system
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_business_audit_logs_request_id ON business_audit_logs (request_id);
```

---

## 5. Behavioral Rules

These rules override the diagrams when a diagram and a rule ever differ.

### 5.1 Duplicate `request_id`

Take the in-process lock for that `request_id` before reading the row for a `POST`. The lock is held through the Slack call and the following database write.

| Current row | What the `POST` does |
|---|---|
| Lock already held | `409` `A create for this ID is still in progress`. Retry the same `POST`. |
| `posting`, lock free | Reconcile (§5.3). A found card becomes `pending` or `expired` and returns `200` `result=created`. A confirmed miss becomes `failed` and continues as a re-drive in this same call. A history-API failure leaves `posting` and returns `502` unknown. |
| `pending` | `409` `An active approval request with this ID already exists`. No second card. |
| `failed` | Re-drive: write this request's payload, clear Slack, decision, callback, and card columns, set `posting`, then post one card. |
| `approved`, `rejected`, `expired` | `200` with `result` = `already_decided` and the `GET` body. The stored decision stays as it is. No new card. |
| no row | Create flow in §5.3. |

`409` bodies:

```json
{"error": "Conflict", "message": "An active approval request with this ID already exists", "request_id": "demo-req-001"}
```

```json
{"error": "Conflict", "message": "A create for this ID is still in progress", "request_id": "demo-req-001"}
```

A caller that received the in-progress `409` retries the same `POST`. It does not treat that response as an open approval. `GET` shows whether the row is still `posting`, has become `pending` or `failed`, or has already reached a terminal status.

### 5.2 Error Envelope

```json
{"error": "ErrorType", "message": "What went wrong"}
```

`409` also includes `request_id`.

| Situation | HTTP | Body |
|---|---|---|
| Missing or wrong `X-API-Key` | `401` | `{"error": "Unauthorized", "message": "Invalid or missing X-API-Key header"}` |
| Request JSON fails §5.9 | `422` | `{"error": "ValidationError", "message": "timeout_minutes: must be an integer from 1 to 10080"}` |
| Slack signature or timestamp fails §5.7 | `400` | `{"error": "InvalidSignature", "message": "Slack signature mismatch or expired timestamp"}` |
| Interactive body has no JSON `payload`, or a decision button has no `user.id` | `400` | `{"error": "InvalidPayload", "message": "Slack payload is missing or not JSON"}` |
| Slack `chat.postMessage` returns `ok: false` | `502` | `{"error": "SlackAPIError", "message": "Failed to post message to Slack: channel_not_found"}` |
| Slack post has no confirmed `ts` (timeout, connection loss, HTTP 5xx, or the `ts` write failed) | `502` | `{"error": "SlackAPIError", "message": "Slack outcome unknown; retry the same request_id"}` |
| `GET` id is absent, or the button `value` matches no row | `404` | `{"error": "NotFound", "message": "Approval request not found"}` |
| The message exchange cannot be recorded before the request is accepted or sent | `503` | `{"error": "MessageTraceError", "message": "Failed to record the exchange"}` |

The definite `502` message ends with Slack's `error` string. The unknown `502` always uses the sentence in the table. A click on a row that is already `approved`, `rejected`, or `expired` is not a `404`; §5.4 repairs the card and returns an empty `200`.

### 5.3 Create, Reconcile, and Re-drive

**Create**

1. Validate the body (§5.9) and the API key.
2. Under the per-id lock, apply §5.1.
3. Insert `status = 'posting'`, `expires_at = now + timeout_minutes`, `created_at = now`. A new row gets a new `correlation_id`. A re-drive keeps the existing one. Commit before calling Slack. Recording the outbound Slack exchange follows §5.10 before `chat.postMessage`.
4. Call `chat.postMessage` with the card in §5.8.
5. Classify the Slack result:
   * `ok: true` and a `ts`: store `slack_channel_id`, `slack_message_ts`, and `card_updated_at`, and set `pending`. Retry that write three times if the database errors. If the write still fails, leave `posting` and return the unknown `502`.
   * `ok: false`: set `failed`, leave `slack_message_ts` null, return the definite `502`.
   * No usable Slack body: leave `posting`, return the unknown `502`.
6. If the row is `pending` and `now > expires_at`, run the expiry update from §5.4 before responding. Replace the card with the expired text.
7. Return `200`:

```json
{
  "result": "created",
  "request_id": "demo-req-001",
  "correlation_id": "6f1c0c3e-7b2a-4e5d-9a11-2c8e5b7d4a10",
  "status": "pending",
  "expires_at": "2026-11-11T17:00:00Z"
}
```

`status` in this body is the approval state (`pending` or, in step 6, `expired`). `result` is only the operation. A terminal replay uses `result` = `already_decided` and never uses `result` to mean the approval state.

**Reconcile**

Used when a `POST` finds `posting` with the lock free, and once a minute for `posting` rows whose lock is free and whose `created_at` is more than 60 seconds ago.

Call `conversations.history` for `SLACK_CHANNEL_ID` with `limit` 100. A hit is a message whose `metadata.event_payload.request_id` equals this id.

* Hit, and `now <= expires_at`: store that channel and `ts`, set `pending` and `card_updated_at`, return `200` `result=created`.
* Hit, and `now > expires_at`: store the `ts`, then take the expiry transition. Return `200` `result=created` with `status` = `expired`.
* No hit: set `failed`. The `POST` that started this reconcile continues into re-drive. The minute scanner stops after setting `failed` and waits for the caller's `POST`.
* History call fails: leave `posting`. The `POST` returns the unknown `502`. The scanner tries again next minute.

This channel is a dedicated approval channel. The search window is the latest 100 messages. A card that has scrolled out of that window is treated as a miss; the re-drive posts a new card, and §5.4 ignores clicks on any older `ts`.

**Re-drive**

Under the same lock, update the existing `failed` row: new `system_source`, `callback_url`, `title`, `details`, `expires_at`, and `created_at`; `status = 'posting'`; clear `slack_channel_id`, `slack_message_ts`, `decided_by`, `decided_at`, `callback_state`, `callback_delivered_at`, `callback_error_log`, and `card_updated_at`. Then post once, as in create step 4. The conditional predicate is `status = 'failed'`. Zero rows means another writer moved the row; re-read it and follow §5.1.

### 5.4 Decisions, Expiry Clicks, and Card Repair

A request is past due when `now > expires_at`. A click at exactly `expires_at` is still in time.

Verify the signature before reading the row. Parse the form only after that. The button `value` is the `request_id`. `decided_by` is `payload.user.id`.

**Stale card.** If `slack_message_ts` is stored and `payload.message.ts` is different, `chat.update` that older message to the text `This approval card was replaced by a newer request with the same ID.` and remove its buttons. Return an empty `200`. Leave the row unchanged.

**Already terminal.** If `status` is `approved`, `rejected`, or `expired`, do not change the decision and do not schedule a callback. `chat.update` the clicked message to the stored presentation in §5.8. On success set `card_updated_at`. Return an empty `200`.

**Winning update.** For `posting`, `pending`, or `failed`, when the click is the current card (or `slack_message_ts` is still null):

```sql
UPDATE approval_requests
SET status = :new_status,
    slack_channel_id = :channel,
    slack_message_ts = :ts,
    decided_by = :decided_by,
    decided_at = :decided_at,
    callback_state = 'pending',
    callback_delivered_at = NULL,
    callback_error_log = NULL,
    card_updated_at = NULL
WHERE request_id = :request_id
  AND status IN ('pending', 'posting', 'failed');
```

* In time, `action_id` `approve_request`: `new_status = approved`, `decided_by` = the user id, `decided_at` = now.
* In time, `action_id` `reject_request`: `new_status = rejected`, same actor and time.
* Past due, either button: `new_status = expired`, `decided_by` null, `decided_at` = now.

One changed row is the winner. The winner `chat.update`s the card, then schedules one callback (§5.5), then returns an empty `200`. Zero changed rows means another writer won: re-read the row and follow the already-terminal rule. Slack may redeliver the interaction; the second delivery changes zero rows.

`chat.update` failure does not roll back the decision and does not cancel the callback. The exchange is still the paired record in §5.10. `card_updated_at` stays null, and the minute scanner retries the card update.

Any other `action_id` returns an empty `200` and does not touch the row.

### 5.5 Callback Runner

The interactive handler and the scheduler both call the same in-process `schedule_callback(request_id)`. This is not FastAPI `BackgroundTasks`; the scheduler has no HTTP request.

The runner keeps an in-memory set of ids already in a wave. A second schedule for an id in that set does nothing.

Each wave:

1. `POST` `callback_url` immediately.
2. On failure, retry three more times, waiting 2 seconds, then 5 seconds, then 10 seconds.
3. Any HTTP 2xx sets `callback_state = delivered`, sets `callback_delivered_at`, and clears `callback_error_log`.
4. Four failures set `callback_state = exhausted` and write the last status code and error text to `callback_error_log`. Each attempt is its own `message_exchanges` row (§5.10). `status` and the card stay as they are.

Payload:

```json
{
  "request_id": "demo-req-001",
  "status": "approved",
  "decided_by": "U012AB3CD",
  "decided_at": "2026-11-11T16:30:00Z"
}
```

`status` is `approved`, `rejected`, or `expired`. For `expired`, `decided_by` is JSON `null` and `decided_at` is when the row became `expired`.

Delivery is at least once for that one final status. The caller treats a repeat of the same `request_id` and `status` as the same decision. A create that returns `502` does not send a callback.

If the process dies during a wave, `callback_state` is still `pending` and the in-memory set is gone. The next minute scan schedules the wave again. An `exhausted` row is not scheduled again.

### 5.6 Minute Scanner

APScheduler runs every 60 seconds in the same process. Each tick, in order:

1. **Expire.** Conditional update of rows with `status = 'pending'` and `expires_at < now` to `expired`, with `decided_by` null, `decided_at` now, `callback_state = 'pending'`, and `card_updated_at` null. The scanner's predicate is only `pending`. A row still `posting` is not expired here; tick 4 reconciles it. Each row the update actually changes gets a card update and `schedule_callback`.
2. **Finish callbacks.** For `callback_state = 'pending'` whose id is not in the runner set, call `schedule_callback`.
3. **Repair cards.** For `approved`, `rejected`, or `expired` with a stored `slack_message_ts` and `card_updated_at` null, `chat.update` to §5.8. Set `card_updated_at` on success.
4. **Reconcile abandoned posts.** For `posting` whose per-id lock is free and whose `created_at` is older than 60 seconds, run the history reconcile in §5.3. The scanner does not re-drive a miss; it leaves `failed` for the caller's `POST`.
5. **Close abandoned exchanges.** For `message_exchanges` still `sent` or `received` whose `sent_at` is older than 60 seconds and whose `exchange_id` is not in the in-flight set, set `exchange_status = timeout`, `business_outcome = unknown`, and leave `response_body` null.
6. **Purge trace rows.** Delete `http_call_logs` older than 30 days. Delete `message_exchanges` and `business_audit_logs` older than 365 days. A failure here is an ERROR on stderr and does not stop steps 1–5.

### 5.7 Slack Signature

Read the raw body bytes before parsing.

* Headers `X-Slack-Request-Timestamp` and `X-Slack-Signature` are both required.
* Reject when `abs(now - timestamp) > 300` seconds.
* Base string is `v0:` + timestamp + `:` + raw body.
* Expected signature is `v0=` + hex HMAC-SHA256 of that base string, keyed with `SLACK_SIGNING_SECRET`.
* Compare with a constant-time compare.

Failure returns `400` and does not change the database.

### 5.8 Card

`chat.postMessage` body:

```json
{
  "channel": "C01234567",
  "text": "Purchase order approval #PO-2026-001",
  "metadata": {
    "event_type": "approval_request",
    "event_payload": {"request_id": "demo-req-001"}
  },
  "blocks": [
    {
      "type": "header",
      "text": {"type": "plain_text", "text": "Purchase order approval #PO-2026-001"}
    },
    {
      "type": "section",
      "fields": [
        {"type": "mrkdwn", "text": "*amount*\n$12,500.00"},
        {"type": "mrkdwn", "text": "*vendor*\nAcme Corp"}
      ]
    },
    {
      "type": "actions",
      "block_id": "approval_actions",
      "elements": [
        {
          "type": "button",
          "action_id": "approve_request",
          "style": "primary",
          "text": {"type": "plain_text", "text": "Approve"},
          "value": "demo-req-001"
        },
        {
          "type": "button",
          "action_id": "reject_request",
          "style": "danger",
          "text": {"type": "plain_text", "text": "Reject"},
          "value": "demo-req-001"
        }
      ]
    },
    {
      "type": "context",
      "elements": [
        {"type": "mrkdwn", "text": "demo-req-001 · ERP-System · expires 2026-11-11T17:00:00Z"}
      ]
    }
  ]
}
```

`details` renders at most 10 fields. Keys and values are strings. The header and the notification `text` are the title, truncated to 150 characters. Omit the section when `details` is null.

Terminal `chat.update` keeps the header and the context, removes the actions, and uses one section:

| Status | Section text |
|---|---|
| `approved` | `Approved by <decided_by> at <decided_at>.` |
| `rejected` | `Rejected by <decided_by> at <decided_at>.` |
| `expired` | `This approval request expired at <expires_at>.` |

### 5.9 Request Validation

`POST /api/v1/approvals` rejects a body that fails these checks with one `422` `ValidationError`. The message is `<field>: <reason>`.

| Field | Rule |
|---|---|
| `request_id` | String, 1–128 characters, no leading or trailing space |
| `system_source` | String, 1–128 characters |
| `callback_url` | `http` or `https` URL, at most 2048 characters |
| `title` | String, 1–150 characters |
| `details` | Omitted, JSON `null`, or an object of at most 10 string values |
| `timeout_minutes` | Integer from 1 to 10080 |

### 5.10 Integration Message Trace

Every cross-system API call produces one exchange record. The record has one `exchange_id`. It is tied to the business `request_id` and to the chain `correlation_id`. Success, HTTP failure, transport failure, and timeout are all kept. A response that has not arrived is not invented.

The three logs are written for the same call and answer different questions:

| Log | Table | Question it answers |
|---|---|---|
| HTTP call log | `http_call_logs` | Who called which interface, and when |
| Message exchange | `message_exchanges` | Which request message was sent, and which response came back |
| Business audit | `business_audit_logs` | Who approved, rejected, or expired the request, and how `status` changed |

**Exchange lifecycle**

1. Inbound: insert the row with the request headers and body, `exchange_status = received`, and null response fields before business processing.
2. Outbound: insert the row with the request headers and body, `exchange_status = sent`, and null response fields before the bytes are sent.
3. When a real response arrives, update that same `exchange_id`. Set `exchange_status = completed`, `http_status`, response headers, response body, `received_at`, `duration_ms`, and `business_outcome`. Do not insert a second row for the response.
4. On timeout or a dropped connection, update that same row to `timeout` or `transport_failed`. `response_body` stays null. `business_outcome` is `unknown`.
5. The HTTP call log is one index row pointing at `exchange_id`. It stores method, URL, systems, status, and duration. It does not store the messages.
6. A status change inserts one business audit row in the same transaction as the `approval_requests` update. `actor` is the Slack user id, or `system` for the scanner and for a Slack `ok: false`. `reason` names the transition, for example `approve`, `reject`, `expire`, `slack_post_failed`.

Operations are `create_approval`, `get_approval`, `read_trace`, `list_exchanges`, `get_exchange`, `read_summary`, `slack_interactive`, `slack_post_message`, `slack_update_message`, `slack_history`, and `callback`. `source_system` and `target_system` are the caller's `system_source`, `slack-approval-proxy`, or `slack`. An outbound callback uses `slack-approval-proxy` as the source and the host of `callback_url` as the target. `url` has no query string.

`request_body` and `response_body` are the messages. A body over 1 MiB keeps its first 1 MiB and sets `body_truncated` to 1. `GET` may store a null `request_body`. An empty proxy `200` stores an empty response string, which is a real response.

`business_outcome` is separate from `http_status`. HTTP 200 is not treated as business success by itself.

| Response | `business_outcome` |
|---|---|
| This proxy's JSON with a top-level `error` | `failed` |
| This proxy's JSON without `error`, including `status = pending` | `succeeded` |
| Slack JSON with `ok: false`, including when HTTP is 200 | `failed` |
| Slack JSON with `ok: true` | `succeeded` |
| External callback HTTP non-2xx, or JSON with `success: false` or a top-level `error` | `failed` |
| External callback HTTP 2xx without those failure markers | `succeeded` |
| `timeout` or `transport_failed` | `unknown` |

An external body whose `status` is `rejected` is still a successful delivery of the decision. That word does not set `business_outcome` to `failed`.

**Reliability**

* If the inbound request row cannot be inserted, return `503` `MessageTraceError` and do not run the business step.
* If the outbound request row cannot be inserted, do not send. Create then returns `503` and leaves the approval `posting`, so a later `POST` can reconcile. A callback attempt is not counted as one of the four deliveries.
* If updating the same row with a real response fails, retry that update three times, then emit stderr ERROR `message_trace_write_failed`. Do not insert another response row.
* If the business audit insert fails, roll back the status change and return `500`. A new status without an audit row is not committed.
* If only the HTTP call log insert fails, emit the same ERROR and continue. The exchange row remains the message record.

**Masking, access, retention, backup**

Stored headers are a JSON object. The values of `Authorization`, `X-API-Key`, `Cookie`, `X-Slack-Signature`, and any header carrying the bot token are `***`. In a JSON body, the values of `national_id`, `id_card`, `bank_account`, `bank_card`, `password`, `access_token`, `refresh_token`, `api_key`, `token`, and `secret` are `***`, including one level of nested objects. Every other business field is kept as received.

`GET /api/v1/approvals/{request_id}/trace` requires `X-API-Key` and returns the chain for that id: `correlation_id`, `message_exchanges`, `http_call_logs`, and `business_audit_logs`, already masked. There is no anonymous read. A missing approval is `404`. The control tower in §8 is the maintenance screen for the same records. It cannot change them.

`http_call_logs` are kept 30 days. `message_exchanges` and `business_audit_logs` are kept 365 days. §5.6 deletes them. The backup of this service is a copy of `approvals.db`; that file contains all three tables. Stderr ERROR `message_trace_write_failed` is the alert. It is not omitted at INFO log level.

---

## 6. API Contract

### 6.1 Create an Approval Request

* **URL**: `/api/v1/approvals`
* **Method**: `POST`
* **Headers**: `Content-Type: application/json`, `X-API-Key`

```json
{
  "request_id": "demo-req-001",
  "system_source": "ERP-System",
  "callback_url": "https://webhook.site/your-unique-id",
  "title": "Purchase order approval #PO-2026-001",
  "details": {
    "amount": "$12,500.00",
    "vendor": "Acme Corp",
    "item": "Server Hardware"
  },
  "timeout_minutes": 30
}
```

Success (`200`, new row, re-drive, or reconcile that found the card) is the `result=created` body in §5.3. Duplicate and error behavior are §5.1 and §5.2.

A terminal duplicate is also `200`:

```json
{
  "result": "already_decided",
  "request_id": "demo-req-001",
  "correlation_id": "6f1c0c3e-7b2a-4e5d-9a11-2c8e5b7d4a10",
  "system_source": "ERP-System",
  "status": "approved",
  "decided_by": "U012AB3CD",
  "decided_at": "2026-11-11T16:30:00Z",
  "expires_at": "2026-11-11T17:00:00Z",
  "created_at": "2026-11-11T16:00:00Z",
  "callback_state": "delivered",
  "callback_delivered_at": "2026-11-11T16:30:02Z",
  "callback_error_log": null
}
```

### 6.2 Get Approval Status

* **URL**: `/api/v1/approvals/{request_id}`
* **Method**: `GET`
* **Header**: `X-API-Key`

`200` for every stored status, including `posting` and `failed`:

```json
{
  "request_id": "demo-req-001",
  "correlation_id": "6f1c0c3e-7b2a-4e5d-9a11-2c8e5b7d4a10",
  "system_source": "ERP-System",
  "status": "approved",
  "decided_by": "U012AB3CD",
  "decided_at": "2026-11-11T16:30:00Z",
  "expires_at": "2026-11-11T17:00:00Z",
  "created_at": "2026-11-11T16:00:00Z",
  "callback_state": "exhausted",
  "callback_delivered_at": null,
  "callback_error_log": "HTTP 503: connection reset"
}
```

`decided_by` and `decided_at` are null for `posting`, `pending`, and `failed`. Callback fields are null until a terminal update starts a wave. A missing id is `404`. A bad API key is `401`.

### 6.5 Read the message trace

* **URL**: `/api/v1/approvals/{request_id}/trace`
* **Method**: `GET`
* **Header**: `X-API-Key`

`200` returns `correlation_id` and the three lists from §5.10, in `sent_at` / `called_at` / `created_at` order. Bodies and headers are the masked copies. A missing approval is `404`. The path is `/{request_id}/trace`, which is a different route from `/{request_id}`.

### 6.6 List and open one exchange

These reads feed the control tower. All require `X-API-Key`.

* `GET /api/v1/message-exchanges`
* `GET /api/v1/message-exchanges/summary`
* `GET /api/v1/message-exchanges/{exchange_id}`

The list accepts `request_id`, `correlation_id`, `direction`, `exchange_status`, `business_outcome`, `operation`, `page` (from 1), and `size` (default 20, maximum 100). `200` returns `items`, `page`, `size`, and `total`. Each item is a summary: `exchange_id`, `correlation_id`, `request_id`, `direction`, `source_system`, `target_system`, `operation`, `http_method`, `url`, `exchange_status`, `http_status`, `business_outcome`, `sent_at`, `received_at`, `duration_ms`, `attempt`. The list omits headers and bodies. Unless `include_operator_reads=true`, the list hides `list_exchanges`, `get_exchange`, `read_trace`, and `read_summary`, so the page does not fill itself with its own lookups. `total` uses that same filter.

The detail returns the full masked exchange, the HTTP call log rows for that `exchange_id`, and the business audit rows for that `request_id`. A missing `exchange_id` is `404`.

`GET /api/v1/message-exchanges/summary` is a fixed path, registered ahead of `/{exchange_id}`. It takes the same `include_operator_reads` flag. `200` returns counts over the exchanges that the list would include, plus pending approvals:

```json
{
  "exchanges_total": 12,
  "exchanges_succeeded": 7,
  "exchanges_failed": 3,
  "exchanges_open": 2,
  "approvals_pending": 1,
  "systems": [
    {
      "system": "ERP-System",
      "last_sent_at": "2026-11-11T16:00:00Z",
      "last_business_outcome": "succeeded"
    }
  ]
}
```

`exchanges_succeeded` counts `exchange_status = completed` and `business_outcome = succeeded`. `exchanges_failed` counts `business_outcome = failed` or `exchange_status` of `timeout` or `transport_failed`. `exchanges_open` counts `received` and `sent`. `approvals_pending` counts `approval_requests.status = pending`. `systems` lists every distinct `source_system` and `target_system` on the included rows. `last_sent_at` and `last_business_outcome` come from that system's newest exchange. The three exchange counts are subsets of `exchanges_total`. They do not have to add up to it.

Opening the page is itself inbound traffic from `operator-ui`. Record it: `list_exchanges`, `get_exchange`, `read_trace`, and `read_summary` follow §5.10. A failure to record one of these reads returns `503` and the page shows that error. It does not show an empty chain in place of a trace failure.

### 6.3 Slack Interactive Callback

* **URL**: `/api/v1/slack/interactive`
* **Method**: `POST`
* **Headers**: `X-Slack-Request-Timestamp`, `X-Slack-Signature`
* **Body**: `application/x-www-form-urlencoded` with a JSON `payload` field

Recognized clicks return an empty `200` after the rules in §5.4 and §5.7. Signature failure is `400`. An unknown `request_id` is `404`.

### 6.4 Outbound Webhook

Payload, retries, and `callback_error_log` are §5.5. The proxy calls `callback_url` only after a winning transition to `approved`, `rejected`, or `expired`.

---

## 7. Deployment and Demo

### 7.1 Local Setup

   ```bash
pip install fastapi uvicorn pydantic aiosqlite httpx python-dotenv apscheduler
uvicorn main:app --port 8000
```

Startup creates `approvals.db` when the file is absent and starts the minute scanner once in the process lifespan.

### 7.2 Public URL for Slack (ngrok)

1. Run `ngrok http 8000`.
2. In the Slack app, open **Interactivity & Shortcuts** and enable it.
3. Set **Request URL** to `https://<ngrok-host>/api/v1/slack/interactive`.
4. Install the app with `chat:write`, `channels:history`, and `groups:history`, and invite the bot to `SLACK_CHANNEL_ID`.

### 7.3 Demo Run

1. Open [Webhook.site](https://webhook.site/) and copy a unique URL.
2. Create an approval:

   ```bash
   curl -X POST "http://localhost:8000/api/v1/approvals" \
   -H "Content-Type: application/json" \
   -H "X-API-Key: erp-system-secret-key-123" \
   -d '{
     "request_id": "demo-req-001",
     "system_source": "ERP-System",
     "callback_url": "https://webhook.site/your-unique-id",
     "title": "Purchase order approval #PO-2026-001",
     "details": {
       "amount": "$12,500.00",
       "vendor": "Acme Corp"
     },
     "timeout_minutes": 30
   }'
   ```

3. Click **Approve** in the channel. The card loses its buttons. Webhook.site receives one decision payload.
4. Repeat the same `curl` while the row is `pending`. The response is `409` and no second card appears.
5. After Approve, Reject, or expiry, the same `curl` returns `200` with `result` = `already_decided` and the stored outcome.
6. `GET http://localhost:8000/api/v1/approvals/demo-req-001` with the same API key shows `callback_state` and `callback_error_log`.
7. Open `http://localhost:8000/`. Enter the API key, search `demo-req-001`, and confirm the request message and the response message for the create, the Slack card, and the callback. A row still `sent` or `timeout` shows no fabricated response. The screens are `doc/integration_control_tower_frontend.md`.

---

## 8. Control tower

The console maintains the trace by search and inspection. It does not insert, edit, or delete rows. Retention stays on the scanner in §5.6.

Screen layout, routes, and the static module shape are `doc/integration_control_tower_frontend.md`. Bootstrap serves `static/index.html` at `GET /` and mounts the same directory at `/static`. The console calls only the reads in §6.5 and §6.6, including `GET /api/v1/message-exchanges/summary`. It contains no approval rules and no Slack calls.

The API key is typed into the page and kept in `sessionStorage` under `integration_hub_api_key` for that browser session. The HTML and script do not contain the key. Closing the session forgets it. Every request sends it as `X-API-Key`. A `401` clears the stored key and asks again.

`401` says the key is missing or wrong. `404` says the id was not found. `503` says the trace could not be recorded. A list with no rows says no exchanges matched. Bodies are shown as stored, including masking and a visible note when `body_truncated` is 1. `sent` and `timeout` show the request and an explicit empty response: `No response recorded`. The page does not display a synthetic HTTP 200. HTTP status and `business_outcome` stay on screen together.
