# Integration Control Tower

## Frontend design

The console is the read-only face of the Slack Approval Proxy. Behavior that the screens must not break is §8 of `doc/slack_approval_proxy_mvp_technical_design_document.md`. This file specifies the shell, the routes, and what each screen shows.

The brand in the sidebar is **Integration Hub**, with the small label **MVP**. The product line is **Enterprise Integration Gateway**. The document title and the browser title are **Integration Control Tower**.

The layout is an industrial control tower: a dark canvas, a left rail, a top bar, a row of counts, and a dense message table. It is a viewing console for exchanges, approvals, and audit. It is not an admin product for master data.

---

## 1. Stack and module shape

The console is a static hash SPA, the same shape as a small `static/` app:

| Piece | Role |
|---|---|
| `static/index.html` | Shell. Served at `GET /` with `Cache-Control: no-cache` |
| `static/css/style.css` | Shell only: rail, top bar, canvas, count cards, table, two-pane inspector |
| `static/js/main.js` | `esc`, `showToast`, `HttpClient`. Loaded as a classic script |
| `static/js/app.js` | Hash router. Loaded as `type="module"` |
| `static/js/features/index.js` | `pageMeta` |
| `static/js/features/<page>/template.js` | HTML string for that screen |
| `static/js/features/<page>/index.js` | `render` and `init`. State stays in the module |
| `static/js/ui/page-size.js` | Page size and page buttons for the exchange list |

`static/js` holds only `main.js` and `app.js`. A new screen adds `pageMeta`, a `pageLoaders` entry in `app.js`, and a sidebar `data-page` when the screen is a menu item. Inspector is opened from a row and stays off the menu.

There is no login page, no permission catalog, no theme switch, no build step, and no server template. Third-party scripts are not loaded from a CDN. User-visible text that comes from the API passes through `esc`.

Changing a script increments the `?v=` on that script in `index.html` or in the `import()` path. The HTML itself is not cached.

Identifiers in JavaScript are camelCase. A page object is PascalCase. A constant is `UPPER_SNAKE`. Fields copied from the API keep the API's snake_case names.

---

## 2. Shell

```text
static/index.html
├── aside#sidebar
│     brand: INTEGRATION HUB / MVP
│     a[data-page=overview]   Overview
│     a[data-page=exchanges]  Exchanges
│     a[data-page=map]        Map
│     a[data-page=audit]      Audit
├── header
│     current title
│     API key field and save
└── main#pageContent
```

The default hash is `#/overview`. `#/` and an empty hash land there. A hash the router does not know also lands there.

The API key field writes `sessionStorage` key `integration_hub_api_key`. The source never contains a key. The key is not put in the URL or in `localStorage`. `HttpClient` sends it as `X-API-Key`. A `401` removes the stored key, shows `message`, and focuses the field.

`HttpClient` returns `{ ok, status, body }`. `body` is the JSON object as the server sent it. The client does not unwrap a `success` / `data` envelope. A list reads `body.items` and `body.total`. An error reads `body.error` and `body.message`.

| Status | What the screen shows |
|---|---|
| `401` | The key is missing or wrong |
| `404` | That id was not found |
| `503` | The trace could not be recorded. The screen does not replace this with an empty table or an empty chain |
| `200` and `items` empty | No exchanges matched |

HTTP status and `business_outcome` are both shown. A row with HTTP 200 and `business_outcome = failed` is a failure. `sent` and `timeout` keep the request and the sentence `No response recorded`.

---

## 3. Screens

### 3.1 Overview `#/overview`

`GET /api/v1/message-exchanges/summary` fills five counts: exchanges total, succeeded, failed, open, and pending approvals. The counts are retained rows, not a rolling 24-hour window.

Under the counts, `GET /api/v1/message-exchanges?business_outcome=failed&page=1&size=10` shows the newest failed exchanges: `sent_at`, `request_id`, `direction`, `source_system`, `target_system`, `operation`, `http_status`, `business_outcome`, `exchange_status`. Choosing a row navigates to `#/exchange?exchange_id=...`.

### 3.2 Exchanges `#/exchanges`

The list from §6.6, newest `sent_at` first. Filters are `request_id`, `correlation_id`, `direction`, `exchange_status`, `business_outcome`, and `operation`, plus a switch for `include_operator_reads`. `page` and `size` come from `page-size.js`. The table shows the summary fields and omits headers and bodies. Choosing a row opens the inspector.

### 3.3 Inspector `#/exchange?exchange_id=`

`GET /api/v1/message-exchanges/{exchange_id}`.

A strip above the panes shows `exchange_id`, `correlation_id`, `request_id`, direction, source, target, operation, method, URL, `sent_at`, `received_at`, `http_status`, `business_outcome`, `exchange_status`, `duration_ms`, and `attempt`.

The left pane is the request: masked `request_headers` and `request_body`. The right pane is the response: masked `response_headers` and `response_body`. When `body_truncated` is 1, both panes note that the stored body was cut at 1 MiB.

Below the panes, the same payload's HTTP call log rows for that `exchange_id`, then the business audit rows for that `request_id`. A link on `request_id` opens `#/audit?request_id=...`.

### 3.4 Map `#/map`

`summary.systems` is the node list. Each node shows `system`, `last_sent_at`, and `last_business_outcome`. Edges are the distinct `source_system` → `target_system` pairs on the current exchange list, loaded with `size=100` and the same operator-read switch as Exchanges. The screen has no editor. A system name is not a configured adapter record.

The nodes this MVP can show are the caller's `system_source`, `slack-approval-proxy`, `slack`, `operator-ui`, and the host of `callback_url`.

### 3.5 Audit `#/audit?request_id=`

The operator enters `request_id`. `GET /api/v1/approvals/{request_id}/trace` fills three stacks, in `sent_at` / `called_at` / `created_at` order:

1. Message exchanges, the chain from the caller through the proxy to Slack and back out the callback.
2. HTTP call logs.
3. Business audit: `from_status`, `to_status`, `actor`, `reason`, `created_at`.

Choosing an exchange opens the inspector. A missing approval shows the `404` message.

---

## 4. Acceptance

After the five demo steps in §7.3 of the behavior contract, the console can show:

1. The create, the Slack post, and their request and response bodies.
2. A rejected decision, the audit row, and the callback exchange.
3. A failed callback with the request kept, the error response kept, and a later attempt on its own `exchange_id`.
4. A repeated `request_id` that did not create a second approval row.
5. One `request_id` search whose exchanges run caller → proxy → Slack → caller, sharing one `correlation_id`.

The console never writes an approval, a Slack message, or a trace row.
