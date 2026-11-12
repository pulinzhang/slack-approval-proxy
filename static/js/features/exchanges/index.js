import { exchangesTemplate } from "./template.js?v=1";
import { outcomeClass, problemHtml } from "../../ui/format.js?v=1";
import { bindPagination, DEFAULT_PAGE_SIZE, paintPagination } from "../../ui/page-size.js?v=1";
import { operatorReads, setOperatorReads } from "../../ui/operator-reads.js?v=1";

const state = { page: 1, filters: {} };

export function render() {
  return exchangesTemplate();
}

export function init() {
  const form = document.getElementById("exchangeFilters");
  form.include_operator_reads.checked = operatorReads();
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    state.page = 1;
    state.filters = Object.fromEntries(new FormData(form).entries());
    setOperatorReads(form.include_operator_reads.checked);
    load();
  });
  bindPagination(document.getElementById("exchangePager"), (page) => {
    state.page = page;
    load();
  });
  load();
}

async function load() {
  const form = document.getElementById("exchangeFilters");
  const include = form.include_operator_reads.checked ? "true" : "";
  const result = await window.HttpClient.get("/api/v1/message-exchanges", {
    ...state.filters,
    include_operator_reads: include,
    page: state.page,
    size: DEFAULT_PAGE_SIZE,
  });
  const target = document.getElementById("exchangeTable");
  const problem = problemHtml(result);
  if (problem) {
    target.innerHTML = problem;
    document.getElementById("exchangePager").innerHTML = "";
    return;
  }
  if (!result.body.items.length) {
    target.innerHTML = "<p>No exchanges matched.</p>";
    document.getElementById("exchangePager").innerHTML = "";
    return;
  }
  target.innerHTML = table(result.body.items);
  target.querySelectorAll("tr.pick").forEach((row) => {
    row.addEventListener("click", () => {
      window.location.hash = `#/exchange?exchange_id=${row.dataset.exchangeId}`;
    });
  });
  const pages = Math.max(1, Math.ceil(result.body.total / result.body.size));
  paintPagination(document.getElementById("exchangePager"), state.page, pages);
}

function table(items) {
  const head = "<tr><th>Sent</th><th>Request</th><th>Correlation</th><th>Direction</th><th>Source</th><th>Target</th><th>Operation</th><th>HTTP</th><th>Business</th><th>Status</th><th>Attempt</th></tr>";
  const rows = items.map((item) => `
    <tr class="pick" data-exchange-id="${window.esc(item.exchange_id)}">
      <td>${window.esc(item.sent_at)}</td>
      <td>${window.esc(item.request_id)}</td>
      <td>${window.esc(item.correlation_id)}</td>
      <td>${window.esc(item.direction)}</td>
      <td>${window.esc(item.source_system)}</td>
      <td>${window.esc(item.target_system)}</td>
      <td>${window.esc(item.operation)}</td>
      <td>${window.esc(item.http_status)}</td>
      <td class="${outcomeClass(item.business_outcome)}">${window.esc(item.business_outcome)}</td>
      <td class="${outcomeClass(item.exchange_status)}">${window.esc(item.exchange_status)}</td>
      <td>${window.esc(item.attempt)}</td>
    </tr>
  `).join("");
  return `<table>${head}${rows}</table>`;
}
