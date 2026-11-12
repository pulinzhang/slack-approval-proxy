const API_KEY_STORAGE = "integration_hub_api_key";

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showToast(message, kind) {
  const toast = document.createElement("div");
  toast.className = `toast ${kind || "error"}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  window.setTimeout(() => toast.remove(), 4000);
}

const HttpClient = {
  async get(url, params) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([name, value]) => {
      if (value === undefined || value === null || value === "") return;
      query.append(name, String(value));
    });
    const target = query.toString() ? `${url}?${query}` : url;
    const key = sessionStorage.getItem(API_KEY_STORAGE) || "";
    let response;
    try {
      response = await fetch(target, { headers: { "X-API-Key": key } });
    } catch (_error) {
      return {
        ok: false,
        status: 0,
        body: { error: "Network", message: "The server could not be reached" },
      };
    }
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) {
      sessionStorage.removeItem(API_KEY_STORAGE);
      const field = document.getElementById("apiKey");
      if (field instanceof HTMLInputElement) field.focus();
      showToast(body.message || "Invalid or missing X-API-Key header", "error");
    }
    return { ok: response.ok, status: response.status, body };
  },
};

window.esc = esc;
window.showToast = showToast;
window.HttpClient = HttpClient;
window.API_KEY_STORAGE = API_KEY_STORAGE;
