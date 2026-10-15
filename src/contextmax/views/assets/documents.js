/* ContextMAX documents page: the document map, three ways. */
"use strict";
(function () {
  var D = CMX.pageData(), safe = CMX.safe, $ = CMX.$;
  var N = D.nodes, E = D.edges;
  var canvas = $("#canvas"), side = $("#drawer"), crumbs = $("#crumbs"), controls = $("#controls");
  var KIND = {
    cites: { label: "cites", title: "writes another document's title or file name" },
    quotes: { label: "document number", title: "quotes another document's number" },
    shares: { label: "shared values", title: "states the same named values (red when they differ)" },
    samepart: { label: "same part", title: "about the same part of the code, next stage" }
  };
  var kindsOn = { cites: true, quotes: true, shares: true, samepart: false, onlyCoded: false };
  var BIG_NODES = 1500, BIG_LINKS = 15000;     // above either, a map is drawn the cheaper way (every line still drawn)
  var linksOf = N.map(function () { return []; });
  E.forEach(function (e, i) { linksOf[e.a].push(i); linksOf[e.b].push(i); });
  var modIndex = {}; D.modules.forEach(function (m, i) { modIndex[m] = i; });
  var codeTarget = D.code_targets.length ? D.code_targets[0].name : null;

  function edgeColor(e) {
    if (e.k === "shares") return e.differ_count ? CMX.css("--conflict") : CMX.css("--ok");
    if (e.k === "samepart") return CMX.css("--text-3");
    return CMX.css("--doc");
  }
  function strengthClass(c) { return c === "strong" ? "strong" : c === "one" ? "one" : ""; }

  /* == the panel == */
  function showDoc(id) {
    var n = N[id]; selected = id;
    var h = "<h2>" + safe(n.t) + "</h2>";
    if (n.dt && n.dt.toLowerCase() !== n.t.toLowerCase()) h += '<p class="quiet">“' + safe(n.dt) + "”</p>";
    h += '<div class="hstack"><span class="badge is-doc">' + safe(n.st) + "</span>" + (n.ext ? '<span class="badge">' + safe(n.ext) + "</span>" : "") +
      (n.code.length ? '<span class="badge is-code">names code</span>' : n.topic ? '<span class="badge">about ' + safe(n.topic) + "</span>" : '<span class="badge">stand-alone</span>') + "</div>";
    h += '<p class="quiet" style="font-size:12.5px">' + safe(n.folder) + " › " + safe(n.rel) + "</p>";
    if (n.copies > 1) h += '<div class="remark"><b>' + n.copies + " copies, one document.</b> Kept: this copy (" + safe(n.reason || "") + "). Folded in: <span class=\"fixed\">" + safe(n.copy_list.join(", ")) + "</span></div>";
    var acts = [];
    if (n.path) {
      acts.push('<button type="button" class="btn" data-file="' + safe(n.path) + '" data-how="open">Open document</button>');
      acts.push('<button type="button" class="btn ghost" data-file="' + safe(n.path) + '" data-how="select">Show in folder</button>');
    }
    if (n.text) acts.push('<a class="btn ghost" target="_blank" rel="noopener" href="../documents/' + safe(n.text) + '">Extracted text</a>');
    if (acts.length) h += '<div class="hstack">' + acts.join("") + "</div>";
    if (n.code.length) {
      h += "<h3>Names code</h3><ul>" + n.code.map(function (c) {
        var t = c.t[0] || codeTarget;
        return '<li><span><i class="strength ' + strengthClass(c.c) + '"></i><a href="code-' + safe(t) + '.html#view=bubbles">' + safe(c.m) + "</a> <span class=\"quiet\">" + c.w + " name" + (c.w > 1 ? "s" : "") + "</span></span><span>" + safe(c.c) + "</span></li>" +
          '<li style="display:block;color:var(--text-2);font-size:12.5px" class="fixed">' + c.top.map(function (s) { return '<a href="code-' + safe(t) + ".html#fn=" + encodeURIComponent(s[0]) + '">' + safe(s[0]) + "</a>"; }).join(", ") + "</li>";
      }).join("") + "</ul>";
    }
    var ls = linksOf[id].map(function (i) { return E[i]; }).filter(function (e) { return e.k !== "samepart"; });
    if (ls.length) {
      h += "<h3>Linked documents</h3><ul>" + ls.slice(0, 30).map(function (e) {
        var other = e.a === id ? e.b : e.a, dir = e.k === "cites" || e.k === "quotes" ? (e.a === id ? "cites" : "cited by") : "";
        var what = e.k === "shares" ? (e.shared_count + " values" + (e.differ_count ? ", <b style=\"color:var(--conflict)\">" + e.differ_count + " differ</b>" : ", all agree")) : e.k === "quotes" ? (dir + " · " + safe(e.doc_number || "")) : dir;
        return '<li><a href="#" data-doc="' + other + '">' + safe(N[other].t) + "</a><span>" + what + "</span></li>";
      }).join("") + "</ul>";
    }
    h += "<h3>Contents</h3><p class=\"quiet\">" + n.nh + " headings · " + n.nr + " shall statements · " + n.np + " values</p>";
    if (n.heads.length) h += '<ul style="gap:2px">' + n.heads.map(function (x) { return "<li><span>" + safe(x) + "</span></li>"; }).join("") + "</ul>";
    if (n.reqs.length) h += "<h3>Requirements</h3><ul>" + n.reqs.map(function (r) { return '<li style="display:block">' + safe(r[0]) + (r[1].length ? ' <span class="badge is-doc fixed">' + safe(r[1].join(", ")) + "</span>" : "") + "</li>"; }).join("") + "</ul>";
    if (n.params.length) {
      h += "<h3>Values</h3><ul>" + n.params.map(function (p) {
        var vi = p[3] ? varPos[p[3]] : undefined;
        var name = p[0] ? (vi !== undefined ? '<a href="#" data-var="' + vi + '">' + safe(p[0]) + "</a>" : safe(p[0])) : '<span class="quiet">(no name)</span>';
        return "<li><span>" + name + "</span><span class=\"fixed\">" + safe(p[1]) + (p[2] ? " " + safe(p[2]) : "") + "</span></li>";
      }).join("") + "</ul><div id=\"varbox\"></div><p class=\"quiet\" style=\"font-size:12.5px\">A linked name is stated in other documents too: click it to compare.</p>";
    }
    side.innerHTML = h;
    if (current && current.select) current.select(id);
  }
  var varPos = {}; D.variables.forEach(function (v, i) { varPos[v[1]] = i; });
  function compareVar(vi) {
    var rows = D.statements[vi], uniqueValues = {};
    rows.forEach(function (r) { uniqueValues[r[2]] = r[1]; });
    var k = Object.keys(uniqueValues).length;
    var box = $("#varbox"); if (!box) return;
    box.innerHTML = '<div class="remark"><b>' + safe(D.variables[vi][0]) + "</b> is stated in " + rows.length + " documents: " +
      (k === 1 ? '<span style="color:var(--ok)">all say ' + safe(uniqueValues[Object.keys(uniqueValues)[0]]) + "</span>" : '<b style="color:var(--conflict)">' + k + " different values</b>") +
      "<ul>" + rows.map(function (r) { return '<li><a href="#" data-doc="' + r[0] + '">' + safe(N[r[0]].t) + '</a><span class="fixed">' + safe(r[1]) + (r[3] ? " @" + safe(r[3]) : "") + "</span></li>"; }).join("") + "</ul></div>";
  }
  function overview() {
    var c = D.counts;
    side.innerHTML = "<h2>" + CMX.num(c.docs) + ' documents</h2><p class="quiet">' + CMX.num(c.linked_code) + " name code. Links: " +
      Object.keys(c.links).map(function (k) { return c.links[k] + " " + (KIND[k] ? KIND[k].label : k); }).join(", ") + ".</p>" +
      '<p class="quiet">Click a document. Columns are lifecycle stages; each stage has a lane for its workbooks. Rows: documents that name code, documents about a part of the code, and stand-alone documents.</p>' +
      '<div class="remark">Stages, links and values are finding aids drawn from the text. Open the original before relying on a number or a requirement.</div>';
  }
  side.addEventListener("click", function (ev) {
    var a = ev.target.closest("[data-doc]"); if (a) { ev.preventDefault(); focusDoc(+a.getAttribute("data-doc")); return; }
    a = ev.target.closest("[data-var]"); if (a) { ev.preventDefault(); compareVar(+a.getAttribute("data-var")); }
  });
  function focusDoc(id) { showDoc(id); if (current.focus) current.focus(id); }
  function linkToggles() {
    controls.innerHTML = Object.keys(KIND).map(function (k) {
      var sw = k === "shares" ? "border-top:2.5px solid var(--ok)" : k === "samepart" ? "border-top:2px dashed var(--text-3)" : k === "quotes" ? "border-top:2px dashed var(--doc)" : "border-top:2.5px solid var(--doc)";
      return '<button type="button" class="switch' + (kindsOn[k] ? " is-on" : "") + '" data-kind="' + k + '" aria-pressed="' + kindsOn[k] + '" title="' + safe(KIND[k].title) + '"><i style="display:inline-block;width:18px;' + sw + '"></i>' + safe(KIND[k].label) + "</button>";
    }).join("") + '<button type="button" class="switch' + (kindsOn.onlyCoded ? " is-on" : "") + '" data-kind="onlyCoded" aria-pressed="' + kindsOn.onlyCoded + '">Only documents that name code</button>';
    CMX.$$("button", controls).forEach(function (b) { b.onclick = function () { var k = b.getAttribute("data-kind"); kindsOn[k] = !kindsOn[k]; current.enter(); }; });
  }
  function visibleEdge(e) { return kindsOn[e.k] && (!kindsOn.onlyCoded || (N[e.a].code.length && N[e.b].code.length)); }
  function visibleNode(n) { return !kindsOn.onlyCoded || n.code.length; }

  /* == 1 document map (the stage grid) == */
  var corpus = (function () {
    var net = null, nodes = null;
    function build() {
      canvas.innerHTML = '<div class="vis"></div>';
      var ink = CMX.css("--text"), ink2 = CMX.css("--text-2"), surf = CMX.css("--surface");
      var items = [];
      D.headers.forEach(function (hd, i) {
        items.push({ id: "h" + i, label: hd.label.toUpperCase() + (hd.sheet ? "\n(workbooks)" : ""), x: hd.x + 90, y: -90, fixed: true, physics: false, shape: "text",
                     font: { size: hd.sheet ? 14 : 18, color: hd.sheet ? ink2 : ink, bold: true, face: "Segoe UI" } });
      });
      D.tiers.forEach(function (t, i) {
        items.push({ id: "t" + i, label: t.label + "\n" + t.sub, x: -260, y: t.y + 10, fixed: true, physics: false, shape: "text",
                     font: { size: 15, color: ink, face: "Segoe UI", multi: false } });
      });
      N.forEach(function (n) {
        if (!visibleNode(n)) return;
        var mi = modIndex[n.mod || n.topic];
        var c = n.code.length ? CMX.color(mi === undefined ? 0 : mi) : null;
        var sheet = n.kind === "spreadsheet";
        items.push({ id: n.id, label: (n.t.length > 28 ? n.t.slice(0, 27) + "…" : n.t), x: n.x + 90, y: n.y, fixed: true, physics: false, shape: "box",
                     margin: { top: 7, bottom: 7, left: 10, right: 10 }, widthConstraint: { minimum: 180, maximum: 190 },
                     color: { background: c ? c : (n.tier === 1 ? CMX.css("--doc-tint") : surf), border: sheet ? CMX.css("--ok") : (c || CMX.css("--rule")),
                              highlight: { background: c || CMX.css("--doc-tint"), border: CMX.css("--focus") }, hover: { background: c || CMX.css("--doc-tint-2"), border: CMX.css("--doc") } },
                     borderWidth: sheet ? 2 : 1, shapeProperties: { borderRadius: 6, borderDashes: sheet ? [4, 3] : false },
                     font: { color: c ? "#FFFFFF" : ink, size: 12, face: "Segoe UI" }, title: n.t + " · " + n.st });
      });
      var links = [];
      E.forEach(function (e, i) {
        if (!visibleEdge(e)) return;
        links.push({ id: "e" + i, from: e.a, to: e.b, color: { color: edgeColor(e), opacity: e.k === "samepart" ? 0.35 : 0.65, highlight: CMX.css("--focus") },
                     dashes: e.k === "quotes" ? [5, 4] : e.k === "samepart" ? [10, 6] : false, width: e.k === "shares" ? 1 + Math.min(4, e.shared_count / 3) : 1.4,
                     smooth: { type: "curvedCW", roundness: 0.18 }, arrows: e.k === "cites" || e.k === "quotes" ? { to: { enabled: true, scaleFactor: 0.45 } } : undefined,
                     title: e.k === "shares" ? e.shared_count + " shared values" + (e.differ_count ? ", " + e.differ_count + " differ" : "") : KIND[e.k].title });
      });
      var large = items.length > BIG_NODES || links.length > BIG_LINKS;
      nodes = new vis.DataSet(items);
      net = new vis.Network(canvas.firstChild, { nodes: nodes, edges: new vis.DataSet(links) },
        { physics: false, layout: { improvedLayout: false },
          interaction: { hover: true, hoverConnectedEdges: true, tooltipDelay: 120, hideEdgesOnDrag: large, hideEdgesOnZoom: large } });
      net.once("afterDrawing", function () { net.fit(); });
      net.on("click", function (p) { if (p.nodes.length && typeof p.nodes[0] === "number") showDoc(p.nodes[0]); });
    }
    return {
      id: "map", label: "Document map", title: "Stages left to right, rows by how closely a document ties to the code",
      enter: function () { linkToggles(); crumbs.innerHTML = "<b>Document map</b>"; build(); if (selected !== null) showDoc(selected); else overview(); },
      leave: function () { if (net) { net.destroy(); net = null; } },
      select: function (id) { if (net && nodes.get(id)) net.selectNodes([id]); },
      focus: function (id) { if (net && nodes.get(id)) { net.selectNodes([id]); net.focus(id, { scale: 1, animation: true }); } }
    };
  })();

  /* == 2 drafting table (svg) == */
  var drafting = (function () {
    var svg, pz, pages = {}, gLinks;
    var W = 196, Hh = 34;
    function center(n) { return [n.x + W / 2, n.y + Hh / 2]; }
    function draw() {
      svg = CMX.freshSvg(canvas);
      var gGrid = CMX.el("g", {}, svg);
      D.headers.forEach(function (hd) {
        CMX.el("text", { x: hd.x, y: -40, class: "head" }, gGrid, hd.label.toUpperCase() + (hd.sheet ? " · workbooks" : ""));
        CMX.el("line", { x1: hd.x - 22, y1: -60, x2: hd.x - 22, y2: D.height, stroke: CMX.css("--rule"), "stroke-dasharray": "2 5" }, gGrid);
      });
      D.tiers.forEach(function (t) {
        CMX.el("text", { x: -300, y: t.y + 14, class: "head" }, gGrid, t.label);
        CMX.el("text", { x: -300, y: t.y + 32, class: "small" }, gGrid, t.sub);
        CMX.el("line", { x1: -300, y1: t.y - 30, x2: D.width, y2: t.y - 30, stroke: CMX.css("--rule") }, gGrid);
      });
      gLinks = CMX.el("g", {}, svg);
      E.forEach(function (e) {
        if (!visibleEdge(e)) return;
        var a = center(N[e.a]), b = center(N[e.b]);
        var p = CMX.el("path", { d: CMX.arc(a[0], a[1], b[0], b[1], 0.12), class: "link-" + e.k + (e.k === "shares" && e.differ_count ? " differ" : ""), "data-a": e.a, "data-b": e.b }, gLinks);
        CMX.el("title", {}, p, KIND[e.k].label + ": " + N[e.a].t + " → " + N[e.b].t);
      });
      var gPages = CMX.el("g", {}, svg);
      N.forEach(function (n) {
        if (!visibleNode(n)) return;
        var g = CMX.el("g", { style: "cursor:pointer" }, gPages);
        var fold = n.kind === "spreadsheet" ? 0 : 12;
        var d = "M" + n.x + "," + n.y + " h" + (W - fold) + " l" + fold + "," + fold + " v" + (Hh - fold) + " h-" + W + " z";
        var p = CMX.el("path", { d: d, class: "page" + (n.kind === "spreadsheet" ? " workbook" : "") }, g);
        if (n.code.length) CMX.el("rect", { x: n.x, y: n.y + Hh - 4, width: W, height: 4, fill: CMX.css("--code") }, g);
        if (n.kind === "spreadsheet") for (var k = 1; k < 4; k++) CMX.el("line", { x1: n.x + k * W / 4, y1: n.y, x2: n.x + k * W / 4, y2: n.y + Hh, stroke: CMX.css("--surface"), "stroke-width": 1, opacity: 0.6 }, g);
        CMX.el("text", { x: n.x + 9, y: n.y + 21, class: "caption" }, g, n.t.length > 27 ? n.t.slice(0, 26) + "…" : n.t);
        if (n.copies > 1) CMX.el("text", { x: n.x + W - 16, y: n.y + 21, class: "small", "text-anchor": "end" }, g, "×" + n.copies);
        CMX.el("title", {}, g, n.t + " · " + n.st);
        g.addEventListener("click", function () { if (!svg.dataset.dragged) showDoc(n.id); });
        pages[n.id] = p;
      });
      pz = CMX.panZoom(svg, D.width, D.height + 40);
      CMX.zoomButtons(canvas, pz);
    }
    function select(id) {
      Object.keys(pages).forEach(function (k) { pages[k].classList.remove("sel"); });
      if (pages[id]) pages[id].classList.add("sel");
      var near = {}; near[id] = true;
      CMX.$$("path", gLinks).forEach(function (p) {
        var a = +p.getAttribute("data-a"), b = +p.getAttribute("data-b"), on = a === id || b === id;
        p.classList.toggle("link-faded", !on);
        if (on) { near[a] = true; near[b] = true; }
      });
      Object.keys(pages).forEach(function (k) { pages[k].classList.toggle("lo", !near[k]); });
    }
    return {
      id: "drafting", label: "Drafting table", title: "Documents as pages in a fixed grid, light or dark",
      enter: function () { linkToggles(); crumbs.innerHTML = "<b>Drafting table</b>"; draw(); if (selected !== null) showDoc(selected); else overview(); },
      select: select,
      focus: function (id) { var n = N[id]; pz.center(n.x + W / 2, n.y, 1100); select(id); },
      onTheme: function () { draw(); if (selected !== null) select(selected); }
    };
  })();

  /* == 3 network (physics) == */
  var network = (function () {
    var net = null, nodes = null;
    function build() {
      canvas.innerHTML = '<div class="vis"></div>';
      var linked = {};
      E.forEach(function (e) { if (visibleEdge(e)) { linked[e.a] = true; linked[e.b] = true; } });
      var items = [], ink = CMX.css("--text"), bg = CMX.css("--paper");
      N.forEach(function (n) {
        if (!linked[n.id] && !n.code.length) return;
        if (!visibleNode(n)) return;
        items.push({ id: n.id, label: n.t.length > 24 ? n.t.slice(0, 23) + "…" : n.t, shape: n.kind === "spreadsheet" ? "square" : "dot", size: 10 + Math.min(14, linksOf[n.id].length),
                     color: { background: n.code.length ? CMX.css("--doc") : CMX.css("--doc-tint"), border: CMX.css("--doc"), highlight: { background: CMX.css("--doc"), border: CMX.css("--focus") } },
                     font: { color: ink, size: 12, strokeWidth: 4, strokeColor: bg, face: "Segoe UI" }, title: n.t + " · " + n.st });
      });
      var drawn = {};                          // document id -> drawn, looked up once per link instead of searched
      items.forEach(function (x) { drawn[x.id] = true; });
      var mods = {};
      N.forEach(function (n) { if (!drawn[n.id]) return; n.code.forEach(function (c) { mods[c.m] = true; }); });
      Object.keys(mods).sort().forEach(function (m) {
        items.push({ id: "m:" + m, label: m, shape: "box", margin: 8, color: { background: CMX.css("--code-tint"), border: CMX.css("--code") }, font: { color: CMX.css("--code-ink"), face: "Cascadia Mono, Consolas, monospace", size: 12 }, title: "code module " + m });
      });
      var links = [];
      E.forEach(function (e, i) {
        if (!visibleEdge(e) || !drawn[e.a] || !drawn[e.b]) return;
        links.push({ id: "e" + i, from: e.a, to: e.b, color: { color: edgeColor(e), opacity: 0.6 }, dashes: e.k === "quotes" ? [5, 4] : e.k === "samepart" ? [10, 6] : false,
                     width: e.k === "shares" ? 1 + Math.min(4, e.shared_count / 3) : 1.4, arrows: e.k === "cites" || e.k === "quotes" ? { to: { enabled: true, scaleFactor: 0.4 } } : undefined });
      });
      N.forEach(function (n) {
        if (!drawn[n.id]) return;
        n.code.forEach(function (c) { links.push({ from: n.id, to: "m:" + c.m, color: { color: CMX.css("--code"), opacity: 0.55 }, width: c.c === "strong" ? 4 : c.c === "some" ? 2.2 : 1.2, dashes: c.c === "one" ? [4, 4] : false }); });
      });
      // Every link is drawn as its own line at any size. A large network is laid out once, with
      // straight lines and without the slow first layout, and then stands still instead of being
      // simulated and redrawn on every frame; it hides its lines only while it is dragged or zoomed.
      // The layout starts from a fixed seed, so the same documents give the same picture.
      var large = items.length > BIG_NODES || links.length > BIG_LINKS;
      nodes = new vis.DataSet(items);
      net = new vis.Network(canvas.firstChild, { nodes: nodes, edges: new vis.DataSet(links) },
        { physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -60, springLength: 110 },
                     stabilization: { iterations: large ? 100 : 250, updateInterval: 50 } },
          layout: { improvedLayout: !large, randomSeed: 7 },
          interaction: { hover: !large, tooltipDelay: 120, hideEdgesOnDrag: large, hideEdgesOnZoom: large },
          edges: { smooth: large ? false : { type: "continuous" } } });
      if (large) net.once("stabilizationIterationsDone", function () { net.setOptions({ physics: { enabled: false } }); });
      net.on("click", function (p) { if (p.nodes.length && typeof p.nodes[0] === "number") showDoc(p.nodes[0]); });
      if (!items.length) canvas.innerHTML = '<div class="empty">No document links of the kinds switched on.</div>';
    }
    return {
      id: "network", label: "Network", title: "Linked documents and the code modules they name, laid out by physics",
      enter: function () { linkToggles(); crumbs.innerHTML = "<b>Network</b> <span class=\"quiet\">only documents with a link are drawn</span>"; build(); if (selected !== null) showDoc(selected); else overview(); },
      leave: function () { if (net) { net.destroy(); net = null; } },
      select: function (id) { if (net && nodes.get(id)) net.selectNodes([id]); },
      focus: function (id) { if (net && nodes.get(id)) { net.selectNodes([id]); net.focus(id, { scale: 1.1, animation: true }); } }
    };
  })();

  var selected = null, current = null;
  var list = [corpus, drafting, network];
  CMX.initViews("docs", list.map(function (v) { return { id: v.id, label: v.label, title: v.title, enter: function () { current = v; v.enter(); }, leave: v.leave }; }));
  CMX.onTheme(function () { if (current.onTheme) current.onTheme(); else current.enter(); });
  $("#find").addEventListener("keydown", function (ev) {
    if (ev.key !== "Enter") return;
    var q = ev.target.value.trim().toLowerCase(); if (!q) return;
    var hit = N.filter(function (n) { return n.t.toLowerCase().indexOf(q) >= 0 || (n.dt || "").toLowerCase().indexOf(q) >= 0 || n.key.toLowerCase() === q; })[0];
    if (hit) focusDoc(hit.id); else side.innerHTML = '<p class="quiet">No document matches “' + safe(q) + "”.</p>";
  });
  var m = /doc=([^&]+)/.exec(location.hash);
  if (m) { var key = decodeURIComponent(m[1]); var n = N.filter(function (x) { return x.key === key; })[0]; if (n) setTimeout(function () { focusDoc(n.id); CMX.dropHash("doc"); }, 300); }
})();
