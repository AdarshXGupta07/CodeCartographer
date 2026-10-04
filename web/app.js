/* CodeCartographer web UI: streams the agent trace (SSE) and renders verified results. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
const SYS_COLORS = { bm25: "#64748b", dense: "#a78bfa", hybrid: "#3b82f6", agent: "#22d3ee", "agent+llm": "#34d399" };

let STATUS = null;
let source = null;
let cy = null, exCy = null;

/* ------------------------------------------------------------------ tabs */
$$(".tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));
function showView(v) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === v));
  $$(".view").forEach((s) => s.classList.toggle("active", s.id === `view-${v}`));
  if (v === "eval") loadEval();
  if (v === "findings") loadFindings();
  if (v === "explore") loadTree();
  if (v === "ask" && cy) setTimeout(() => cy.resize().fit(undefined, 30), 50);
}

/* ---------------------------------------------------------------- status */
async function loadStatus() {
  STATUS = await (await fetch("/api/status")).json();
  const s = STATUS.meta?.stats;
  $("#repoPill").textContent = s ? `${STATUS.repo} · ${s.files} files · ${s.functions} functions · ${s.tools} tools` : "no repo indexed";
  $("#llmPill").textContent = STATUS.llm_available ? `LLM: ${STATUS.llm}` : "offline planner";
  $("#llmPill").classList.toggle("on", STATUS.llm_available);
  $("#llmToggle").checked = STATUS.llm_available;
  $("#llmToggle").disabled = !STATUS.llm_available;
  $("#llmToggleWrap").title = STATUS.llm_available ? "Let the LLM refine the answer" : "Set GEMINI_API_KEY / GROQ_API_KEY / OPENAI_API_KEY to enable";
  $("#chips").innerHTML = STATUS.examples.map((e) => `<button class="chip" data-q="${esc(e.q)}"><i>${e.type}</i>${esc(e.q)}</button>`).join("");
  $$("#chips .chip").forEach((c) => c.addEventListener("click", () => { $("#q").value = c.dataset.q; ask(); }));
}

/* ------------------------------------------------------------------- ask */
$("#askForm").addEventListener("submit", (e) => { e.preventDefault(); ask(); });

function ask() {
  const q = $("#q").value.trim();
  if (!q) return;
  if (source) source.close();
  $("#hero").hidden = true;
  $("#trace").innerHTML = "";
  $("#locations").innerHTML = "";
  $("#answerPanel").hidden = true;
  $("#graphPanel").hidden = true;
  $("#optPanel").hidden = true;
  $("#traceMeta").innerHTML = '<span class="spinner"></span>';
  $("#askBtn").disabled = true;
  const started = performance.now();
  source = new EventSource(`/api/ask?q=${encodeURIComponent(q)}&llm=${$("#llmToggle").checked}`);
  source.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "done") { source.close(); $("#askBtn").disabled = false; $("#traceMeta").textContent = `${Math.round(performance.now() - started)} ms`; return; }
    onEvent(ev);
  };
  source.onerror = () => { source.close(); $("#askBtn").disabled = false; $("#traceMeta").textContent = "connection closed"; };
}

function traceItem(cls, html) {
  const li = document.createElement("li");
  li.className = cls;
  li.innerHTML = html;
  $("#trace").appendChild(li);
  li.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return li;
}

