"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const el = {
    prompt: $("prompt"), maxTokens: $("max-tokens"), speed: $("speed"), pause: $("pause"),
    start: $("start"), drop: $("drop"), resume: $("resume"), cancel: $("cancel"),
    error: $("error"), state: $("state"), output: $("output"), verdict: $("verdict"),
    last: $("stat-last"), resumes: $("stat-resumes"), beats: $("stat-beats"), expiry: $("stat-expiry"),
    train: $("train"), labError: $("lab-error"), labResult: $("lab-result"), labAnswer: $("lab-answer"), useModel: $("use-model"),
    labBase: $("lab-base"), labPrompt: $("lab-prompt"), labTuned: $("lab-tuned"), labDelta: $("lab-delta"), labModel: $("lab-model"), labCkpt: $("lab-ckpt"),
    log: $("log"), clear: $("clear-log"), dot: $("health-dot"), healthText: $("health-text"),
  };
  const STORE_KEY = "modellab.stream";
  const TERMINAL = ["done", "cancelled"];

  // Everything the page knows about the current stream. Token text is rebuilt from `tokens`
  // only, so a reconnect can never double-append or reorder it.
  let s = null;
  let tick = null;
  let labModelId = null;

  const fresh = (id) => ({
    id, es: null, lastId: 0, tokens: [], resumes: 0, beats: 0, status: "running",
    terminal: null, expiresAt: null, intact: true, dropped: false, ending: false,
  });

  // ---------------------------------------------------------------- ui helpers
  function log(kind, text) {
    const li = document.createElement("li");
    const t = document.createElement("span"); t.className = "t"; t.textContent = new Date().toLocaleTimeString([], { hour12: false });
    const k = document.createElement("span"); k.className = "k"; k.dataset.kind = kind; k.textContent = kind;
    const m = document.createElement("span"); m.textContent = text;
    li.append(t, k, m);
    el.log.prepend(li);
    while (el.log.children.length > 200) el.log.lastChild.remove();
  }

  function setState(state, label) {
    el.state.dataset.state = state;
    el.state.textContent = label;
  }

  function showError(message) {
    el.error.hidden = !message;
    el.error.textContent = message || "";
  }

  function renderOutput() {
    el.output.replaceChildren();
    if (!s || !s.tokens.length) {
      const p = document.createElement("span");
      p.className = "placeholder";
      p.textContent = s && s.status === "running" ? "Waiting for the first token…" : "Start a stream to see tokens arrive.";
      el.output.append(p);
    } else {
      el.output.append(document.createTextNode(s.tokens.join("")));
    }
    if (s && s.status === "running" && s.es) {
      const c = document.createElement("span"); c.className = "cursor"; el.output.append(c);
    }
    el.output.scrollTop = el.output.scrollHeight;
  }

  function renderStats() {
    el.last.textContent = s ? String(s.lastId) : "0";
    el.resumes.textContent = s ? String(s.resumes) : "0";
    el.beats.textContent = s ? String(s.beats) : "0";
    if (!s || s.expiresAt === null) { el.expiry.textContent = "—"; return; }
    const left = Math.max(0, Math.round((s.expiresAt - Date.now()) / 1000));
    el.expiry.textContent = left > 0 ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "expired";
  }

  function renderButtons() {
    const running = !!s && s.status === "running";
    const connected = !!s && !!s.es;
    el.drop.disabled = !(running && connected);
    el.resume.disabled = !(s && !connected && !s.terminal && s.status !== "expired" && s.status !== "error");
    el.cancel.disabled = !running;
  }

  function verdict(ok, text) {
    el.verdict.hidden = !text;
    el.verdict.dataset.ok = String(ok);
    el.verdict.textContent = text || "";
  }

  function refresh() { renderOutput(); renderStats(); renderButtons(); }

  // ----------------------------------------------------------------- transport
  async function api(path, options) {
    const r = await fetch(path, options);
    let body = null;
    try { body = await r.json(); } catch { /* 204 or non-JSON */ }
    return { status: r.status, ok: r.ok, body };
  }

  function disconnect() {
    if (s && s.es) { s.es.close(); s.es = null; }
  }

  // Connect (or reconnect) from the last id we have *actually applied*. The query form is
  // used for manual resumes; EventSource's own automatic retries send Last-Event-ID instead.
  function connect(reason) {
    if (!s || s.es || s.terminal) return;
    const url = `/v1/streams/${encodeURIComponent(s.id)}/events` + (s.lastId > 0 ? `?last_event_id=${s.lastId}` : "");
    if (reason === "resume") { s.resumes += 1; log("resume", `reconnecting after id ${s.lastId}`); }
    s.dropped = false;
    setState("reconnecting", reason === "resume" ? "Resuming…" : "Connecting…");
    const es = new EventSource(url);
    s.es = es;
    const mine = s;

    es.addEventListener("ready", (e) => {
      if (s !== mine) return;
      const d = JSON.parse(e.data);
      setState("live", "Live");
      log("ready", d.resumed_after ? `server replaying from id ${d.resumed_after + 1}` : "connected, from the start");
      refresh();
    });

    es.addEventListener("token", (e) => {
      if (s !== mine) return;
      const id = Number(e.lastEventId);
      if (id <= mine.lastId) { log("dup", `ignored already-applied id ${id}`); return; }
      if (id !== mine.lastId + 1) {
        mine.intact = false;
        log("gap", `expected id ${mine.lastId + 1}, got ${id}`);
      }
      mine.lastId = id;
      mine.tokens.push(JSON.parse(e.data).token);
      renderOutput(); renderStats();
    });

    es.addEventListener("heartbeat", (e) => {
      if (s !== mine) return;
      mine.beats += 1;
      const d = JSON.parse(e.data);
      log("heartbeat", `idle link alive; server is at id ${d.last_id}`);
      renderStats();
    });

    es.addEventListener("shutdown", () => {
      // Server is restarting. EventSource will retry by itself and send Last-Event-ID.
      if (s === mine) log("reconnect", `server is shutting down; will resume after id ${mine.lastId}`);
    });

    for (const kind of TERMINAL) {
      es.addEventListener(kind, (e) => { if (s === mine) finish(kind, Number(e.lastEventId), JSON.parse(e.data)); });
    }

    es.onerror = () => {
      if (s !== mine) return;
      if (es.readyState === EventSource.CONNECTING) {
        // Network-level failure: the browser retries by itself, sending Last-Event-ID.
        setState("reconnecting", "Reconnecting…");
        log("reconnect", `connection lost at id ${mine.lastId}; browser will retry with Last-Event-ID`);
        return;
      }
      // The server answered with an error status and EventSource gave up.
      es.close(); mine.es = null;
      diagnose();
    };
    refresh();
  }

  // After a hard failure, ask the status endpoint why, so the message is accurate.
  async function diagnose() {
    const mine = s;
    const r = await api(`/v1/streams/${encodeURIComponent(mine.id)}`);
    if (s !== mine) return;
    if (r.status === 410) {
      mine.status = "expired"; sessionStorage.removeItem(STORE_KEY);
      setState("expired", "Expired");
      log("expired", "the server dropped this stream; replay is no longer possible");
      showError("This stream expired. Stored streams are only kept for a limited time after they finish. Start a new one.");
    } else if (r.status === 404) {
      mine.status = "error"; sessionStorage.removeItem(STORE_KEY);
      setState("error", "Not found");
      log("error", "stream not found (the server may have restarted)");
      showError("The server does not know this stream. It may have restarted; streams are kept in memory.");
    } else if (r.ok && TERMINAL.includes(r.body.status) && mine.lastId >= r.body.last_event_id) {
      mine.status = r.body.status; setState(r.body.status, r.body.status === "done" ? "Done" : "Cancelled");
    } else {
      mine.status = "running";
      setState("dropped", "Disconnected");
      log("error", `connection refused (status ${r.status}); press Resume to retry`);
    }
    refresh();
  }

  async function finish(kind, id, data) {
    const mine = s;
    mine.lastId = id;
    mine.terminal = kind; mine.status = kind;
    if (mine.es) { mine.es.close(); mine.es = null; }
    setState(kind, kind === "done" ? "Done" : "Cancelled");
    log(kind, `${data.total_tokens} tokens`);

    // Resume correctness check, client side: nothing missing, nothing doubled, same bytes.
    const text = mine.tokens.join("");
    let hashOk = null;
    if (window.crypto && crypto.subtle) {
      const bytes = new TextEncoder().encode(text);
      const hex = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
      hashOk = hex === data.sha256;
    }
    if (s !== mine) return;
    const countOk = mine.tokens.length === data.total_tokens && mine.intact;
    const ok = countOk && hashOk !== false;
    const resumed = mine.resumes ? ` across ${mine.resumes} resume${mine.resumes === 1 ? "" : "s"}` : "";
    verdict(ok, ok
      ? `Verified${resumed}: ${data.total_tokens} tokens, contiguous ids, ${hashOk ? "SHA-256 matches the server" : "checksum skipped (needs HTTPS or localhost)"}.`
      : `Mismatch: got ${mine.tokens.length} tokens, server sent ${data.total_tokens}${hashOk === false ? ", checksum differs" : ""}.`);
    const st = await api(`/v1/streams/${encodeURIComponent(mine.id)}`);
    if (s === mine && st.ok && st.body.expires_in_seconds != null) {
      mine.expiresAt = Date.now() + st.body.expires_in_seconds * 1000;
      log("expiry", `replay kept for ${Math.round(st.body.expires_in_seconds)} s`);
    }
    refresh();
  }

  // --------------------------------------------------------------- model lab
  const SAMPLE = [
    ["capital of France", "Paris"], ["capital of Japan", "Tokyo"], ["capital of Italy", "Rome"], ["capital of Spain", "Madrid"],
    ["capital of Egypt", "Cairo"], ["capital of Kenya", "Nairobi"], ["capital of Peru", "Lima"], ["capital of Norway", "Oslo"],
    ["capital of Canada", "Ottawa"], ["capital of India", "New Delhi"], ["capital of Chile", "Santiago"], ["capital of Ghana", "Accra"],
    ["capital of Poland", "Warsaw"], ["capital of Cuba", "Havana"], ["capital of Nepal", "Kathmandu"], ["capital of Iraq", "Baghdad"],
    ["capital of Greece", "Athens"], ["capital of Qatar", "Doha"], ["capital of Laos", "Vientiane"], ["capital of Fiji", "Suva"],
  ].map(([input, output]) => ({ input, output }));

  const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const pct = (n) => `${Math.round(n * 100)}%`;
  const detail = (r) => (r.body && (Array.isArray(r.body.detail) ? r.body.detail.map((d) => d.message).join("; ") : r.body.detail)) || `HTTP ${r.status}`;

  async function trainSample() {
    el.labError.hidden = true;
    el.train.disabled = true;
    el.train.textContent = "Training…";
    try {
      const ds = await post("/v1/datasets", { name: "sample-capitals", records: SAMPLE });
      if (!ds.ok) throw new Error(`dataset: ${detail(ds)}`);
      const tr = await post("/v1/training/run", { dataset_id: ds.body.dataset_id, lora_r: 8, lora_alpha: 16 });
      if (!tr.ok) throw new Error(`training: ${detail(tr)}`);
      const ev = await post(`/v1/models/${encodeURIComponent(tr.body.model_id)}/evaluate`, {});
      if (!ev.ok) throw new Error(`evaluation: ${detail(ev)}`);
      const model = await api(`/v1/models/${encodeURIComponent(tr.body.model_id)}`);
      const e = ev.body;
      labModelId = tr.body.model_id;
      el.labAnswer.textContent = e.answer;
      el.labAnswer.dataset.ok = String(e.justified);
      el.labBase.textContent = pct(e.base);
      el.labPrompt.textContent = pct(e.prompt_engineered);
      el.labTuned.textContent = pct(e.fine_tuned);
      el.labDelta.textContent = `${e.delta_vs_base >= 0 ? "+" : ""}${Math.round(e.delta_vs_base * 100)} pts`;
      el.labModel.textContent = labModelId;
      el.labCkpt.textContent = model.ok ? `${model.body.checkpoints.length} checkpoints, final loss ${model.body.checkpoints.at(-1).loss}` : "";
      el.labResult.hidden = false;
      log("lab", `${labModelId}: tuned ${pct(e.fine_tuned)} vs base ${pct(e.base)}`);
    } catch (err) {
      el.labError.hidden = false;
      el.labError.textContent = `Could not run the pipeline: ${err.message}`;
    } finally {
      el.train.disabled = false;
      el.train.textContent = "Train sample model";
    }
  }

  // ------------------------------------------------------------------- actions
  async function start() {
    showError("");
    const prompt = el.prompt.value.trim();
    const maxTokens = Number(el.maxTokens.value);
    if (!prompt) return showError("Enter a prompt first.");
    if (!Number.isInteger(maxTokens) || maxTokens < 1 || maxTokens > 512) return showError("Tokens must be a whole number from 1 to 512.");
    disconnect();
    el.start.disabled = true;
    const r = await api("/v1/streams", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt, max_tokens: maxTokens, token_delay_ms: Number(el.speed.value), first_token_delay_ms: Number(el.pause.value),
        ...(labModelId && el.useModel.checked ? { model_id: labModelId } : {}),
      }),
    });
    el.start.disabled = false;
    if (!r.ok) {
      const detail = Array.isArray(r.body && r.body.detail) ? r.body.detail.map((d) => `${d.path}: ${d.message}`).join("; ") : (r.body && r.body.detail) || `HTTP ${r.status}`;
      return showError(`Could not start the stream: ${detail}`);
    }
    s = fresh(r.body.stream_id);
    sessionStorage.setItem(STORE_KEY, s.id);
    verdict(true, "");
    log("start", `stream ${s.id.slice(0, 8)}…; ${r.body.max_tokens} simulated tokens${r.body.model_id ? ` seeded by ${r.body.model_id}` : ""}`);
    connect("start");
    refresh();
  }

  function drop() {
    if (!s || !s.es) return;
    disconnect();
    s.dropped = true;
    setState("dropped", "Disconnected");
    log("drop", `closed the socket at id ${s.lastId}; the server keeps generating`);
    refresh();
  }

  async function cancel() {
    if (!s) return;
    const mine = s;
    const r = await api(`/v1/streams/${encodeURIComponent(mine.id)}/cancel`, { method: "POST" });
    if (s !== mine) return;
    if (!r.ok) return diagnose();
    // The cancelled event is in the stream; reconnect to receive it and finish cleanly.
    if (!mine.es) connect("resume");
  }

  // After a page reload, pick the stream back up from id 0: this *is* a resume.
  async function restore() {
    const id = sessionStorage.getItem(STORE_KEY);
    if (!id) return;
    const r = await api(`/v1/streams/${encodeURIComponent(id)}`);
    s = fresh(id);
    if (!r.ok) { diagnose(); log("restore", `previous stream is gone (status ${r.status})`); return; }
    log("restore", "page reloaded; replaying the stored stream from the start");
    connect("start");
    refresh();
  }

  async function health() {
    try {
      const r = await fetch("/health");
      const ok = r.ok;
      el.dot.dataset.ok = String(ok);
      el.healthText.textContent = ok ? "Service healthy · simulated tokens" : "Service unavailable";
    } catch {
      el.dot.dataset.ok = "false";
      el.healthText.textContent = "Service unreachable";
    }
  }

  el.start.addEventListener("click", start);
  el.drop.addEventListener("click", drop);
  el.resume.addEventListener("click", () => { showError(""); connect("resume"); });
  el.cancel.addEventListener("click", cancel);
  el.train.addEventListener("click", trainSample);
  el.clear.addEventListener("click", () => el.log.replaceChildren());
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); start(); }
  });
  window.addEventListener("pagehide", disconnect);

  tick = setInterval(() => {
    if (!s || s.expiresAt === null) return;
    renderStats();
    if (Date.now() >= s.expiresAt && s.status !== "expired") {
      s.status = "expired";
      setState("expired", "Expired");
      log("expired", "retention window ended; the server will answer 410 Gone");
      renderButtons();
    }
  }, 1000);

  health();
  refresh();
  restore();
})();
