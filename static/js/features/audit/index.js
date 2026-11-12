import { auditTemplate } from "./template.js?v=1";
import { outcomeClass, problemHtml } from "../../ui/format.js?v=1";

export function render() {
  return auditTemplate();
}

export function init(query) {
  const form = document.getElementById("auditForm");
  const field = document.getElementById("auditRequestId");
  field.value = query.get("request_id") || "";
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    window.location.hash = `#/audit?request_id=${encodeURIComponent(field.value.trim())}`;
  });
  if (field.value) load(field.value);
}

async function load(requestId) {
  const target = document.getElementById("auditResult");
  const result = await window.HttpClient.get(`/api/v1/approvals/${encodeURIComponent(requestId)}/trace`);
  const problem = problemHtml(result);
  if (problem) {
    target.innerHTML = problem;
    return;
  }
  const body = result.body;
  target.innerHTML = `
    <p>correlation_id ${window.esc(body.correlation_id)}</p>
    <section class="stack"><h2>Message exchanges</h2>${exchangeTable(body.message_exchanges)}</section>
    <section class="stack"><h2>HTTP call logs</h2>${callTable(body.http_call_logs)}</section>
    <section class="stack"><h2>Business audit</h2>${auditTable(body.business_audit_logs)}</section>
  `;
  target.querySelectorAll("tr.pick").forEach((row) => {
    row.addEventListener("click", () => {
      window.location.hash = `#/exchange?exchange_id=${row.dataset.exchangeId}`;
    });
  });
}

function exchangeTable(rows) {
  if (!rows.length) return "<p>No exchanges matched.</p>";
  const body = rows.map((row) => `
    <tr class="pick" data-exchange-id="${window.esc(row.exchange_id)}">
      <td>${window.esc(row.sent_at)}</td>
      <td>${window.esc(row.direction)}</td>
      <td>${window.esc(row.source_system)}</td>
      <td>${window.esc(row.target_system)}</td>
      <td>${window.esc(row.operation)}</td>
      <td>${window.esc(row.http_status)}</td>
      <td class="${outcomeClass(row.business_outcome)}">${window.esc(row.business_outcome)}</td>
      <td class="${outcomeClass(row.exchange_status)}">${window.esc(row.exchange_status)}</td>
    </tr>
  `).join("");
  return `<table><tr><th>Sent</th><th>Direction</th><th>Source</th><th>Target</th><th>Operation</th><th>HTTP</th><th>Business</th><th>Status</th></tr>${body}</table>`;
}

function callTable(rows) {
  if (!rows.length) return "<p>No exchanges matched.</p>";
  const body = rows.map((row) => `<tr><td>${window.esc(row.called_at)}</td><td>${window.esc(row.operation)}</td><td>${window.esc(row.http_status)}</td><td>${window.esc(row.duration_ms)}</td></tr>`).join("");
  return `<table><tr><th>Called</th><th>Operation</th><th>HTTP</th><th>Duration</th></tr>${body}</table>`;
}

function auditTable(rows) {
  if (!rows.length) return "<p>No exchanges matched.</p>";
  const body = rows.map((row) => `<tr><td>${window.esc(row.created_at)}</td><td>${window.esc(row.from_status)}</td><td>${window.esc(row.to_status)}</td><td>${window.esc(row.actor)}</td><td>${window.esc(row.reason)}</td></tr>`).join("");
  return `<table><tr><th>When</th><th>From</th><th>To</th><th>Actor</th><th>Reason</th></tr>${body}</table>`;
}
