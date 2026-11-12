export function problemHtml(result) {
  if (result.ok) return "";
  return `<p class="error">${window.esc(result.body.message || "Request failed")}</p>`;
}

export function outcomeClass(value) {
  if (value === "failed" || value === "timeout" || value === "transport_failed") return "failed";
  if (value === "succeeded" || value === "completed") return "succeeded";
  return "open";
}
