import { exchangeTemplate } from "./template.js?v=1";
import { outcomeClass, problemHtml } from "../../ui/format.js?v=1";

export function render() {
  return exchangeTemplate();
}

export function init(query) {
  load(query.get("exchange_id") || "");
}

async function load(exchangeId) {
  const target = document.getElementById("inspector");
  if (!exchangeId) {
    target.innerHTML = "<p class=\"error\">That id was not found.</p>";
    return;
  }
  const result = await window.HttpClient.get(`/api/v1/message-exchanges/${encodeURIComponent(exchangeId)}`);
  const problem = problemHtml(result);
  if (problem) {
    target.innerHTML = problem;
    return;
  }
  target.innerHTML = inspector(result.body);
}

function inspector(row) {
  const response = row.exchange_status === "sent" || row.exchange_status === "timeout"
    ? "No response recorded"
    : row.response_body || "";
  const truncated = row.body_truncated ? "<p>Stored body was cut at 1 MiB.</p>" : "";
  const fields = ["exchange_id", "correlation_id", "request_id", "direction", "source_system", "target_system", "operation", "http_method", "url", "sent_at", "received_at", "http_status", "business_outcome", "exchange_status", "duration_ms", "attempt"];
  const meta = fields.map((name) => `<span><span class="muted">${window.esc(name)}</span><br />${window.esc(row[name])}</span>`).join("");
  const requestLink = row.request_id
    ? `<p><a href="#/audit?request_id=${window.esc(row.request_id)}">Open audit for ${window.esc(row.request_id)}</a></p>`
    : "";
  return `
    <div class="meta">${meta}</div>
    ${requestLink}
    ${truncated}
    <div class="panes">
      <section class="pane"><h2>Request</h2><pre>${window.esc(pretty(row.request_headers))}\n\n${window.esc(row.request_body)}</pre></section>
      <section class="pane"><h2>Response</h2><p class="${outcomeClass(row.business_outcome)}">HTTP ${window.esc(row.http_status)} · ${window.esc(row.business_outcome)}</p><pre>${window.esc(pretty(row.response_headers))}\n\n${window.esc(response)}</pre></section>
    </div>
    <section class="stack"><h2>HTTP call log</h2>${logTable(row.http_call_logs)}</section>
    <section class="stack"><h2>Business audit</h2>${auditTable(row.business_audit_logs)}</section>
  `;
}

function logTable(rows) {
  if (!rows.length) return "<p>No exchanges matched.</p>";
  const body = rows.map((row) => `<tr><td>${window.esc(row.called_at)}</td><td>${window.esc(row.http_method)}</td><td>${window.esc(row.url)}</td><td>${window.esc(row.http_status)}</td><td>${window.esc(row.duration_ms)}</td><td>${window.esc(row.error_message)}</td></tr>`).join("");
  return `<table><tr><th>Called</th><th>Method</th><th>URL</th><th>HTTP</th><th>Duration</th><th>Error</th></tr>${body}</table>`;
}

function auditTable(rows) {
  if (!rows.length) return "<p>No exchanges matched.</p>";
  const body = rows.map((row) => `<tr><td>${window.esc(row.created_at)}</td><td>${window.esc(row.from_status)}</td><td>${window.esc(row.to_status)}</td><td>${window.esc(row.actor)}</td><td>${window.esc(row.reason)}</td></tr>`).join("");
  return `<table><tr><th>When</th><th>From</th><th>To</th><th>Actor</th><th>Reason</th></tr>${body}</table>`;
}

function pretty(value) {
  if (!value) return "";
  return JSON.stringify(value, null, 2);
}
