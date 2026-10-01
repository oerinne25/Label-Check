/* Label Check - front end. Plain JavaScript, no build step, no external
   requests: everything is served by the app itself (firewall-friendly). */
"use strict";

const STATUS = {
  pass:   { word: "Matches",        icon: "✓", verdict: "Label matches the application", sub: "Every check passed." },
  review: { word: "Needs review",   icon: "!", verdict: "Needs your review",             sub: "Nothing clearly wrong, but some items need a look." },
  fail:   { word: "Does not match", icon: "✕", verdict: "Label does not match",           sub: "One or more checks failed. See below." },
};
const FIELDS = ["beverage_type", "brand_name", "class_type", "alcohol_content", "net_contents", "bottler", "country_of_origin"];
const MAX_CONCURRENCY = 4;
const RETRY_DELAYS_MS = [3000, 8000]; // for temporary server errors (busy or restarting)
const sleep = ms => new Promise(r => setTimeout(r, ms));
const $ = (sel, root = document) => root.querySelector(sel);

/* ---------------- Tabs ---------------- */
const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(tab) {
  tabs.forEach(t => {
    const on = t === tab;
    t.setAttribute("aria-selected", on);
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
  });
  tab.focus();
}
tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", e => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      selectTab(tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length]);
    }
  });
});

/* ---------------- API ---------------- */
class TemporaryError extends Error {}

/** Check one label, retrying automatically if the server is briefly busy or restarting. */
async function verifyLabel(file, fields, signal) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await verifyOnce(file, fields, signal);
    } catch (err) {
      if (!(err instanceof TemporaryError) || attempt >= RETRY_DELAYS_MS.length) {
        throw err instanceof TemporaryError
          ? new Error("The server was too busy to check this label. Try it again in a minute.")
          : err;
      }
      await sleep(RETRY_DELAYS_MS[attempt]);
      if (signal && signal.aborted) throw new DOMException("Aborted", "AbortError");
    }
  }
}

async function verifyOnce(file, fields, signal) {
  const body = new FormData();
  body.append("image", file, file.name);
  FIELDS.forEach(k => body.append(k, fields[k] || ""));
  let res;
  try {
    res = await fetch("/api/verify", { method: "POST", body, signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new TemporaryError("network");
  }
  if ([502, 503, 504].includes(res.status)) throw new TemporaryError(String(res.status));
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `The server returned an error (${res.status}).`);
  return data;
}

/* ---------------- Result rendering (shared) ---------------- */
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text; // textContent everywhere: OCR text is untrusted
  return node;
}

function renderResult(data) {
  const node = $("#result-template").content.firstElementChild.cloneNode(true);
  const s = STATUS[data.overall];
  node.classList.add(data.overall);
  $(".verdict-icon", node).textContent = s.icon;
  $(".verdict-title", node).textContent = s.verdict;
  $(".verdict-sub", node).textContent = `${s.sub} Checked as: ${data.beverage_label}. Read in ${data.seconds}s.`;

  const notes = $(".notes", node);
  (data.notes || []).forEach(n => notes.append(el("li", "", n)));

  const list = $(".checklist", node);
  data.checks.forEach(c => {
    // Requirement checks (application field blank) read as present/missing, not match/mismatch.
    const presence = c.expected === "(not in application)";
    const word = presence ? { pass: "Present", review: "Check by eye", fail: "Missing" }[c.status]
                          : STATUS[c.status].word;
    const li = el("li", `check ${c.status}`);
    const mark = el("span", "check-mark", STATUS[c.status].icon);
    mark.setAttribute("aria-hidden", "true");
    const head = el("div", "check-head");
    head.append(el("span", "check-name", c.label), el("span", "check-status", word));
    const body = el("div");
    body.append(el("p", "check-message", c.message));
    if (c.field !== "government_warning" && c.expected) {
      const dl = el("dl", "compare");
      if (!presence) dl.append(el("dt", "", "Application"), el("dd", "", c.expected));
      dl.append(el("dt", "", "Label"), el("dd", "", c.found || "Not found"));
      body.append(dl);
    }
    if (c.details && c.details.length) {
      const ul = el("ul", "check-details");
      c.details.forEach(d => ul.append(el("li", "", d)));
      body.append(ul);
    }
    li.append(mark, head, body);
    list.append(li);
  });
  $(".ocr-text pre", node).textContent = data.ocr_text || "(no text found)";
  return node;
}

/* ---------------- Single label ---------------- */
const form = $("#single-form");
const imageInput = $("#image-input");
const dropzone = $("#dropzone");
const preview = $("#preview");
const singleError = $("#single-error");
const singleResult = $("#single-result");
const checkBtn = $("#check-btn");
let chosenFile = null;

function setImage(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    showSingleError(`"${file.name}" isn't an image. Choose a JPG, PNG, or WebP file.`);
    return;
  }
  chosenFile = file;
  preview.src = URL.createObjectURL(file);
  preview.alt = `Label image: ${file.name}`;
  preview.hidden = false;
  $("#drop-text").hidden = true;
  singleError.hidden = true;
}

