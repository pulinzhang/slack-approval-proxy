import { overviewTemplate } from "./template.js?v=1";
import { outcomeClass, problemHtml } from "../../ui/format.js?v=1";

export function render() {
  return overviewTemplate();
}

export function init() {
  load();
}

async function load() {
  const summary = await window.HttpClient.get("/api/v1/message-exchanges/summary");
  const counts = document.getElementById("counts");
  const problem = problemHtml(summary);
  if (problem) {
    counts.innerHTML = problem;
    return;
  }
  const body = summary.body;
  counts.innerHTML = [
    ["Exchanges", body.exchanges_total],
    ["Succeeded", body.exchanges_succeeded],
    ["Failed", body.exchanges_failed],
    ["Open", body.exchanges_open],
    ["Pending approvals", body.approvals_pending],
  ].map(([label, value]) => `<article class="count"><span>${label}</span><strong>${window.esc(value)}</strong></article>`).join("");
  const failed = await window.HttpClient.get("/api/v1/message-exchanges", {
    business_outcome: "failed",
    page: 1,
    size: 10,
  });
  const target = document.getElementById("failedExchanges");
  const failedProblem = problemHtml(failed);
  if (failedProblem) {
    target.innerHTML = failedProblem;
    return;
  }
  if (!failed.body.items.length) {
    target.innerHTML = "<p>No exchanges matched.</p>";
    return;
  }
  target.innerHTML = table(failed.body.items);
  target.querySelectorAll("tr.pick").forEach((row) => {
    row.addEventListener("click", () => {
      window.location.hash = `#/exchange?exchange_id=${row.dataset.exchangeId}`;
    });
  });
}

function table(items) {
  const head = "<tr><th>Sent</th><th>Request</th><th>Direction</th><th>Source</th><th>Target</th><th>Operation</th><th>HTTP</th><th>Business</th><th>Exchange</th></tr>";
  const rows = items.map((item) => `
    <tr class="pick" data-exchange-id="${window.esc(item.exchange_id)}">
      <td>${window.esc(item.sent_at)}</td>
      <td>${window.esc(item.request_id)}</td>
      <td>${window.esc(item.direction)}</td>
      <td>${window.esc(item.source_system)}</td>
      <td>${window.esc(item.target_system)}</td>
      <td>${window.esc(item.operation)}</td>
      <td>${window.esc(item.http_status)}</td>
      <td class="${outcomeClass(item.business_outcome)}">${window.esc(item.business_outcome)}</td>
      <td class="${outcomeClass(item.exchange_status)}">${window.esc(item.exchange_status)}</td>
    </tr>
  `).join("");
  return `<table>${head}${rows}</table>`;
}
