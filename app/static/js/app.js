/* SmartShop AI - shared frontend utilities */

const API_BASE = "/api";

const Auth = {
  getToken() { return localStorage.getItem("smartshop_token"); },
  setToken(t) { localStorage.setItem("smartshop_token", t); },
  getUser() {
    try {
      const raw = localStorage.getItem("smartshop_user");
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  },
  setUser(user) { localStorage.setItem("smartshop_user", JSON.stringify(user)); },
  clearUser() { localStorage.removeItem("smartshop_user"); },
  clear() {
    localStorage.removeItem("smartshop_token");
    localStorage.removeItem("smartshop_user");
  },
  isAdmin() { return this.getUser()?.role === "admin"; },
  isLoggedIn() { return !!this.getToken(); },
};

async function apiFetch(path, options = {}) {
  const headers = options.headers || {};
  headers["Content-Type"] = "application/json";
  const token = Auth.getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function fmtPrice(p) {
  if (p === null || p === undefined) return "Price unavailable";
  return `₹${Number(p).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function fmtRating(r) {
  return r === null || r === undefined ? "No rating" : `${r}★`;
}

function fmtReviews(n) {
  return n === null || n === undefined ? "" : `${Number(n).toLocaleString("en-IN")} reviews`;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------------- Theme ---------------- */
function initTheme() {
  const saved = localStorage.getItem("smartshop_theme") || "light";
  document.documentElement.setAttribute("data-theme", saved);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  const next = current === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("smartshop_theme", next);
  updateThemeIcon();
}

/* ---------------- Nav ---------------- */
function renderNav(activePage) {
  const el = document.getElementById("navbar");
  if (!el) return;
  const isAdmin = Auth.isAdmin();
  const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
  const themeIcon = currentTheme === "light" ? "☀" : "☾";
  el.innerHTML = `
    <a class="brand" href="/">
      SmartShop <span style="color:var(--primary)">AI</span>
      <span class="tag">Discover · Compare · Shop Smarter</span>
    </a>
    <div class="nav-links">
      <a href="/" class="${activePage === 'home' ? 'active' : ''}">Search</a>
      <a href="/assistant" class="${activePage === 'assistant' ? 'active' : ''}">AI Assistant</a>
      <a href="/analytics" class="${activePage === 'analytics' ? 'active' : ''}">Analytics</a>
      ${isAdmin ? `<a href="/admin" class="${activePage === 'admin' ? 'active' : ''}">Admin</a>` : ""}
      <button class="icon-btn" onclick="toggleTheme()" title="Toggle theme">${themeIcon}</button>
    </div>
  `;
}

function updateThemeIcon() {
  const btn = document.querySelector('.icon-btn');
  if (btn) {
    const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
    btn.textContent = currentTheme === "light" ? "☀" : "☾";
  }
}

function trackOutboundClick(el) {
  const payload = {
    product_id: el?.dataset?.productId || null,
    offer_id: el?.dataset?.offerId || null,
    platform: el?.dataset?.platform || null,
    title: el?.dataset?.title || null,
    url: el?.dataset?.url || null,
  };
  const body = JSON.stringify(payload);
  if (navigator.sendBeacon) {
    navigator.sendBeacon("/api/analytics/click-out", new Blob([body], { type: "application/json" }));
    return true;
  }
  fetch("/api/analytics/click-out", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
    keepalive: true,
  }).catch(() => {});
  return true;
}

/* ---------------- Product card rendering ---------------- */
function productCardHtml(p, { selectable = false } = {}) {
  const offersBadges = (p.offers || [])
    .map(o => `<span class="badge badge-${o.platform}">${o.platform}</span>`)
    .join(" ");
  const img = p.primary_image_url || "https://via.placeholder.com/300x200?text=No+Image";
  const variant = p.rec_type || "default";
  return `
    <div class="card card-${variant}" data-product-id="${p.id}">
      ${selectable ? `<label class="checkbox-row"><input type="checkbox" class="compare-check" value="${p.id}"> Select to compare</label>` : ""}
      <img src="${img}" alt="${escapeHtml(p.canonical_title)}" onerror="this.src='https://via.placeholder.com/300x200?text=No+Image'">
      <h3>${escapeHtml(p.canonical_title)}</h3>
      <div>${offersBadges}</div>
      <div class="price">${fmtPrice(p.best_price)}</div>
      <div class="meta"><span>${fmtRating(p.avg_rating)}</span><span>${fmtReviews(p.total_reviews)}</span></div>
      ${p.ai_reason ? `<div class="ai-reason">${escapeHtml(p.ai_reason)}</div>` : ""}
      <div class="actions">
        <a class="btn btn-primary" href="/product?id=${p.id}">View details</a>
      </div>
    </div>
  `;
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
});