function showSingleError(msg) {
  singleError.textContent = msg;
  singleError.hidden = false;
}

imageInput.addEventListener("change", () => setImage(imageInput.files[0]));
["dragenter", "dragover"].forEach(ev => dropzone.addEventListener(ev, e => {
  e.preventDefault(); dropzone.classList.add("dragging");
}));
["dragleave", "drop"].forEach(ev => dropzone.addEventListener(ev, e => {
  e.preventDefault(); dropzone.classList.remove("dragging");
}));
dropzone.addEventListener("drop", e => setImage(e.dataTransfer.files[0]));

form.addEventListener("reset", () => {
  chosenFile = null;
  preview.hidden = true;
  $("#drop-text").hidden = false;
  singleError.hidden = true;
  singleResult.replaceChildren();
});

form.addEventListener("submit", async e => {
  e.preventDefault();
  singleError.hidden = true;
  const fields = Object.fromEntries(FIELDS.map(k => [k, (form.elements[k].value || "").trim()]));
  if (!chosenFile) return showSingleError("Add a label image first.");
  if (!fields.brand_name && !fields.class_type && !fields.alcohol_content && !fields.net_contents) {
    form.elements.brand_name.focus();
    return showSingleError("Enter at least one value from the application, such as the brand name.");
  }
  checkBtn.disabled = true;
  checkBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Checking…';
  singleResult.replaceChildren();
  try {
    const data = await verifyLabel(chosenFile, fields);
    singleResult.replaceChildren(renderResult(data));
    singleResult.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showSingleError(err.message);
  } finally {
    checkBtn.disabled = false;
    checkBtn.textContent = "Check label";
  }
});

$("#load-example").addEventListener("click", async () => {
  try {
    const res = await fetch("/samples/01_old_tom_compliant.png");
    if (!res.ok) throw new Error();
    const blob = await res.blob();
    setImage(new File([blob], "01_old_tom_compliant.png", { type: "image/png" }));
    Object.entries({
      brand_name: "OLD TOM DISTILLERY", class_type: "Kentucky Straight Bourbon Whiskey",
      alcohol_content: "45% Alc./Vol. (90 Proof)", net_contents: "750 mL",
    }).forEach(([k, v]) => { form.elements[k].value = v; });
    form.querySelector('input[name="beverage_type"][value="spirits"]').checked = true;
    checkBtn.focus();
  } catch {
    showSingleError("The example label isn't available on this server.");
  }
});

/* ---------------- Batch ---------------- */
const batch = { images: new Map(), rows: new Map(), results: [], controller: null, filter: "all" };
const batchRun = $("#batch-run");
const batchError = $("#batch-error");

/** Minimal RFC 4180 CSV parser (quoted fields, commas and newlines inside quotes). */
function parseCSV(text) {
  const rows = []; let row = [], field = "", quoted = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += ch;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows.filter(r => r.some(c => c.trim()));
}

function updateBatchReady() {
  batchRun.disabled = !(batch.images.size && batch.rows.size);
  const matched = [...batch.images.keys()].filter(k => batch.rows.has(k)).length;
  batchRun.textContent = batch.images.size ? `Check ${batch.images.size} label${batch.images.size === 1 ? "" : "s"}` : "Check labels";
  batchError.hidden = true;
  if (batch.images.size && batch.rows.size && matched < batch.images.size) {
    batchError.textContent = `${batch.images.size - matched} image(s) have no matching row in the CSV. They'll be listed so you can check them by hand.`;
    batchError.hidden = false;
  }
}

$("#batch-images").addEventListener("change", e => {
  batch.images.clear();
  [...e.target.files].filter(f => f.type.startsWith("image/"))
    .forEach(f => batch.images.set(f.name.toLowerCase(), f));
  const status = $("#batch-images-status");
  status.textContent = batch.images.size ? `${batch.images.size} image${batch.images.size === 1 ? "" : "s"} chosen.` : "No images chosen.";
  status.classList.toggle("ok", batch.images.size > 0);
  updateBatchReady();
});

$("#batch-csv").addEventListener("change", async e => {
  const file = e.target.files[0];
  const status = $("#batch-csv-status");
  batch.rows.clear();
  if (!file) return updateBatchReady();
  const rows = parseCSV(await file.text());
  const header = (rows.shift() || []).map(h => h.trim().toLowerCase().replace(/[\s/]+/g, "_"));
  if (!header.includes("filename")) {
    status.textContent = 'This CSV needs a "filename" column. Download the template to see the layout.';
    status.classList.remove("ok");
    return updateBatchReady();
  }
  rows.forEach(r => {
    const rec = Object.fromEntries(header.map((h, i) => [h, (r[i] || "").trim()]));
    if (rec.filename) batch.rows.set(rec.filename.toLowerCase(), rec);
  });
  status.textContent = `${batch.rows.size} application row${batch.rows.size === 1 ? "" : "s"} loaded from ${file.name}.`;
  status.classList.add("ok");
  updateBatchReady();
});

