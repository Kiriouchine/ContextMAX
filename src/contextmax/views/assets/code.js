/* ContextMAX code page: one code base, five ways to look at it. */
"use strict";
(function () {
  var D = CMX.pageData(), safe = CMX.safe, $ = CMX.$;
  var F = D.functions, M = D.modules;
  var callers = F.map(function () { return []; }), callees = F.map(function () { return []; });
  D.calls.forEach(function (c) { callees[c[0]].push(c[1]); callers[c[1]].push(c[0]); });
  var perModule = M.map(function () { return []; });
  F.forEach(function (f) { perModule[f.m].push(f.id); });
  var state = { tests: false, stubs: true, physics: true, lines: true, module: null, fn: null };
  /* a view drawn again because a switch was turned (or the theme changed) keeps where the viewer left it */
  var held = null;
  function hold() { held = current && current.view ? { id: current.id, v: current.view() } : null; }
  function take(id) { var v = held && held.id === id ? held.v : null; held = null; return v; }
  function filePath(rel) { return D.target.root ? D.target.root.replace(/[\\\/]+$/, "") + "\\" + rel.replace(/\//g, "\\") : ""; }
  var canvas = $("#canvas"), side = $("#drawer"), crumbs = $("#crumbs"), controls = $("#controls");
  var docsUrl = "documents.html";

  function visible(f) { return (f.r !== "test" || state.tests) && (f.r !== "stub" || state.stubs); }
  function plural(n, word) { n = n || 0; return CMX.num(n) + " " + word + (n === 1 ? "" : "s"); }
  function where(f) { return D.files[f.f] + ":" + f.l + (f.e && f.e !== f.l ? "–" + f.e : ""); }
  function roleClass(f) { return f.r === "test" ? "role-test" : f.r === "stub" ? "role-stub" : "role-product"; }

  /* == the panel == */
  function impact(id) {
    var seen = {}, queue = [id], prod = 0, tests = 0, mods = {};
    seen[id] = true;
    while (queue.length) {
      var n = queue.shift();
      callers[n].forEach(function (c) {
        if (seen[c]) return; seen[c] = true; queue.push(c);
        if (F[c].r === "test") tests++; else { prod++; mods[F[c].m] = true; }
      });
    }
    return { prod: prod, tests: tests, mods: Object.keys(mods).length, ids: Object.keys(seen).map(Number) };
  }
  function fnList(ids, cap) {
    ids = ids.slice().sort(function (a, b) { return F[b].c - F[a].c || (F[a].n < F[b].n ? -1 : 1); });
    var h = ids.slice(0, cap).map(function (i) {
      var f = F[i];
      return '<li><a href="#" data-fn="' + i + '" class="fixed">' + safe(f.q) + '</a><span class="fixed">' + safe(M[f.m].name) + (f.r !== "product" ? " · " + f.r : "") + "</span></li>";
    }).join("");
    if (ids.length > cap) h += '<li class="quiet">and ' + (ids.length - cap) + " more</li>";
    return "<ul>" + h + "</ul>";
  }
  function describeFn(id) {
    var f = F[id]; state.fn = id;
    var cs = callers[id], prodC = cs.filter(function (i) { return F[i].r !== "test"; }).length;
    var link = CMX.editorLink(D.target.root, D.files[f.f], f.l);
    var h = '<h2 class="fixed">' + safe(f.q) + "</h2>";
    h += '<div class="hstack"><span class="badge ' + roleClass(f) + '">' + safe(f.r) + '</span><span class="badge">' + safe(f.lang) + '</span><span class="badge">' + safe(f.k) + "</span>" +
      (f.c === 0 && f.r === "product" ? '<span class="badge is-code">entry point</span>' : "") + "</div>";
    h += '<p class="fixed" style="font-size:12.5px">' + safe(f.sig) + "</p>";
    if (f.d) h += "<p>" + safe(f.d) + "</p>";
    var file = filePath(D.files[f.f]);
    h += '<div class="hstack"><span class="fixed">' + safe(where(f)) + "</span>" + (link ? '<a class="btn" href="' + link + '">Open in editor</a>' : "") +
      (file ? '<button type="button" class="btn ghost" data-file="' + safe(file) + '" data-how="select">Show in folder</button>' : "") + "</div>";
    h += "<h3>Called by " + cs.length + (cs.length ? ' <span class="quiet" style="text-transform:none;letter-spacing:0">· ' + prodC + " product, " + (cs.length - prodC) + " test</span>" : "") + "</h3>";
    h += cs.length ? fnList(cs, 12) : '<p class="quiet">Nothing in these folders calls it by name.' + (f.r === "product" ? " It may run through a pointer, a callback, or from outside." : "") + "</p>";
    h += "<h3>Calls " + callees[id].length + "</h3>" + (callees[id].length ? fnList(callees[id], 12) : '<p class="quiet">No calls into these folders.</p>');
    if (f.nx) h += '<p class="quiet">Outside these folders: <span class="fixed">' + safe(f.x.slice(0, 12).join(", ")) + (f.nx > 12 ? " …" : "") + "</span></p>";
    if (f.ind && f.ind.length) h += '<div class="remark">' + f.ind.length + " call" + (f.ind.length > 1 ? "s" : "") + " through a pointer or an object " + (f.ind.length > 1 ? "are" : "is") + " not followed: <span class=\"fixed\">" + safe(f.ind.slice(0, 4).map(function (x) { return x.expr + " (line " + x.line + ")"; }).join(", ")) + "</span>. Their targets cannot be known from the text.</div>";
    if (f.amb && f.amb.length) h += '<div class="remark">' + f.amb.map(function (a) { return '<span class="fixed">' + safe(a[0]) + "</span> is defined " + a[1].length + " times; the nearest one was chosen."; }).join(" ") + "</div>";
    var docs = D.docs_for[String(id)] || [];
    h += "<h3>Documents that name it</h3>" + (docs.length ? "<ul>" + docs.map(function (d) {
      return '<li><span><i class="strength ' + safe(d[2]) + '"></i><a href="' + docsUrl + "#doc=" + encodeURIComponent(d[3]) + '">' + safe(d[0]) + "</a></span><span>" + safe(d[1]) + "</span></li>";
    }).join("") + "</ul>" : '<p class="quiet">No document names it.</p>');
    var im = impact(id);
    h += '<h3>If it changes</h3><p>' + (im.prod ? "<b>" + im.prod + "</b> product function" + (im.prod > 1 ? "s" : "") + " in <b>" + im.mods + "</b> module" + (im.mods > 1 ? "s" : "") + " can reach it" : "No product function reaches it by name") + (im.tests ? ", and " + im.tests + " test" + (im.tests > 1 ? "s" : "") : "") + '.</p><div class="hstack"><button type="button" class="btn ghost" data-impact="' + id + '">Show them</button></div>';
    side.innerHTML = h;
    if (current && current.select) current.select(id);
  }
  function describeModule(mi) {
    var m = M[mi]; state.module = mi;
    var out = D.mod_edges.filter(function (e) { return e[0] === mi; }).sort(function (a, b) { return b[2] - a[2]; });
    var inn = D.mod_edges.filter(function (e) { return e[1] === mi; }).sort(function (a, b) { return b[2] - a[2]; });
    var top = perModule[mi].slice().sort(function (a, b) { return F[b].c - F[a].c; }).slice(0, 10);
    var h = '<h2 class="fixed">' + safe(m.name) + '</h2><p class="quiet">' + m.nf + " functions (" + m.np + " product) in " + m.files + " files</p>";
    var folder = D.target.root ? filePath(m.dir || "").replace(/\\$/, "") : "";
    h += '<div class="hstack"><button type="button" class="btn" data-open="' + mi + '">Open this module</button>' +
      (folder ? '<button type="button" class="btn ghost" data-file="' + safe(folder) + '" data-how="open" title="' + safe(folder) + '">Open its folder</button>' : "") + "</div>";
    h += "<h3>Calls into</h3>" + (out.length ? "<ul>" + out.map(function (e) { return '<li><a href="#" data-mod="' + e[1] + '" class="fixed">' + safe(M[e[1]].name) + "</a><span>" + e[2] + " calls</span></li>"; }).join("") + "</ul>" : '<p class="quiet">No other module.</p>');
    h += "<h3>Called from</h3>" + (inn.length ? "<ul>" + inn.map(function (e) { return '<li><a href="#" data-mod="' + e[0] + '" class="fixed">' + safe(M[e[0]].name) + "</a><span>" + e[2] + " calls</span></li>"; }).join("") + "</ul>" : '<p class="quiet">No other module.</p>');
    h += "<h3>Most called</h3>" + fnList(top, 10);
    h += "<h3>Documents about it</h3>" + (m.docs.length ? "<ul>" + m.docs.map(function (d) { return '<li><span><i class="strength ' + safe(d[2]) + '"></i><a href="' + docsUrl + "#doc=" + encodeURIComponent(d[3]) + '">' + safe(d[0]) + "</a></span><span>" + safe(d[1]) + "</span></li>"; }).join("") + "</ul>" : '<p class="quiet">No document names its code.</p>');
    side.innerHTML = h;
  }
  function describeOverview() {
    var s = D.summary, langs = Object.keys(D.target.languages).map(function (k) { return k + " " + D.target.languages[k]; }).join(", ");
    side.innerHTML = '<h2>' + safe(D.target.label) + '</h2><p class="quiet">' + safe(langs) + "</p>" +
      '<dl class="kv"><dt>Files</dt><dd>' + CMX.num(s.files_count) + "</dd><dt>Functions</dt><dd>" + CMX.num(s.functions_count) + " (" + CMX.num(s.product_functions_count) + " product, " + CMX.num(s.test_functions_count) + " test)</dd>" +
      "<dt>Calls</dt><dd>" + CMX.num(s.call_edges_count) + "</dd><dt>Modules</dt><dd>" + CMX.num(s.modules_count) + "</dd><dt>Entry points</dt><dd>" + CMX.num(s.entry_points_count) + "</dd></dl>" +
      '<div class="remark">Not followed: ' + plural(s.indirect_calls_count, "call") + " through pointers or objects, " + plural(s.ambiguous_calls_count, "call") + " to a name defined more than once, and calls to " + plural(s.unresolved_call_names_count, "name") + " defined outside these folders.</div>" +
      '<p class="quiet" style="margin-top:14px">Click a module or a function to see it here. A bubble with an arrow going into a box ' +
      "opens: double-click it to see the functions inside (or, for a function of another module, that module).</p>";
  }
  side.addEventListener("click", function (ev) {
    var a = ev.target.closest("[data-fn]"); if (a) { ev.preventDefault(); goFn(+a.getAttribute("data-fn")); return; }
    a = ev.target.closest("[data-mod]"); if (a) { ev.preventDefault(); describeModule(+a.getAttribute("data-mod")); if (current.selectModule) current.selectModule(+a.getAttribute("data-mod")); return; }
    a = ev.target.closest("[data-open]"); if (a) { ev.preventDefault(); if (current.openModule) current.openModule(+a.getAttribute("data-open")); else { views.pick("bubbles"); bubbles.openModule(+a.getAttribute("data-open")); } return; }
    a = ev.target.closest("[data-impact]"); if (a) { ev.preventDefault(); if (current.showImpact) current.showImpact(impact(+a.getAttribute("data-impact")).ids); }
  });
  function goFn(id) { if (current.focusFn) current.focusFn(id); else describeFn(id); }

  function setControls(html) { controls.innerHTML = html || ""; }
  function setCrumbs(parts) {
    crumbs.innerHTML = parts.map(function (p, i) { return (i ? '<span class="divider">›</span>' : "") + (p.go ? '<a data-crumb="' + i + '">' + safe(p.label) + "</a>" : "<b>" + safe(p.label) + "</b>"); }).join("");
    CMX.$$("a[data-crumb]", crumbs).forEach(function (a) { a.onclick = function () { parts[+a.getAttribute("data-crumb")].go(); }; });
  }
  function linkButtons() {
    return '<button type="button" class="switch' + (state.lines ? " is-on" : "") + '" data-lines="1" aria-pressed="' + state.lines + '">All links on</button>' +
      '<button type="button" class="switch' + (state.lines ? "" : " is-on") + '" data-lines="0" aria-pressed="' + !state.lines + '">All links off</button>';
  }
  controls.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-lines]"); if (!b) return;
    state.lines = b.getAttribute("data-lines") === "1"; hold(); current.enter();
  });
  function roleToggles(after) {
    setControls('<button type="button" class="switch' + (state.tests ? " is-on" : "") + '" id="t-tests" aria-pressed="' + state.tests + '">Tests</button>' +
      '<button type="button" class="switch' + (state.stubs ? " is-on" : "") + '" id="t-stubs" aria-pressed="' + state.stubs + '">Stubs</button>' + (after || "") + linkButtons());
    $("#t-tests").onclick = function () { state.tests = !state.tests; hold(); current.enter(); };
    $("#t-stubs").onclick = function () { state.stubs = !state.stubs; hold(); current.enter(); };
  }

  /* == 1 bubbles (physics) == */
  var bubbles = (function () {
    var net = null, nodes = null, edges = null;
    function base(opts) {
      var ink = CMX.css("--text"), bg = CMX.css("--paper");
      return Object.assign({
        physics: { enabled: state.physics, solver: "barnesHut", stabilization: { iterations: 300 },
                   barnesHut: { gravitationalConstant: -9000, springLength: 140, springConstant: 0.03, damping: 0.4, avoidOverlap: 0.4 } },
        interaction: { hover: true, tooltipDelay: 120, hideEdgesOnDrag: true },
        nodes: { shape: "dot", borderWidth: 0, font: { face: "Segoe UI, system-ui, sans-serif", color: ink, size: 14, strokeWidth: 5, strokeColor: bg } },
        edges: { smooth: { type: "continuous" }, arrows: { to: { enabled: true, scaleFactor: 0.45 } }, selectionWidth: 2.5, hoverWidth: 1.5 }
      }, opts || {});
    }
    function mount(n, e, opts) {
      canvas.innerHTML = '<div class="vis"></div>';
      nodes = new vis.DataSet(n); edges = new vis.DataSet(e);
      var keep = take("bubbles"), o = base(opts);
      o.physics.stabilization = Object.assign({}, o.physics.stabilization, { fit: !keep });
      o.edges = Object.assign({}, o.edges, { hidden: !state.lines });
      net = new vis.Network(canvas.firstChild, { nodes: nodes, edges: edges }, o);
      var zoomer = CMX.visZoom(net);
      CMX.zoomButtons(canvas, zoomer);
      if (keep) net.once(state.physics ? "stabilizationIterationsDone" : "afterDrawing", function () { zoomer.setView(keep); });
      return net;
    }
    function hex(c, a) { var n = parseInt(c.slice(1), 16); return "rgba(" + (n >> 16 & 255) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + a + ")"; }
    /* a bubble that opens (double-click: a module's functions, or the module a function belongs to) carries
       an arrow going into a box in its middle; a function that is only itself carries none */
    function enterMark(ctx, x, y, s) {
      function shape() {
        ctx.beginPath();
        ctx.moveTo(x - s * 0.1, y - s * 0.72); ctx.lineTo(x + s * 0.72, y - s * 0.72);
        ctx.lineTo(x + s * 0.72, y + s * 0.72); ctx.lineTo(x - s * 0.1, y + s * 0.72);
        ctx.moveTo(x - s * 0.95, y); ctx.lineTo(x + s * 0.32, y);
        ctx.moveTo(x - s * 0.04, y - s * 0.36); ctx.lineTo(x + s * 0.32, y); ctx.lineTo(x - s * 0.04, y + s * 0.36);
      }
      var w = Math.max(1.3, s * 0.17);
      ctx.save(); ctx.lineCap = "round"; ctx.lineJoin = "round";
      ctx.strokeStyle = "rgba(0,0,0,0.38)"; ctx.lineWidth = w + 2.2; shape(); ctx.stroke();
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = w; shape(); ctx.stroke();
      ctx.restore();
    }
    function markOpenable(ids) {
      net.on("afterDrawing", function (ctx) {
        var pos = net.getPositions(ids);
        ids.forEach(function (id) {
          var node = net.body.nodes[id];
          if (!node || !pos[id]) return;
          var r = (node.shape && node.shape.radius) || node.options.size || 0;
          if (r >= 5) enterMark(ctx, pos[id].x, pos[id].y, Math.max(3.5, r * 0.5));
        });
      });
    }
    function overview() {
      state.module = null;
      var n = M.map(function (m) {
        var c = CMX.color(m.id);
        return { id: "m" + m.id, label: m.name + "\n" + m.nf, value: Math.max(1, m.nf), shape: "dot", scaling: { min: 18, max: 70, label: { enabled: true, min: 13, max: 22 } },
                 color: { background: hex(c, 0.88), border: c, highlight: { background: c, border: CMX.css("--focus") }, hover: { background: c, border: c } }, borderWidth: 2,
                 title: m.name + ": " + m.nf + " functions · double-click to open" };
      });
      var maxw = Math.max.apply(null, [1].concat(D.mod_edges.map(function (e) { return e[2]; })));
      var e = D.mod_edges.map(function (x, i) {
        return { id: "e" + i, from: "m" + x[0], to: "m" + x[1], width: 1 + 5 * Math.log(1 + x[2]) / Math.log(1 + maxw), title: x[2] + " calls",
                 color: { color: hex(CMX.color(x[0]), 0.45), highlight: CMX.css("--focus"), hover: CMX.color(x[0]) } };
      });
      mount(n, e);
      /* only a module with a function to show opens (its tests or stubs may be switched off) */
      function opens(mi) { return perModule[mi].some(function (i) { return visible(F[i]); }); }
      markOpenable(M.filter(function (m) { return opens(m.id); }).map(function (m) { return "m" + m.id; }));
      net.on("click", function (p) { if (p.nodes.length) describeModule(+p.nodes[0].slice(1)); });
      net.on("doubleClick", function (p) { if (p.nodes.length) { var mi = +p.nodes[0].slice(1); if (opens(mi)) openModule(mi); else describeModule(mi); } });
      setCrumbs([{ label: D.target.label + " · all modules" }]);
      describeOverview();
    }
    function openModule(mi) {
      state.module = mi;
      var inside = perModule[mi].filter(function (i) { return visible(F[i]); });
      var set = {}; inside.forEach(function (i) { set[i] = true; });
      var outside = {};
      inside.forEach(function (i) {
        callers[i].concat(callees[i]).forEach(function (j) { if (!set[j] && visible(F[j])) outside[j] = (outside[j] || 0) + 1; });
      });
      var ext = Object.keys(outside).map(Number).sort(function (a, b) { return outside[b] - outside[a] || a - b; }).slice(0, 150);
      ext.forEach(function (j) { set[j] = true; });
      var mc = CMX.color(mi);
      var n = inside.concat(ext).map(function (i) {
        var f = F[i], own = f.m === mi, c = own ? mc : CMX.color(f.m);
        var test = f.r === "test", stub = f.r === "stub";
        return { id: i, label: f.n, value: 1 + f.c, scaling: { min: own ? 9 : 6, max: own ? 34 : 16, label: { enabled: true, min: 11, max: 17 } },
                 color: { background: test || stub ? CMX.css("--surface") : hex(c, own ? 0.92 : 0.35), border: test ? CMX.css("--test") : stub ? CMX.css("--stub") : c,
                          highlight: { background: c, border: CMX.css("--focus") }, hover: { background: c, border: c } },
                 borderWidth: test || stub ? 2 : 1, shapeProperties: { borderDashes: stub ? [3, 2] : false },
                 font: { size: own ? 13 : 11, color: own ? CMX.css("--text") : CMX.css("--text-2") },
                 title: f.q + " · " + M[f.m].name + " · " + f.c + " callers" + (own ? "" : " · double-click to open " + M[f.m].name) };
      });
      var e = [];
      D.calls.forEach(function (c, k) {
        if (set[c[0]] && set[c[1]] && (F[c[0]].m === mi || F[c[1]].m === mi)) e.push({ id: "c" + k, from: c[0], to: c[1], color: { color: hex(CMX.color(F[c[0]].m), 0.4), highlight: CMX.css("--focus") } });
      });
      mount(n, e);
      markOpenable(ext);
      net.on("click", function (p) { if (p.nodes.length) describeFn(p.nodes[0]); });
      net.on("doubleClick", function (p) { if (p.nodes.length && F[p.nodes[0]].m !== mi) openModule(F[p.nodes[0]].m); });
      setCrumbs([{ label: D.target.label, go: overview }, { label: M[mi].name }]);
      describeModule(mi);
    }
    return {
      id: "bubbles", label: "Bubbles", title: "Modules, then a module's functions, laid out by physics",
      enter: function () {
        roleToggles('<button type="button" class="switch' + (state.physics ? " is-on" : "") + '" id="t-phys" aria-pressed="' + state.physics + '">Physics</button>');
        $("#t-phys").onclick = function () { state.physics = !state.physics; this.classList.toggle("is-on", state.physics); this.setAttribute("aria-pressed", state.physics); if (net) net.setOptions({ physics: { enabled: state.physics } }); };
        if (state.module !== null) openModule(state.module); else overview();
      },
      leave: function () { if (net) { net.destroy(); net = null; } },
      view: function () { return net ? CMX.visZoom(net).view() : null; },
      openModule: openModule,
      selectModule: function (mi) { if (net && nodes.get("m" + mi)) { net.selectNodes(["m" + mi]); net.focus("m" + mi, { scale: 1, animation: true }); } },
      select: function (id) { if (net && nodes.get(id)) net.selectNodes([id]); },
      focusFn: function (id) {
        if (state.module !== F[id].m) openModule(F[id].m);
        describeFn(id);
        if (net && nodes.get(id)) { net.selectNodes([id]); setTimeout(function () { net.focus(id, { scale: 1.2, animation: true }); }, 300); }
      },
      showImpact: function (ids) { if (net) net.selectNodes(ids.filter(function (i) { return nodes.get(i); })); }
    };
  })();

  /* == 2 drafting table (fixed) == */
  var drafting = (function () {
    var svg, pz, circles = {}, layer;
    function draw() {
      var L = D.drafting;
      svg = CMX.freshSvg(canvas);
      var defs = CMX.el("defs", {}, svg);
      var mk = CMX.el("marker", { id: "arr", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 11, markerHeight: 11, markerUnits: "userSpaceOnUse", orient: "auto-start-reverse" }, defs);
      CMX.el("path", { d: "M0,0 L10,5 L0,10 z", fill: CMX.css("--text-2") }, mk);
      var gEdges = CMX.el("g", {}, svg), gBlocks = CMX.el("g", {}, svg);
      layer = CMX.el("g", {}, svg);
      var pos = {}; L.blocks.forEach(function (b) { pos[b.m] = b; });
      var maxw = Math.max.apply(null, [1].concat(D.mod_edges.map(function (e) { return e[2]; })));
      D.mod_edges.forEach(function (e) {
        var a = pos[e[0]], b = pos[e[1]]; if (!a || !b) return;
        var x1 = a.x + a.w, y1 = a.y + Math.min(a.h / 2, 60), x2 = b.x, y2 = b.y + Math.min(b.h / 2, 60);
        if (b.x <= a.x) { x1 = a.x; x2 = b.x + b.w; }
        var p = CMX.el("path", { d: CMX.wire(x1, y1, x2, y2), class: "mod-edge", "stroke-width": (1 + 4 * Math.log(1 + e[2]) / Math.log(1 + maxw)).toFixed(2), "marker-end": "url(#arr)" }, gEdges);
        CMX.el("title", {}, p, M[e[0]].name + " → " + M[e[1]].name + ": " + e[2] + " calls");
      });
      L.blocks.forEach(function (b) {
        var m = M[b.m], g = CMX.el("g", { "data-mod": b.m }, gBlocks);
        CMX.el("rect", { x: b.x, y: b.y, width: b.w, height: b.h, rx: 10, class: "block" }, g);
        var t = CMX.el("text", { x: b.x + 14, y: b.y + 24, class: "head fixed", style: "cursor:pointer" }, g, m.name);
        CMX.el("text", { x: b.x + 14 + 8.4 * m.name.length + 10, y: b.y + 24, class: "small" }, g, m.nf + (b.hidden ? " (" + b.hidden + " not drawn)" : ""));
        t.addEventListener("click", function () { describeModule(b.m); select(null, b.m); });
      });
      circles = {};
      F.forEach(function (f) {
        var p = L.circles[String(f.id)]; if (!p || !visible(f)) return;
        var c = CMX.el("circle", { cx: p[0], cy: p[1], r: f.rad, class: "func " + (f.r === "test" ? "role-test" : f.r === "stub" ? "role-stub" : "") }, gBlocks);
        CMX.el("title", {}, c, f.q + " · " + f.c + " callers");
        c.addEventListener("click", function () { if (!svg.dataset.dragged) describeFn(f.id); });
        circles[f.id] = c;
      });
      pz = CMX.panZoom(svg, L.width, L.height);
      CMX.zoomButtons(canvas, pz);
      pz.setView(take("drafting"));
      if (!state.lines) gEdges.style.display = "none";
    }
    function select(id, mi) {
      layer.innerHTML = "";
      CMX.$$(".func", svg).forEach(function (c) { c.classList.remove("sel", "hi", "lo"); });
      CMX.$$(".block", svg).forEach(function (r) { r.classList.remove("sel"); });
      if (mi !== undefined && mi !== null) { var g = svg.querySelector('g[data-mod="' + mi + '"] rect'); if (g) g.classList.add("sel"); }
      if (id === null || id === undefined || !circles[id]) return;
      var P = D.drafting.circles;
      Object.keys(circles).forEach(function (k) { circles[k].classList.add("lo"); });
      circles[id].classList.remove("lo"); circles[id].classList.add("sel");
      function line(a, b, cls) {
        var p1 = P[String(a)], p2 = P[String(b)]; if (!p1 || !p2 || !circles[a] || !circles[b]) return;
        CMX.el("path", { d: CMX.wire(p1[0], p1[1], p2[0], p2[1]), class: "call " + cls }, layer);
        circles[a].classList.remove("lo"); circles[b].classList.remove("lo");
      }
      callers[id].forEach(function (c) { line(c, id, "in"); });
      callees[id].forEach(function (c) { line(id, c, "hot"); });
    }
    return {
      id: "drafting", label: "Drafting table", title: "Modules as blocks, functions as circles, in a fixed layout",
      enter: function () {
        roleToggles('<span class="swatches"><span><i style="width:10px;height:10px;border-radius:50%;background:var(--text)"></i>product</span><span><i style="width:10px;height:10px;border-radius:50%;border:2px solid var(--test)"></i>test</span><span><i style="width:18px;border-top:2.5px solid var(--doc)"></i>calls it</span><span><i style="width:18px;border-top:2.5px solid var(--code)"></i>it calls</span></span>');
        setCrumbs([{ label: D.target.label + " · drafting table" }]);
        draw(); if (state.fn !== null && circles[state.fn]) select(state.fn); else describeOverview();
      },
      select: function (id) { select(id, F[id] ? F[id].m : null); },
      focusFn: function (id) { describeFn(id); var p = D.drafting.circles[String(id)]; if (p) pz.center(p[0], p[1], 700); },
      selectModule: function (mi) { select(null, mi); var b = D.drafting.blocks.filter(function (x) { return x.m === mi; })[0]; if (b) pz.center(b.x + b.w / 2, b.y + b.h / 2, Math.max(700, b.w * 1.6)); },
      view: function () { return pz ? pz.view() : null; },
      showImpact: function (ids) {
        var hit = {}; ids.forEach(function (i) { hit[i] = true; });
        Object.keys(circles).forEach(function (k) { circles[k].classList.toggle("lo", !hit[k]); circles[k].classList.toggle("hi", !!hit[k]); });
      },
      onTheme: function () { draw(); }
    };
  })();

  /* == 3 metro lines == */
  var metro = (function () {
    var svg, pz, dots = {}, gLinks;
    function draw() {
      var L = D.metro;
      svg = CMX.freshSvg(canvas);
      var where = {}; L.lines.forEach(function (ln) { ln.stations.forEach(function (s) { where[s[0]] = [s[1], ln.y]; }); });
      var crossing = {}; L.links.forEach(function (k) { crossing[k[0]] = true; crossing[k[1]] = true; });
      gLinks = CMX.el("g", {}, svg);
      var gLines = CMX.el("g", {}, svg), gSt = CMX.el("g", {}, svg);
      L.links.forEach(function (k) {
        var a = where[k[0]], b = where[k[1]];
        var p = CMX.el("path", { d: "M" + a[0] + "," + a[1] + " C" + a[0] + "," + (a[1] + b[1]) / 2 + " " + b[0] + "," + (a[1] + b[1]) / 2 + " " + b[0] + "," + b[1], class: "call", "data-a": k[0], "data-b": k[1] }, gLinks);
        CMX.el("title", {}, p, F[k[0]].q + " calls " + F[k[1]].q);
      });
      L.lines.forEach(function (ln) {
        var c = CMX.color(ln.m);
        CMX.el("line", { x1: ln.x0, y1: ln.y, x2: ln.x1, y2: ln.y, stroke: c, "stroke-width": 9, "stroke-linecap": "round" }, gLines);
        var tag = CMX.el("g", { style: "cursor:pointer" }, gLines);
        var w = Math.max(70, 8.2 * M[ln.m].name.length + 22);
        CMX.el("rect", { x: ln.x0 - w - 16, y: ln.y - 13, width: w, height: 26, rx: 13, fill: c }, tag);
        CMX.el("text", { x: ln.x0 - w / 2 - 16, y: ln.y + 4.5, "text-anchor": "middle", style: "fill:#fff;font-weight:700;font-size:12.5px" }, tag, M[ln.m].name);
        tag.addEventListener("click", function () { describeModule(ln.m); });
        if (ln.more > 0) CMX.el("text", { x: ln.x1 + 18, y: ln.y + 4, class: "small" }, gLines, "+" + ln.more + " more");
        var seenName = {};
        ln.stations.forEach(function (s) { var n = F[s[0]].n; seenName[n] = (seenName[n] || 0) + 1; });
        ln.stations.forEach(function (s, i) {
          var f = F[s[0]];
          var cross = !!crossing[f.id];
          var dot = CMX.el("circle", { cx: s[1], cy: ln.y, r: cross ? 9 : 7, fill: CMX.css("--surface"), stroke: CMX.css("--text"), "stroke-width": cross ? 4 : 3, style: "cursor:pointer" }, gSt);
          CMX.el("title", {}, dot, f.q + " · " + f.c + " callers");
          dot.addEventListener("click", function () { if (!svg.dataset.dragged) describeFn(f.id); });
          dots[f.id] = dot;
          var name = f.n;
          if (seenName[f.n] > 1) { var stem = D.files[f.f].split("/").pop().replace(/\.[^.]+$/, ""); name = stem === f.n ? f.n : stem + "/" + f.n; }
          var up = i % 2 === 0, label = name.length > 18 ? name.slice(0, 17) + "…" : name;
          CMX.el("text", { x: s[1], y: ln.y + (up ? -17 : 27), "text-anchor": "middle", class: "caption fixed", style: "font-size:11px" }, gSt, label);
        });
      });
      pz = CMX.panZoom(svg, L.width, L.height);
      CMX.zoomButtons(canvas, pz);
      pz.setView(take("metro"));
      if (!state.lines) gLinks.style.display = "none";
      if (!CMX.store.get("metro-explained")) {
        var box = document.createElement("div"); box.className = "explain";
        box.innerHTML = '<button type="button" class="iconbtn" aria-label="Close">Got it</button><b>How to read the metro map.</b> Each coloured line is one module. Its stations are the module\'s functions, left to right in call order: a function sits to the right of the functions that call it. A big station has a thin link to a station on another line: that is a call from one module into another, like changing trains. Only the functions that matter on a line are drawn; the rest are counted at the end of the line.';
        box.querySelector("button").onclick = function () { CMX.store.set("metro-explained", "1"); box.remove(); };
        canvas.appendChild(box);
      }
    }
    function select(id) {
      CMX.$$("path", gLinks).forEach(function (p) {
        var a = +p.getAttribute("data-a"), b = +p.getAttribute("data-b");
        p.setAttribute("class", "call" + (a === id ? " hot" : b === id ? " in" : ""));
      });
      Object.keys(dots).forEach(function (k) { dots[k].setAttribute("stroke", +k === id ? CMX.css("--focus") : CMX.css("--text")); });
    }
    return {
      id: "metro", label: "Metro lines", title: "Each module a line, its functions the stations, calls between lines as changes",
      enter: function () {
        setControls('<span class="swatches"><span><i style="width:22px;border-top:8px solid ' + CMX.color(0) + ';border-radius:4px"></i>a module</span><span><i style="width:12px;height:12px;border-radius:50%;border:3px solid var(--text)"></i>a function</span><span><i style="width:18px;border-top:2px solid var(--text-3)"></i>a call to another module</span></span>' + linkButtons());
        setCrumbs([{ label: D.target.label + " · metro lines" }]);
        draw(); describeOverview();
      },
      select: select,
      view: function () { return pz ? pz.view() : null; },
      focusFn: function (id) { describeFn(id); var hit = null; D.metro.lines.forEach(function (ln) { ln.stations.forEach(function (s) { if (s[0] === id) hit = [s[1], ln.y]; }); }); if (hit) pz.center(hit[0], hit[1], 900); },
      onTheme: function () { draw(); }
    };
  })();

  /* == 4 zoom levels == */
  var zoom = (function () {
    var focus = null, mod = null;
    function pane(title, sub) {
      var p = document.createElement("section");
      p.style.cssText = "flex:1 1 320px;min-width:0;display:flex;flex-direction:column;border-right:1px solid var(--rule)";
      p.innerHTML = '<div style="padding:10px 14px;border-bottom:1px solid var(--rule-2);background:var(--surface-2)"><b>' + safe(title) + '</b> <span class="quiet">' + safe(sub || "") + '</span></div><div class="pane-host" style="position:relative;flex:1;min-height:380px"></div>';
      return p;
    }
    function repaint() {
      canvas.innerHTML = "";
      var wrap = document.createElement("div"); wrap.style.cssText = "position:absolute;inset:0;display:flex;flex-wrap:wrap;overflow:auto";
      canvas.appendChild(wrap);
      var p1 = pane("1 · System", "the code bases"), p2 = pane("2 · Modules", "of " + D.target.label), p3 = pane("3 · One function", "its callers and callees");
      wrap.appendChild(p1); wrap.appendChild(p2); wrap.appendChild(p3);
      drawSystem(p1.lastChild); drawModules(p2.lastChild); drawFocus(p3.lastChild);
    }
    function drawSystem(host) {
      var T = D.project.targets, svg = CMX.freshSvg(host), y = 0;
      T.forEach(function (t, i) {
        var g = CMX.el("g", { style: "cursor:pointer" }, svg), here = t.name === D.target.name;
        CMX.el("rect", { x: 0, y: y, width: 260, height: 68, rx: 10, fill: here ? CMX.css("--code-tint") : CMX.css("--surface"), stroke: here ? CMX.css("--code") : CMX.css("--text"), "stroke-width": here ? 4 : 3.5, "stroke-dasharray": null }, g);
        CMX.el("rect", { x: 5, y: y + 5, width: 250, height: 58, rx: 7, fill: "none", stroke: here ? CMX.css("--code") : CMX.css("--text"), "stroke-width": 1 }, g);
        CMX.el("text", { x: 130, y: y + 31, "text-anchor": "middle", class: "head fixed" }, g, t.label);
        CMX.el("text", { x: 130, y: y + 50, "text-anchor": "middle", class: "small" }, g, t.summary || "");
        if (!here) g.addEventListener("click", function () { location.href = "code-" + t.name + ".html#view=zoom"; });
        y += 96;
      });
      (D.project.links || []).forEach(function (l) { /* hand-written links between code bases are listed under the boxes */
        CMX.el("text", { x: 0, y: (y += 20), class: "small" }, svg, l);
      });
      var pz = CMX.panZoom(svg, 260, Math.max(y, 80));
    }
    function drawModules(host) {
      var Z = D.zoom, svg = CMX.freshSvg(host);
      var maxw = Math.max.apply(null, [1].concat(D.mod_edges.map(function (e) { return e[2]; })));
      D.mod_edges.forEach(function (e) {
        var a = Z.modules[e[0]], b = Z.modules[e[1]]; if (!a || !b) return;
        var x1 = a[0] + a[2], y1 = a[1] + a[3] / 2, x2 = b[0], y2 = b[1] + b[3] / 2;
        if (b[0] <= a[0]) { x1 = a[0]; x2 = b[0] + b[2]; }
        CMX.el("path", { d: CMX.wire(x1, y1, x2, y2), class: "mod-edge", "stroke-width": (1 + 3 * Math.log(1 + e[2]) / Math.log(1 + maxw)).toFixed(2) }, svg);
      });
      M.forEach(function (m) {
        var p = Z.modules[m.id]; if (!p) return;
        var g = CMX.el("g", { style: "cursor:pointer" }, svg), sel = mod === m.id;
        CMX.el("rect", { x: p[0], y: p[1], width: p[2], height: p[3], rx: 9, class: "block" + (sel ? " sel" : "") }, g);
        CMX.el("text", { x: p[0] + 12, y: p[1] + 22, class: "head fixed" }, g, m.name.length > 18 ? m.name.slice(0, 17) + "…" : m.name);
        CMX.el("text", { x: p[0] + 12, y: p[1] + 40, class: "small" }, g, m.nf + " functions");
        g.addEventListener("click", function () {
          if (svg.dataset.dragged) return;
          mod = m.id; describeModule(m.id);
          var top = perModule[m.id].filter(function (i) { return F[i].r !== "test"; }).sort(function (a, b) { return F[b].c - F[a].c; })[0];
          if (top !== undefined) focus = top;
          repaint();
        });
      });
      CMX.panZoom(svg, Z.width, Z.height);
    }
    function drawFocus(host) {
      if (focus === null) { host.innerHTML = '<div class="empty">Click a module in pane 2, or a function anywhere, to see it here with its callers and callees.</div>'; return; }
      var f = F[focus], svg = CMX.freshSvg(host);
      var ins = callers[focus].filter(function (i) { return visible(F[i]); }).sort(function (a, b) { return F[b].c - F[a].c; });
      var outgoing = callees[focus].filter(function (i) { return visible(F[i]); }).sort(function (a, b) { return F[b].c - F[a].c; });
      var shownIn = ins.slice(0, 8), shownOut = outgoing.slice(0, 8), rows = Math.max(shownIn.length, shownOut.length, 1);
      var H = rows * 64, cy = H / 2;
      function node(i, x, y, big) {
        var g = CMX.el("g", { style: "cursor:pointer" }, svg), q = F[i];
        var r = big ? 36 : Math.max(8, Math.min(18, q.rad + 4));
        CMX.el("circle", { cx: x, cy: y, r: r, class: "func " + (q.r === "test" ? "role-test" : q.r === "stub" ? "role-stub" : "") + (big ? " sel" : "") }, g);
        CMX.el("text", { x: x, y: y + r + 15, "text-anchor": "middle", class: "caption fixed" }, g, q.n.length > 20 ? q.n.slice(0, 19) + "…" : q.n);
        if (!big) g.addEventListener("click", function () { if (!svg.dataset.dragged) { focus = i; describeFn(i); repaint(); } });
      }
      var X0 = 50, XF = 230, X1 = 410;
      shownIn.forEach(function (i, k) { var y = (k + 0.5) * H / shownIn.length; CMX.el("path", { d: CMX.wire(X0 + 18, y, XF - 38, cy), class: "call in" }, svg); });
      shownOut.forEach(function (i, k) { var y = (k + 0.5) * H / shownOut.length; CMX.el("path", { d: CMX.wire(XF + 38, cy, X1 - 18, y), class: "call hot" }, svg); });
      shownIn.forEach(function (i, k) { node(i, X0, (k + 0.5) * H / shownIn.length); });
      shownOut.forEach(function (i, k) { node(i, X1, (k + 0.5) * H / shownOut.length); });
      node(focus, XF, cy, true);
      var note = shownIn.length + " of " + ins.length + " callers and " + shownOut.length + " of " + outgoing.length + " callees shown" + (f.ind && f.ind.length ? " · " + f.ind.length + " calls through pointers not followed" : "");
      CMX.el("text", { x: X0 - 20, y: H + 40, class: "small" }, svg, note);
      CMX.panZoom(svg, 470, H + 50);
    }
    return {
      id: "zoom", label: "Zoom levels", title: "Code bases, then modules, then one function",
      enter: function () {
        setControls('<span class="quiet">Click a module (2) to see its busiest function (3); click any circle in (3) to move along the calls.</span>');
        setCrumbs([{ label: D.target.label + " · zoom levels" }]);
        if (focus === null && state.fn !== null) focus = state.fn;
        if (focus === null && F.length) {
          /* start on the busiest product function, so pane 3 is never empty */
          var best = F.filter(function (f) { return f.r !== "test"; }).sort(function (a, b) { return (b.c + b.o) - (a.c + a.o) || a.id - b.id; })[0];
          if (best) focus = best.id;
        }
        if (mod === null && focus !== null) mod = F[focus].m;
        repaint(); if (focus !== null) describeFn(focus); else describeOverview();
      },
      focusFn: function (id) { focus = id; mod = F[id].m; describeFn(id); repaint(); },
      selectModule: function (mi) { mod = mi; repaint(); },
      onTheme: function () { repaint(); }
    };
  })();

  /* == 5 VHDL hierarchy (if any) == */
  var hierarchy = !D.vhdl ? null : (function () {
    var V = D.vhdl;
    function panel(i) {
      var e = V.entities[i];
      var link = CMX.editorLink(D.target.root, e.file, e.line);
      var children = V.edges.filter(function (x) { return x[0] === i; }), parents = V.edges.filter(function (x) { return x[1] === i; });
      side.innerHTML = '<h2 class="fixed">' + safe(e.n) + '</h2><div class="hstack"><span class="badge ' + (e.cls === "design" ? "role-product" : e.cls === "orphan" ? "bad" : "role-test") + '">' + safe(e.cls) + '</span><span class="badge">' + safe(e.r) + '</span><span class="badge">' + safe(e.m) + "</span></div>" +
        '<div class="hstack"><span class="fixed">' + safe(e.file) + ":" + e.line + "</span>" + (link ? '<a class="btn" href="' + link + '">Open in editor</a>' : "") + "</div>" +
        "<h3>Places " + children.length + "</h3><ul>" + children.map(function (k) { return "<li><span class=\"fixed\">" + safe(V.entities[k[1]].n) + "</span><span>" + k[2] + "×</span></li>"; }).join("") + "</ul>" +
        "<h3>Placed by " + parents.length + "</h3><ul>" + parents.map(function (k) { return "<li><span class=\"fixed\">" + safe(V.entities[k[0]].n) + "</span><span>" + k[2] + "×</span></li>"; }).join("") + "</ul>" +
        "<p class=\"quiet\">" + e.ports + " ports</p>";
    }
    return {
      id: "hierarchy", label: "Hierarchy", title: "VHDL entities and which entity places which",
      enter: function () {
        setControls('<span class="swatches"><span>design top: <b class="fixed">' + safe(V.summary.hdl_top || "none") + "</b></span><span>" + V.summary.entities_count + " entities, " + V.summary.instantiations_count + " placements, " + V.summary.unresolved_instances_count + " not found</span></span>");
        setCrumbs([{ label: D.target.label + " · VHDL hierarchy" }]);
        var svg = CMX.freshSvg(canvas);
        V.edges.forEach(function (x) {
          var a = V.pos[x[0]], b = V.pos[x[1]];
          CMX.el("path", { d: CMX.wire(a[0] + a[2], a[1] + a[3] / 2, b[0], b[1] + b[3] / 2), class: "mod-edge", "stroke-width": 1.5 }, svg);
        });
        V.entities.forEach(function (e, i) {
          var p = V.pos[i], g = CMX.el("g", { style: "cursor:pointer" }, svg);
          var cls = e.cls === "design" ? "block" : "block";
          CMX.el("rect", { x: p[0], y: p[1], width: p[2], height: p[3], rx: 8, class: cls, style: e.cls === "orphan" ? "stroke:var(--conflict);stroke-dasharray:5 4" : e.cls !== "design" ? "stroke:var(--test);stroke-dasharray:3 3" : "" }, g);
          CMX.el("text", { x: p[0] + p[2] / 2, y: p[1] + 25, "text-anchor": "middle", class: "caption fixed" }, g, e.n);
          g.addEventListener("click", function () { if (!svg.dataset.dragged) panel(i); });
        });
        var pz = CMX.panZoom(svg, V.width, V.height); CMX.zoomButtons(canvas, pz);
        side.innerHTML = '<h2>' + safe(D.target.label) + '</h2><p class="quiet">In VHDL the call graph is the instantiation hierarchy: which entity places which. Dashed boxes are testbenches and test support; a red dashed box is placed by nothing.</p>';
      }
    };
  })();

  /* == start up == */
  /* a code base of VHDL alone has no functions: only its hierarchy is worth a view */
  var list = F.length ? [bubbles, drafting, metro, zoom] : [];
  if (hierarchy) list.push(hierarchy);
  if (!list.length) { canvas.innerHTML = '<div class="empty">No functions or entities were found in this code base.</div>'; return; }
  var current = null;
  var views = CMX.initViews("code-" + D.target.name, list.map(function (v) {
    return { id: v.id, label: v.label, title: v.title, enter: function () { current = v; v.enter(); }, leave: v.leave };
  }));
  CMX.onTheme(function () { hold(); if (current && current.onTheme) current.onTheme(); else if (current) current.enter(); });

  $("#find").addEventListener("keydown", function (ev) {
    if (ev.key !== "Enter") return;
    var q = ev.target.value.trim().toLowerCase(); if (!q) return;
    var hit = F.filter(function (f) { return f.n.toLowerCase() === q || f.q.toLowerCase() === q; })[0] ||
      F.filter(function (f) { return f.q.toLowerCase().indexOf(q) >= 0; }).sort(function (a, b) { return b.c - a.c; })[0];
    if (hit) { if (!visible(hit)) { if (hit.r === "test") state.tests = true; if (hit.r === "stub") state.stubs = true; } goFn(hit.id); return; }
    var mh = M.filter(function (m) { return m.name.toLowerCase().indexOf(q) >= 0; })[0];
    if (mh) { describeModule(mh.id); if (current.selectModule) current.selectModule(mh.id); }
    else side.innerHTML = '<p class="quiet">Nothing called “' + safe(q) + '” in this code base.</p>';
  });
  var m = /fn=([^&]+)/.exec(location.hash);
  if (m) { var name = decodeURIComponent(m[1]); var f = F.filter(function (x) { return x.n === name || x.q === name; })[0]; if (f) goFn(f.id); CMX.dropHash("fn"); }
})();
