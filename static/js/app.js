import { pageMeta } from "./features/index.js?v=1";

const pageLoaders = {
  overview: () => import("./features/overview/index.js?v=1"),
  exchanges: () => import("./features/exchanges/index.js?v=1"),
  exchange: () => import("./features/exchange/index.js?v=1"),
  map: () => import("./features/map/index.js?v=2"),
  audit: () => import("./features/audit/index.js?v=1"),
};

const loadedPages = new Map();
let currentPage = null;

function pageFromHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const name = raw.split("?")[0] || "overview";
  return pageLoaders[name] ? name : "overview";
}

function queryFromHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const query = raw.split("?")[1] || "";
  return new URLSearchParams(query);
}

async function render() {
  const name = pageFromHash();
  const meta = pageMeta[name];
  document.getElementById("pageTitle").textContent = meta.title;
  document.getElementById("pageKicker").textContent = meta.en;
  document.querySelectorAll("#sidebar a[data-page]").forEach((link) => {
    link.classList.toggle("active", link.dataset.page === name);
  });
  if (currentPage && loadedPages.get(currentPage)?.destroy) {
    loadedPages.get(currentPage).destroy();
  }
  if (!loadedPages.has(name)) {
    loadedPages.set(name, await pageLoaders[name]());
  }
  const page = loadedPages.get(name);
  document.getElementById("pageContent").innerHTML = page.render(queryFromHash());
  page.init(queryFromHash());
  currentPage = name;
}

document.getElementById("apiKeyForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const field = document.getElementById("apiKey");
  sessionStorage.setItem(window.API_KEY_STORAGE, field.value.trim());
  window.showToast("API key saved for this session", "ok");
  render();
});

const savedKey = sessionStorage.getItem(window.API_KEY_STORAGE);
if (savedKey) document.getElementById("apiKey").value = savedKey;

window.addEventListener("hashchange", () => {
  render();
});

if (!window.location.hash) {
  window.location.replace("#/overview");
} else {
  render();
}
