/* ContextMAX viewer. Hand-rolled SVG, no dependencies, no network. Everything drawn here is
   computed from the JSON inlined in the page; the reported counts are always exact even when
   the drawing is capped. */
(function () {
  "use strict";
  const DATA = JSON.parse(document.getElementById("data").textContent);
  const $ = (sel, el) => (el || document).querySelector(sel);
  const NS = "http://www.w3.org/2000/svg";
  const DRAW_CAP = 120;

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const c of children || []) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    return node;
  }
  function svgEl(tag, attrs) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    return node;
  }
  function chip(text, cls) { return el("span", { class: "chip " + (cls || ""), text: text }); }
  function sortBy(arr, key) { return arr.slice().sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0)); }

  // ---- pan / zoom -----------------------------------------------------------------------
  function panZoom(svg, group, bounds) {
    let scale = 1, tx = 0, ty = 0, dragging = null;
    function apply() { group.setAttribute("transform", `translate(${tx} ${ty}) scale(${scale})`); }
    function fit() {
      const w = svg.clientWidth || 800, h = svg.clientHeight || 600;
      scale = Math.min(1.25, Math.max(0.15, Math.min(w / (bounds.w + 40), h / (bounds.h + 40))));
      tx = (w - bounds.w * scale) / 2; ty = (h - bounds.h * scale) / 2;
      apply();
    }
    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      tx = mx - (mx - tx) * factor; ty = my - (my - ty) * factor; scale *= factor; apply();
    }, { passive: false });
    svg.addEventListener("mousedown", (e) => { dragging = { x: e.clientX - tx, y: e.clientY - ty }; });
    window.addEventListener("mousemove", (e) => { if (dragging) { tx = e.clientX - dragging.x; ty = e.clientY - dragging.y; apply(); } });
    window.addEventListener("mouseup", () => { dragging = null; });
    fit();
    return { fit };
  }

  function arrowDefs(svg) {
    const defs = svgEl("defs");
    const marker = svgEl("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    marker.appendChild(svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#3b4a5c" }));
    defs.appendChild(marker); svg.appendChild(defs);
  }

  function drawNode(group, node, x, y, w, h, label, sub, cls, onClick) {
    const g = svgEl("g", { class: "node " + (cls || ""), transform: `translate(${x - w / 2} ${y - h / 2})` });
    g.appendChild(svgEl("rect", { width: w, height: h }));
    const t = svgEl("text", { x: 8, y: sub ? 15 : h / 2 + 4 }); t.textContent = label.length > 26 ? label.slice(0, 25) + "…" : label; g.appendChild(t);
    if (sub) { const s = svgEl("text", { x: 8, y: 28, class: "sub" }); s.textContent = sub; g.appendChild(s); }
    if (onClick) g.addEventListener("click", onClick);
    group.appendChild(g);
    return g;
  }
  function drawEdge(group, x1, y1, x2, y2, cls) {
    const mx = (x1 + x2) / 2;
    group.appendChild(svgEl("path", { class: "edge " + (cls || ""), d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}` }));
  }

  // ---- index page -----------------------------------------------------------------------
  function renderIndex() {
    const root = $("#app");
    const cov = DATA.coverage, tiers = cov.by_tier || {};
    const stats = el("div", { class: "stats" });
    const items = [
      [cov.n_files, "files catalogued"], [tiers.A || 0, "tier A"], [tiers.B || 0, "tier B"], [tiers.C || 0, "tier C"], [tiers.D || 0, "tier D"],
      [(cov.code || {}).n_symbols || 0, "code symbols"], [(cov.documents || {}).n_documents || 0, "documents"],
      [(cov.documents || {}).n_sections || 0, "sections"], [(cov.links || {}).n_edges || 0, "link edges"], [cov.n_skipped, "recorded skips"],
    ];
    for (const [n, l] of items) stats.appendChild(el("div", { class: "stat" }, [el("div", { class: "n", text: String(n) }), el("div", { class: "l", text: l })]));
    root.appendChild(stats);
    function table(title, rows, head) {
      const sec = el("div", { class: "section" }, [el("h2", { text: title })]);
      const t = el("table", { class: "grid" });
      t.appendChild(el("tr", {}, head.map((h) => el("th", { text: h }))));
      for (const r of rows) t.appendChild(el("tr", {}, r.map((c) => el("td", { text: String(c) }))));
      sec.appendChild(t); root.appendChild(sec);
    }
    const byCount = (obj) => Object.entries(obj || {}).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
    table("Languages", byCount(cov.by_language).map(([k, v]) => [DATA.names.languages[k] || k, v]), ["Language", "Files"]);
    table("Document and data formats", byCount(cov.by_format).map(([k, v]) => [DATA.names.formats[k] || k, v]), ["Format", "Files"]);
    table("What was not fully indexed", byCount(cov.by_skip_reason).map(([k, v]) => [k, v]), ["Reason", "Files"]);
    if (cov.code) {
      const c = cov.code;
      table("Code", [["symbols", c.n_symbols], ["call sites", c.n_call_sites], ["resolved to project symbols", c.n_resolved], ["ambiguous", c.n_ambiguous],
        ["to libraries or builtins", c.n_external], ["names not defined in the project", c.n_unresolved], ["imports resolved", `${c.n_imports_resolved} of ${c.n_imports}`]], ["Measure", "Count"]);
    }
    if (cov.documents) {
      const d = cov.documents;
      table("Documents", [["documents", d.n_documents], ["sections", d.n_sections], ["words", d.n_words], ["references", d.n_references],
        ["references external", d.n_references_external], ["references unresolved", d.n_references_unresolved]], ["Measure", "Count"]);
    }
    root.appendChild(el("div", { class: "section note", text: "Every number above is exact and equals coverage.json. Tiers: A dedicated analyzer, B generic grammar, C lexical only, D catalogued only. Nothing here was produced by a model." }));
  }

  // ---- code page ------------------------------------------------------------------------
  function renderCode() {
    const symbols = DATA.symbols, byId = new Map(symbols.map((s) => [s.id, s]));
    const callers = new Map(), callees = new Map();
    for (const e of DATA.calls) {
      if (!callees.has(e.source)) callees.set(e.source, []);
      if (!callers.has(e.target)) callers.set(e.target, []);
      callees.get(e.source).push(e.target); callers.get(e.target).push(e.source);
    }
    for (const m of [callers, callees]) for (const v of m.values()) v.sort();
    const svg = $("#canvas svg"); arrowDefs(svg);
    const group = svgEl("g"); svg.appendChild(group);
    const panel = $("#panel"), list = $("#symbol-list"), search = $("#search");
    let depth = 1, focus = null, pz = null;

    function walk(start, map, maxDepth) {
      const seen = new Map([[start, 0]]); const queue = [start]; const order = [];
      while (queue.length) {
        const n = queue.shift(); const d = seen.get(n);
        if (maxDepth !== null && d >= maxDepth) continue;
        for (const nxt of map.get(n) || []) if (!seen.has(nxt)) { seen.set(nxt, d + 1); order.push(nxt); queue.push(nxt); }
      }
      return { order, seen };
    }
    function drawOverview() {
      group.innerHTML = "";
      const ov = DATA.overview; const pos = new Map(ov.nodes.map((n) => [n.id, n]));
      for (const e of ov.edges) { const a = pos.get(e.source), b = pos.get(e.target); if (a && b) drawEdge(group, a.x + 80, a.y, b.x - 80, b.y, e.weight > 5 ? "strong" : ""); }
      for (const n of ov.nodes) drawNode(group, n, n.x, n.y, 160, 34, n.label, `${n.size} ${n.kind === "docs" ? "documents" : "symbols"}`, n.kind === "docs" ? "docs" : "", () => filterByModule(n));
      pz = panZoom(svg, group, { w: ov.width, h: ov.height });
      panel.innerHTML = "";
      panel.appendChild(el("h3", { text: "Code overview" }));
      panel.appendChild(el("p", { class: "note", text: `${DATA.overview.nodes.length} modules and document folders; ${symbols.length} symbols in the index. Click a module to list its symbols, or search a symbol to see its callers and callees.` }));
      if (DATA.truncated) panel.appendChild(el("p", { class: "note", text: `Whole-graph drawing capped: ${DATA.truncated} symbols not included in the network data (${DATA.selection_rule}). Counts below are never capped.` }));
    }
    function filterByModule(node) {
      const key = node.kind === "docs" ? null : node.label;
      renderList(key ? symbols.filter((s) => s.cluster === key) : symbols);
    }
    function renderList(items) {
      list.innerHTML = "";
      const shown = items.slice(0, 400);
      for (const s of shown) list.appendChild(el("li", { onclick: () => select(s.id) }, [chip(s.kind), el("span", { class: "mono", text: s.label }), el("span", { class: "cite", text: s.cite })]));
      if (items.length > shown.length) list.appendChild(el("li", { class: "note", text: `${items.length - shown.length} more; refine the search` }));
    }
    function select(id) {
      focus = byId.get(id); if (!focus) return;
      location.hash = "node=" + encodeURIComponent(id);
      const up = walk(id, callers, depth), down = walk(id, callees, depth);
      const upAll = walk(id, callers, null), downAll = walk(id, callees, null);
      group.innerHTML = "";
      const colW = 240, rowH = 40;
      const left = up.order.slice(0, DRAW_CAP), right = down.order.slice(0, DRAW_CAP);
      const h = Math.max(left.length, right.length, 1) * rowH + 80;
      const cx = colW * 1.5, cy = h / 2;
      drawNode(group, focus, cx, cy, 200, 40, focus.label, focus.cite, "focus", null);
      left.forEach((n, i) => { const s = byId.get(n); const y = 40 + i * rowH; drawEdge(group, colW / 2 + 100, y, cx - 100, cy, up.seen.get(n) === 1 ? "strong" : "weak"); drawNode(group, s, colW / 2, y, 200, 32, s.label, `${s.cite} · ${up.seen.get(n)} hop`, "", () => select(n)); });
      right.forEach((n, i) => { const s = byId.get(n); const y = 40 + i * rowH; drawEdge(group, cx + 100, cy, colW * 2.5 - 100, y, down.seen.get(n) === 1 ? "strong" : "weak"); drawNode(group, s, colW * 2.5, y, 200, 32, s.label, `${s.cite} · ${down.seen.get(n)} hop`, "", () => select(n)); });
      pz = panZoom(svg, group, { w: colW * 3, h });
      panel.innerHTML = "";
      panel.appendChild(el("h3", {}, [chip(focus.kind), chip("tier " + focus.tier, "tier-" + focus.tier), chip(focus.role), document.createTextNode(" " + focus.label)]));
      const dl = el("dl", { class: "kv" });
      const kv = [["where", focus.cite], ["file", focus.file], ["signature", focus.signature || ""], ["doc", focus.doc || "(no documentation comment)"],
        ["callers", `${up.order.length} within ${depth === null ? "all" : depth} hop(s) · full reach ${upAll.order.length} upstream · ${Math.max(0, up.order.length - left.length)} not drawn`],
        ["callees", `${down.order.length} within ${depth === null ? "all" : depth} hop(s) · full reach ${downAll.order.length} downstream · ${Math.max(0, down.order.length - right.length)} not drawn`]];
      for (const [k, v] of kv) { dl.appendChild(el("dt", { text: k })); dl.appendChild(el("dd", { text: v })); }
      panel.appendChild(dl);
      const docs = DATA.mentions[id] || [];
      panel.appendChild(el("h2", { text: `Mentioned in documents (${docs.length})` }));
      if (!docs.length) panel.appendChild(el("p", { class: "note", text: "No document section names this symbol. Absence here is not proof of absence: check skipped files and tier C limits." }));
      const ul = el("ul", { class: "list" });
      for (const d of docs) ul.appendChild(el("li", {}, [el("a", { href: `docs.html#sec=${encodeURIComponent(d.section)}`, text: d.title }), chip(d.confidence), el("span", { class: "cite", text: d.cite })]));
      panel.appendChild(ul);
      panel.appendChild(el("p", { class: "note", text: focus.tier === "C" ? "Tier C: symbols and calls were found by lexical pattern (confidence low). Verify at the cited lines." : "Verify at the cited lines before relying on this." }));
    }
    for (const b of document.querySelectorAll("[data-depth]")) b.addEventListener("click", () => {
      for (const o of document.querySelectorAll("[data-depth]")) o.classList.remove("active");
      b.classList.add("active"); depth = b.dataset.depth === "all" ? null : Number(b.dataset.depth); if (focus) select(focus.id);
    });
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      renderList(q ? symbols.filter((s) => s.label.toLowerCase().includes(q) || s.file.toLowerCase().includes(q)) : symbols);
    });
    $("#overview-btn").addEventListener("click", () => { focus = null; location.hash = ""; drawOverview(); });
    renderList(symbols);
    const m = location.hash.match(/node=([^&]+)/);
    if (m) { const id = decodeURIComponent(m[1]); if (byId.has(id)) select(id); else { const byName = symbols.find((s) => s.label === id); if (byName) select(byName.id); else drawOverview(); } } else drawOverview();
  }

  // ---- docs page ------------------------------------------------------------------------
  function renderDocs() {
    const docs = DATA.documents, byId = new Map(docs.map((d) => [d.id, d]));
    const sectionsByDoc = new Map();
    for (const s of DATA.sections) { if (!sectionsByDoc.has(s.doc)) sectionsByDoc.set(s.doc, []); sectionsByDoc.get(s.doc).push(s); }
    const panel = $("#panel"), list = $("#doc-list"), search = $("#search"), canvas = $("#canvas");
    function renderList(items) {
      list.innerHTML = "";
      for (const d of items.slice(0, 500)) list.appendChild(el("li", { onclick: () => select(d.id) }, [chip(d.format), el("span", { text: d.title }), el("span", { class: "cite", text: `${d.sections} §` })]));
    }
    function select(id, sectionId) {
      const d = byId.get(id); if (!d) return;
      location.hash = sectionId ? "sec=" + encodeURIComponent(sectionId) : "doc=" + encodeURIComponent(id);
      canvas.innerHTML = "";
      const wrap = el("div", { class: "section" });
      wrap.appendChild(el("h3", {}, [chip(d.format), chip(d.adapter), chip(d.determinism), document.createTextNode(" " + d.title)]));
      const dl = el("dl", { class: "kv" });
      for (const [k, v] of [["file", d.file], ["words", String(d.words)], ["sections", String(d.sections)], ["parameters", String(d.parameters || 0)], ["terms", String(d.terms || 0)], ["references", d.refs_summary || "none"]]) { dl.appendChild(el("dt", { text: k })); dl.appendChild(el("dd", { text: v })); }
      wrap.appendChild(dl);
      wrap.appendChild(el("h2", { text: "Outline" }));
      const secs = sectionsByDoc.get(id) || [];
      if (!secs.length) wrap.appendChild(el("p", { class: "note", text: "No headings were found; the whole document is one section." }));
      const tree = el("div", { class: "tree" }); const stack = [[0, el("ul")]]; tree.appendChild(stack[0][1]);
      for (const s of secs) {
        while (stack.length > 1 && stack[stack.length - 1][0] >= s.depth) stack.pop();
        const li = el("li", {}, [el("a", { href: "#", onclick: (e) => { e.preventDefault(); showSection(d, s); }, text: (s.number ? s.number + " " : "") + s.title }), el("span", { class: "cite", text: " " + s.cite })]);
        if (sectionId === s.id) li.classList.add("selected");
        stack[stack.length - 1][1].appendChild(li);
        const ul = el("ul"); li.appendChild(ul); stack.push([s.depth, ul]);
      }
      wrap.appendChild(tree);
      const terms = (DATA.terms || {})[id] || [];
      if (terms.length) {
        wrap.appendChild(el("h2", { text: `Terms (${d.terms})` }));
        const tl = el("ul", { class: "list" });
        for (const t of terms) tl.appendChild(el("li", {}, [chip(t.method), el("span", { class: "mono", text: t.name + (t.acronym && t.acronym !== t.name ? " (" + t.acronym + ")" : "") }), el("span", { text: t.expansion && t.expansion !== t.name ? " = " + t.expansion : (t.definition ? " — " + t.definition : "") }), el("span", { class: "cite", text: t.occurrences ? " " + t.occurrences + "x" : "" })]));
        if (terms.length < d.terms) tl.appendChild(el("li", { class: "note", text: `… ${d.terms - terms.length} more in nodes/terms.jsonl (cmx q term <name>)` }));
        wrap.appendChild(tl);
        wrap.appendChild(el("p", { class: "note", text: "Acronyms, definitions and glossary rows are quoted from the document; keyphrases are statistical candidates, not concepts." }));
      }
      const params = (DATA.parameters || {})[id] || [];
      if (params.length) {
        wrap.appendChild(el("h2", { text: `Parameters (${d.parameters})` }));
        const pl = el("ul", { class: "list" });
        for (const p of params) pl.appendChild(el("li", {}, [chip(p.source_kind), el("span", { class: "mono", text: p.label }), el("span", { text: " = " + p.display + (p.unit ? " " + p.unit : "") + (p.formula ? "  " + p.formula : "") + (p.hidden ? "  (hidden)" : "") }), el("span", { class: "cite", text: " " + p.cite })]));
        if (params.length < d.parameters) pl.appendChild(el("li", { class: "note", text: `… ${d.parameters - params.length} more in nodes/parameters.jsonl (cmx q param <label>)` }));
        wrap.appendChild(pl);
        wrap.appendChild(el("p", { class: "note", text: "A parameter's identity is its label, not its number. Values are read as stored; verify at the cited cell or line." }));
      }
      canvas.appendChild(wrap);
      panel.innerHTML = "";
      panel.appendChild(el("h3", { text: "Links from this document" }));
      const rel = DATA.doc_links[id] || [];
      if (!rel.length) panel.appendChild(el("p", { class: "note", text: "No links of any kind were derived. Absence here is not proof of absence." }));
      const ul = el("ul", { class: "list" });
      for (const r of rel) ul.appendChild(el("li", {}, [chip(r.rel), r.target_page ? el("a", { href: r.target_page, text: r.label }) : el("span", { text: r.label }), chip(r.confidence || r.status)]));
      panel.appendChild(ul);
      if (sectionId) { const s = secs.find((x) => x.id === sectionId); if (s) showSection(d, s); }
    }
    function showSection(d, s) {
      location.hash = "sec=" + encodeURIComponent(s.id);
      panel.innerHTML = "";
      panel.appendChild(el("h3", { text: (s.number ? s.number + " " : "") + s.title }));
      panel.appendChild(el("p", { class: "note", text: s.cite }));
      panel.appendChild(el("pre", { class: "text", text: s.preview || "(empty section)" }));
      const mentions = DATA.section_mentions[s.id] || [];
      panel.appendChild(el("h2", { text: `Code named in this section (${mentions.length})` }));
      const ul = el("ul", { class: "list" });
      for (const m of mentions) ul.appendChild(el("li", {}, [el("a", { href: `code.html#node=${encodeURIComponent(m.symbol)}`, class: "mono", text: m.label }), chip(m.confidence), el("span", { class: "cite", text: m.cite })]));
      panel.appendChild(ul);
      panel.appendChild(el("p", { class: "note", text: "Exact means the section text names a mapped symbol: strong discovery evidence, not proof the document specifies that code. Open the cited lines to verify." }));
    }
    search.addEventListener("input", () => { const q = search.value.trim().toLowerCase(); renderList(q ? docs.filter((d) => d.title.toLowerCase().includes(q) || d.file.toLowerCase().includes(q)) : docs); });
    renderList(docs);
    const ms = location.hash.match(/sec=([^&]+)/), md = location.hash.match(/doc=([^&]+)/);
    if (ms) { const sid = decodeURIComponent(ms[1]); const sec = DATA.sections.find((s) => s.id === sid); if (sec) select(sec.doc, sid); }
    else if (md) select(decodeURIComponent(md[1]));
    else if (docs.length) canvas.appendChild(el("div", { class: "empty", text: `${docs.length} documents. Pick one on the right.` }));
    else canvas.appendChild(el("div", { class: "empty", text: "No documents were extracted." }));
  }

  const page = document.body.dataset.page;
  if (page === "index") renderIndex();
  else if (page === "code") renderCode();
  else if (page === "docs") renderDocs();
})();