function onEvent(ev) {
  switch (ev.type) {
    case "plan":
      traceItem("plan", `<div class="t-title">Plan <span class="muted">· ${esc(ev.planner)}</span></div><div class="t-thought">${esc(ev.text)}</div>`);
      break;
    case "rewrite":
      traceItem("plan", `<div class="t-title">Rewrite</div><div class="t-args">${esc(ev.text.replace("Query rewrites: ", ""))}</div>`);
      break;
    case "thinking":
      traceItem("plan", `<div class="t-title">Reason</div><div class="t-thought">${esc(ev.text)}</div>`);
      break;
    case "step":
      traceItem("", `<div class="t-title">Step ${ev.n} <span class="t-tool">${esc(ev.tool)}</span><span class="t-ms" id="ms-${ev.n}"></span></div>
        <div class="t-thought">${esc(ev.thought)}</div><div class="t-args">${esc(JSON.stringify(ev.args))}</div><div class="t-obs" id="obs-${ev.n}"><span class="spinner"></span></div>`);
      break;
    case "observation": {
      const o = $(`#obs-${ev.n}`);
      if (o) o.textContent = ev.preview + (ev.lines > 12 ? `\n… ${ev.lines - 12} more lines` : "");
      const ms = $(`#ms-${ev.n}`);
      if (ms) ms.textContent = `${ev.ms} ms`;
      break;
    }
    case "llm_answer":
      traceItem("plan", `<div class="t-title">LLM answer</div><div class="t-thought">${esc(ev.thought || "")}</div>`);
      break;
    case "verify":
      traceItem("verify", `<div class="t-title">Verify</div><div class="t-thought">${esc(ev.text)}</div>`);
      break;
    case "warning":
      traceItem("warn", `<div class="t-title">Warning</div><div class="t-thought">${esc(ev.text)}</div>`);
      break;
    case "error":
      traceItem("warn", `<div class="t-title">Error</div><div class="t-thought">${esc(ev.text)}</div>`);
      break;
    case "final":
      renderFinal(ev);
      break;
  }
}

function renderFinal(ev) {
  $("#answerPanel").hidden = false;
  $("#qtype").textContent = ev.query_type;
  const m = ev.metrics;
  $("#answerMeta").textContent = `${m.latency_ms} ms · ${m.tool_calls} tool calls · ${ev.locations.length} verified locations · ${m.planner}`;
  $("#answerText").innerHTML = md(ev.answer || "");
  $("#locations").innerHTML = ev.locations.map((l, i) => locCard(l, i + 1)).join("");
  hljsAll($("#locations"));
  placeHighlights($("#locations"));
  if (ev.optimizations?.length) {
    $("#optPanel").hidden = false;
    $("#opts").innerHTML = ev.optimizations.map(optRow).join("");
  }
  if (ev.graph?.nodes?.length) {
    $("#graphPanel").hidden = false;
    cy = drawGraph("#graph", ev.graph, cy);
  }
}

function locCard(l, rank) {
  const badge = l.related ? `<span class="badge rel">call-path context</span>` : `<span class="badge ok">✓ verified</span>`;
  return `<div class="loc">
    <div class="loc-head"><span class="loc-rank">${rank}</span><span class="loc-file">${esc(l.file)}:${l.start}-${l.end}</span>
      <span class="loc-sym">${esc(l.symbol || "")}</span>${badge}<div class="loc-why">${md(l.why || "")}</div></div>
    ${codeBlock(l.code, l.start, l.highlight || [])}</div>`;
}

function codeBlock(code, start, hl) {
  const lines = (code || "").split("\n");
  const gutter = lines.map((_, i) => `<div class="${hl.includes(start + i) ? "hl" : ""}">${start + i}</div>`).join("");
  const bars = hl.filter((n) => n >= start && n < start + lines.length).map((n) => `<div class="hlbar" data-off="${n - start}"></div>`).join("");
  return `<div class="code"><div class="gutter">${gutter}</div><pre>${bars}<code class="language-javascript">${esc(code)}</code></pre></div>`;
}

function hljsAll(root) {
  if (!window.hljs) return;
  $$("pre code", root).forEach((c) => hljs.highlightElement(c));
}
function placeHighlights(root) {
  $$(".hlbar", root).forEach((b) => { b.style.top = `${8 + 20 * Number(b.dataset.off)}px`; });
}

function optRow(o) {
  return `<div class="opt"><span class="sev ${o.severity}">${o.severity}</span>
    <div><span class="o-title">${esc(o.title)}</span> <span class="o-loc">${esc(o.file)}:${o.line}</span> <span class="muted">in ${esc(o.function || "")}</span></div>
    <div class="o-code">${esc(o.code)}</div><div class="o-sugg">${esc(o.suggestion)}</div></div>`;
}

