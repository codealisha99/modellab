"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const tenant = $("memory-tenant");
  const note = $("memory-text");
  const query = $("memory-query");
  const feedback = $("memory-feedback");
  const error = $("memory-error");
  const results = $("memory-results");
  const STORE_KEY = "modellab.memory-tenant";
  let revision = 0;

  // Keep a namespace across reloads without requiring browser storage to be available.
  let saved = null;
  try { saved = sessionStorage.getItem(STORE_KEY); } catch { /* Restricted storage. */ }
  tenant.value = saved && /^[A-Za-z0-9_.-]{1,64}$/.test(saved) && saved !== "__eval__"
    ? saved : `lab-${[...crypto.getRandomValues(new Uint8Array(16))].map((n) => n.toString(16).padStart(2, "0")).join("")}`;

  function saveTenant() {
    try { sessionStorage.setItem(STORE_KEY, tenant.value.trim()); } catch { /* Restricted storage. */ }
  }
  saveTenant();
  tenant.addEventListener("input", () => {
    revision += 1;
    results.replaceChildren();
    error.hidden = true;
    feedback.textContent = "Tenant changed. Search to retrieve its notes.";
    tenant.setCustomValidity("");
    saveTenant();
  });

  function context() {
    tenant.value = tenant.value.trim();
    tenant.setCustomValidity(tenant.value === "__eval__" ? "Choose a different tenant ID; this one is reserved." : "");
    if (!tenant.reportValidity()) return null;
    return { tenant: tenant.value, revision };
  }

  async function request(path, ctx, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", "X-Tenant-Id": ctx.tenant },
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      if (response.status === 429) throw new Error("Request limit reached. Wait 60 seconds and try again.");
      throw new Error(`The service returned HTTP ${response.status}. Check the fields and try again.`);
    }
    return response.json();
  }

  async function run(button, ctx, task) {
    if (button.disabled) return;
    const label = button.textContent;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "Working…";
    error.hidden = true;
    try { await task(); }
    catch (err) {
      if (ctx.revision !== revision) return;
      error.hidden = false;
      error.textContent = err.name === "TypeError" || err.name === "TimeoutError"
        ? "Could not reach the service. Check your connection and try again." : err.message;
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = label;
    }
  }

  $("memory-add-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const ctx = context();
    if (!ctx) return;
    if (!note.value.trim()) {
      note.setCustomValidity("Enter a note before saving.");
      note.reportValidity();
      return;
    }
    const text = note.value.trim();
    const kind = $("memory-kind").value;
    const importance = Number($("memory-importance").value);
    run($("memory-save"), ctx, async () => {
      const data = await request("/v1/memory", ctx, { method: "POST", body: JSON.stringify({ text, kind, importance }) });
      if (ctx.revision !== revision) return;
      feedback.textContent = `Memory saved in ${data.kind}: ${data.memory_id}. Search to see its ranking.`;
      // Preserve a new note typed while the request was in flight.
      if (note.value.trim() === text) note.value = "";
    });
  });
  note.addEventListener("input", () => note.setCustomValidity(""));

  $("memory-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const ctx = context();
    if (!ctx) return;
    if (!query.value.trim()) {
      query.setCustomValidity("Enter a search query first.");
      query.reportValidity();
      return;
    }
    const params = new URLSearchParams({ q: query.value.trim(), top_k: "5" });
    const kind = $("memory-filter").value;
    if (kind) params.set("kind", kind);
    run($("memory-search"), ctx, async () => {
      const data = await request(`/v1/memory/search?${params}`, ctx);
      if (ctx.revision !== revision) return;
      results.replaceChildren();
      for (const hit of data.results) {
        const item = document.createElement("li");
        const text = document.createElement("p");
        const meta = document.createElement("p");
        text.textContent = hit.memory.text;
        meta.className = "memory-result-meta";
        meta.textContent = `${hit.memory.kind} · Score ${Number(hit.score).toFixed(3)} · Importance ${hit.memory.importance}`;
        item.append(text, meta);
        results.append(item);
      }
      feedback.textContent = data.results.length
        ? `${data.results.length} ${data.results.length === 1 ? "note" : "notes"} retrieved, highest score first.`
        : "No notes in this tier for this tenant. Save a note or choose another tier.";
    });
  });
  query.addEventListener("input", () => query.setCustomValidity(""));
})();
