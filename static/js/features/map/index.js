import { mapTemplate } from "./template.js?v=1";
import { outcomeClass, problemHtml } from "../../ui/format.js?v=1";
import { operatorReads } from "../../ui/operator-reads.js?v=1";

export function render() {
  return mapTemplate();
}

export function init() {
  load();
}

async function load() {
  const include = operatorReads() ? "true" : "";
  const summary = await window.HttpClient.get("/api/v1/message-exchanges/summary", {
    include_operator_reads: include,
  });
  const nodes = document.getElementById("mapNodes");
  const problem = problemHtml(summary);
  if (problem) {
    nodes.innerHTML = problem;
    return;
  }
  nodes.innerHTML = summary.body.systems.map((system) => {
    const outcome = system.last_business_outcome || "open";
    return `
    <article class="node">
      <strong>${window.esc(system.system)}</strong>
      <span>${window.esc(system.last_sent_at)}</span>
      <span class="${outcomeClass(outcome)}">${window.esc(outcome)}</span>
    </article>`;
  }).join("") || "<p>No exchanges matched.</p>";
  const list = await window.HttpClient.get("/api/v1/message-exchanges", {
    include_operator_reads: include,
    page: 1,
    size: 100,
  });
  const edges = document.getElementById("mapEdges");
  const edgeProblem = problemHtml(list);
  if (edgeProblem) {
    edges.innerHTML = edgeProblem;
    return;
  }
  const pairs = new Map();
  list.body.items.forEach((item) => {
    pairs.set(`${item.source_system}→${item.target_system}`, item);
  });
  edges.innerHTML = [...pairs.values()].map((item) => `<p>${window.esc(item.source_system)} → ${window.esc(item.target_system)}</p>`).join("") || "<p>No exchanges matched.</p>";
}