/* ----------------------------------------------------------------- graph */
function drawGraph(sel, g, prev) {
  if (!window.cytoscape) { $(sel).innerHTML = '<p class="muted" style="padding:12px">graph library unavailable offline</p>'; return null; }
  if (prev) prev.destroy();
  const els = [
    ...g.nodes.map((n) => ({ data: { id: n.id, label: n.label.replace(/^tool:/, "⚙ "), kind: n.kind, focus: n.focus ? 1 : 0, file: n.file, line: n.line } })),
    ...g.edges.map((e, i) => ({ data: { id: "e" + i, source: e.source, target: e.target, label: e.label && e.label !== e.target ? e.label : "" } })),
  ];
  const c = cytoscape({
    container: $(sel),
    elements: els,
    wheelSensitivity: 0.25,
    style: [
      { selector: "node", style: { "background-color": "#22d3ee", label: "data(label)", color: "#cbd5e1", "font-size": 10, "text-valign": "bottom", "text-margin-y": 4, width: 14, height: 14, "font-family": "JetBrains Mono", "text-background-color": "#0b1020", "text-background-opacity": 0.85, "text-background-padding": 2, "text-background-shape": "roundrectangle" } },
      { selector: 'node[kind = "function"], node[kind = "arrow"]', style: { "background-color": "#a78bfa" } },
      { selector: 'node[kind = "tool_handler"]', style: { "background-color": "#f59e0b", shape: "round-diamond" } },
      { selector: "node[focus = 1]", style: { width: 24, height: 24, "border-width": 3, "border-color": "#34d399", color: "#fff", "font-size": 11, "font-weight": 600 } },
      { selector: "edge", style: { width: 1.3, "line-color": "#334155", "target-arrow-color": "#475569", "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.8 } },
    ],
    layout: g.nodes.length <= 18
      ? { name: "breadthfirst", directed: true, spacingFactor: 1.15, padding: 24, avoidOverlap: true, nodeDimensionsIncludeLabels: true }
      : { name: "cose", animate: false, nodeRepulsion: 60000, idealEdgeLength: 120, nodeOverlap: 40, padding: 30, nodeDimensionsIncludeLabels: true },
  });
  c.on("tap", "node", (e) => { const d = e.target.data(); if (d.file) openCode(d.file, d.line); });
  return c;
}

async function openCode(file, line) {
  const f = await (await fetch(`/api/file?path=${encodeURIComponent(file)}&start=${Math.max(1, line - 2)}&end=${line + 30}`)).json();
  const host = $("#view-explore").classList.contains("active") ? $("#exCode") : $("#locations");
  const div = document.createElement("div");
  div.className = "loc";
  div.innerHTML = `<div class="loc-head"><span class="loc-rank">↗</span><span class="loc-file">${esc(file)}:${f.start}-${f.end}</span><span class="badge rel">opened from graph</span></div>${codeBlock(f.code, f.start, [line])}`;
  host.prepend(div);
  hljsAll(div); placeHighlights(div);
  div.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ------------------------------------------------------------------ eval */
let evalLoaded = false;
async function loadEval() {
  if (evalLoaded) return;
  const r = await fetch("/api/eval");
  if (!r.ok) { $("#kpis").innerHTML = '<p class="muted">Run <code>python -m eval.run_eval</code> to generate results.</p>'; return; }
  const R = await r.json();
  evalLoaded = true;
  const S = R.summary, A = S.agent.all, B = S.bm25.all, H = S.hybrid.all;
  const pct = (x) => `${Math.round(x * 100)}%`;
  const kpis = [
    ["Recall@5", pct(A["R@5"]), `+${Math.round((A["R@5"] - B["R@5"]) * 100)} pts vs BM25`],
    ["MRR", A.MRR.toFixed(2), `vs ${H.MRR.toFixed(2)} hybrid`],
    ["Precision@1", pct(A["P@1"]), `vs ${pct(B["P@1"])} BM25`],
    ["Answer precision", pct(A.set_P), `${(A.set_P / B.set_P).toFixed(1)}× less noise`],
    ["Agent p50 latency", `${Math.round(A.latency_p50_ms)} ms`, "CPU only"],
    ["Structural recall", pct(S.agent.structural["R@5"]), "graph-based"],
  ];
  $("#kpis").innerHTML = kpis.map(([l, v, d]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join("");

  const systems = Object.keys(S);
  const metrics = [["P@1", "P@1"], ["R@5", "R@5"], ["MRR", "MRR"], ["set_P", "Ans. prec."]];
  $("#bars").innerHTML = `<div class="sys-legend">${systems.map((s) => `<span><i style="background:${SYS_COLORS[s] || "#999"}"></i>${s}</span>`).join("")}</div>` +
    metrics.map(([k, lbl]) => `<div class="barrow"><div class="lbl">${lbl}</div><div class="bargroup">${systems.map((s) =>
      `<div class="bar" style="width:${Math.max(1, S[s].all[k] * 85)}%;background:${SYS_COLORS[s] || "#999"}"><span>${S[s].all[k].toFixed(2)}</span></div>`).join("")}</div></div>`).join("");

  const types = Object.keys(S.agent).filter((t) => t !== "all");
  $("#typeTable").innerHTML = table(["system", ...types], systems.map((s) => [s, ...types.map((t) => (S[s][t]["R@5"] ?? 0).toFixed(2))]), "agent");
  $("#metricsTable").innerHTML = table(["system", "P@1", "P@5", "R@5", "R@10", "MRR", "p50 ms", "p95 ms"],
    systems.map((s) => { const a = S[s].all; return [s, a["P@1"].toFixed(2), a["P@5"].toFixed(2), a["R@5"].toFixed(2), a["R@10"].toFixed(2), a.MRR.toFixed(2), a.latency_p50_ms, a.latency_p95_ms]; }), "agent") +
    `<p class="muted">Negative query (“placeCall before openDeeplink”, correct answer: none): ${systems.map((s) => `${s} ${S[s].all.negative_correct === 1 ? "✓" : "✗"}`).join(" · ")}</p>`;
  const st = R.index;
  let cost = table(["metric", "value"], [
    ["files / LOC", `${st.files} / ${st.loc}`], ["functions / call sites", `${st.functions} / ${st.call_sites}`],
    ["resolved call edges", st.resolved_edges], ["tools discovered", st.tools], ["chunks", st.chunks],
    ["parse + resolve", `${(st.parse_s + st.resolve_s).toFixed(2)} s`], ["embedding (CPU)", `${st.embed_s} s`],
    ["index size", `${(st.index_bytes / 1e6).toFixed(2)} MB`], ["embedder", R.embedder],
    ["optimisation detectors", `precision ${R.detector.precision}, recall ${R.detector.recall}`],
  ]);
  if (R.scale) {
    const sc = R.scale;
    cost += `<div class="panel-head" style="margin-top:14px"><span>Scale benchmark (${sc.copies}× replicated)</span></div>` + table(["metric", "value"], [
      ["files / LOC", `${sc.files} / ${sc.loc.toLocaleString()}`], ["≈ repo tokens", sc.approx_repo_tokens.toLocaleString()], ["chunks", sc.chunks],
      ["cold index", `${sc.cold_index_s} s (embed ${sc.embed_s} s)`], ["incremental re-index (1 file)", `${sc.incremental_reindex_s} s`],
      ["index size", `${sc.index_mb} MB`], ["agent latency p50 / p95", `${sc.agent_latency_p50_ms} / ${sc.agent_latency_p95_ms} ms`],
    ]);
  }
  $("#costTable").innerHTML = cost;
  $("#perQuery").innerHTML = table(["id", "type", "query", ...systems],
    R.per_query.map((q) => [q.id, q.type, q.query, ...systems.map((s) => {
      const m = q.systems[s]; const v = m["R@5"] ?? m.negative_correct;
      return `<span class="${v >= 0.99 ? "r-ok" : v >= 0.5 ? "r-mid" : "r-bad"}">${v.toFixed(2)}</span>`;
    })]), null, true);
}

function table(head, rows, bestKey, raw = false) {
  return `<table><thead><tr>${head.map((h, i) => `<th class="${i ? "num" : ""}">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) =>
    `<tr class="${r[0] === bestKey ? "best" : ""}">${r.map((c, i) => `<td class="${i && !raw ? "num" : ""}">${raw ? (i === 2 ? esc(c) : c) : esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

/* --------------------------------------------------------------- findings */
async function loadFindings() {
  const r = await (await fetch("/api/findings")).json();
  const order = { high: 0, medium: 1, low: 2 };
  const f = r.findings.sort((a, b) => order[a.severity] - order[b.severity]);
  $("#findMeta").textContent = `${f.length} findings · ${f.filter((x) => x.severity === "high").length} high`;
  $("#findings").innerHTML = `<div class="panel">${f.map(optRow).join("")}</div>`;
}

/* --------------------------------------------------------------- explorer */
let treeData = null;
async function loadTree() {
  if (!treeData) treeData = await (await fetch("/api/map")).json();
  const filt = $("#treeFilter").value.toLowerCase();
  $("#tree").innerHTML = Object.entries(treeData.files).filter(([p, f]) => !filt || p.toLowerCase().includes(filt) || f.symbols.some((s) => s.name.toLowerCase().includes(filt)))
    .map(([p, f]) => `<div class="tfile"><span>${esc(p)}</span><span class="muted">${f.loc}${f.findings ? ` · ⚠${f.findings}` : ""}</span></div>` +
      f.symbols.map((s) => `<div class="tsym ${s.kind === "tool_handler" ? "tool" : ""}" data-file="${esc(p)}" data-line="${s.line}" data-name="${esc(s.name)}">${esc(s.name)}</div>`).join("")).join("");
  $$("#tree .tsym").forEach((el) => el.addEventListener("click", () => exploreSymbol(el.dataset.file, Number(el.dataset.line), el.dataset.name)));
}
$("#treeFilter").addEventListener("input", () => loadTree());

async function exploreSymbol(file, line, name) {
  $("#exTitle").textContent = `${name} — ${file}:${line}`;
  const fid = `${file}::${name}@${line}`;
  const g = await (await fetch(`/api/graph?fid=${encodeURIComponent(fid)}&hops=2`)).json();
  exCy = drawGraph("#exGraph", g, exCy);
  $("#exCode").innerHTML = "";
  openCode(file, line);
}

/* ----------------------------------------------------------------- index */
$("#indexBtn").addEventListener("click", () => { $("#indexPath").value = STATUS?.repo_path || ""; $("#indexDlg").showModal(); });
$("#indexForm").addEventListener("submit", (e) => {
  if (e.submitter?.value !== "default") return;
  e.preventDefault();
  const path = $("#indexPath").value.trim();
  if (!path) return;
  $("#indexGo").disabled = true;
  const es = new EventSource(`/api/index?path=${encodeURIComponent(path)}`);
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "progress") $("#indexProgress").innerHTML = `<span class="spinner"></span> ${ev.stage} ${ev.done}/${ev.total}`;
    if (ev.type === "indexed") { const s = ev.meta.stats; $("#indexProgress").textContent = `✓ ${s.files} files, ${s.functions} functions, ${s.chunks} chunks in ${s.total_s}s`; treeData = null; loadStatus(); }
    if (ev.type === "error") $("#indexProgress").textContent = `✗ ${ev.text}`;
    if (ev.type === "done") { es.close(); $("#indexGo").disabled = false; }
  };
});

loadStatus();
const qp = new URLSearchParams(location.search).get("q");
if (qp) { $("#q").value = qp; setTimeout(ask, 300); }