function pill(status) {
  const s = STATUS[status];
  const span = el("span", `pill ${status}`);
  span.append(el("span", "", s ? s.icon : "…"), el("span", "", s ? s.word : status));
  return span;
}

function summarise(r) {
  if (r.error) return r.error;
  const issues = r.data.checks.filter(c => c.status !== "pass").map(c => `${c.label}: ${c.message}`);
  return issues.length ? issues.join(" ") : "All checks passed.";
}

function renderBatchTable() {
  const tbody = $("#batch-tbody");
  tbody.replaceChildren();
  const counts = { all: 0, pass: 0, review: 0, fail: 0 };
  batch.results.forEach(r => {
    if (r.status in counts) counts[r.status]++;
    if (r.status !== "pending") counts.all++;
    if (batch.filter !== "all" && r.status !== batch.filter) return;
    const tr = el("tr", "row");
    tr.tabIndex = 0;
    tr.setAttribute("aria-expanded", r.open ? "true" : "false");
    const tdPill = el("td"); tdPill.append(pill(r.status));
    tr.append(el("td", "filename", r.name), tdPill, el("td", "", r.status === "pending" ? "" : summarise(r)));
    const toggle = () => { if (r.data) { r.open = !r.open; renderBatchTable(); } };
    tr.addEventListener("click", toggle);
    tr.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    tbody.append(tr);
    if (r.open && r.data) {
      const detail = el("tr", "detail");
      const td = el("td"); td.colSpan = 3; td.append(renderResult(r.data));
      detail.append(td); tbody.append(detail);
    }
  });
  Object.entries(counts).forEach(([k, v]) => { $(`[data-count="${k}"]`).textContent = v; });
}

document.querySelectorAll(".filter").forEach(btn => btn.addEventListener("click", () => {
  batch.filter = btn.dataset.filter;
  document.querySelectorAll(".filter").forEach(b => b.setAttribute("aria-pressed", b === btn));
  renderBatchTable();
}));

batchRun.addEventListener("click", async () => {
  batch.controller = new AbortController();
  const signal = batch.controller.signal;
  // Fails and reviews float to the top as they arrive; order within a status is by file name.
  batch.results = [...batch.images.values()].sort((a, b) => a.name.localeCompare(b.name))
    .map(file => ({ name: file.name, file, row: batch.rows.get(file.name.toLowerCase()), status: "pending" }));
  $("#batch-results").hidden = false;
  $("#batch-progress").hidden = false;
  $("#batch-stop").hidden = false;
  batchRun.disabled = true;

  let done = 0;
  const total = batch.results.length;
  const progress = () => {
    $("#batch-progress-text").textContent = done < total ? `Checked ${done} of ${total}…` : `Finished: ${total} label${total === 1 ? "" : "s"} checked.`;
    $("#batch-bar").style.width = `${(done / total) * 100}%`;
  };
  progress();
  renderBatchTable();

  const queue = [...batch.results];
  async function worker() {
    while (queue.length && !signal.aborted) {
      const r = queue.shift();
      if (!r.row) {
        r.status = "review"; r.error = "No row for this file in the CSV. Check by hand.";
      } else {
        try {
          r.data = await verifyLabel(r.file, r.row, signal);
          r.status = r.data.overall;
        } catch (err) {
          if (err.name === "AbortError") { r.status = "pending"; return; }
          r.status = "review"; r.error = `Couldn't check this label: ${err.message}`;
        }
      }
      done++;
      progress();
      const order = { fail: 0, review: 1, pass: 2, pending: 3 };
      batch.results.sort((a, b) => order[a.status] - order[b.status] || a.name.localeCompare(b.name));
      renderBatchTable();
    }
  }
  // Send only as many labels at once as the server has workers (plus one waiting),
  // so a small server isn't flooded with requests it can't answer in time.
  let concurrency = 2;
  try {
    const h = await (await fetch("/health", { signal })).json();
    concurrency = Math.min(MAX_CONCURRENCY, (h.workers || 1) + 1);
  } catch { /* keep the default */ }
  await Promise.all(Array.from({ length: concurrency }, worker));
  if (signal.aborted) $("#batch-progress-text").textContent = `Stopped after ${done} of ${total}.`;
  $("#batch-stop").hidden = true;
  batchRun.disabled = false;
});

$("#batch-stop").addEventListener("click", () => batch.controller && batch.controller.abort());

$("#batch-download").addEventListener("click", () => {
  const esc = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [["filename", "result", "details"].join(",")];
  batch.results.filter(r => r.status !== "pending").forEach(r => {
    lines.push([r.name, STATUS[r.status] ? STATUS[r.status].word : r.status, summarise(r)].map(esc).join(","));
  });
  const url = URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: "label-check-results.csv" });
  a.click();
  URL.revokeObjectURL(url);
});
