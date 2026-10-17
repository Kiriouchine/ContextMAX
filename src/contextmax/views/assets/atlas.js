/* ContextMAX Complete Atlas: the code, the documents and every link between them, in one drawing.

   Left, the code: every module on a wheel, sized by its functions, and inside the wheel the calls
   between modules. Right, the documents: one column per lifecycle stage. Between them, the documents
   that name code; among the documents, the links between them. Everything can be clicked: a module,
   a document, every line, and (after a double-click on a module) its functions.

   The same drawing runs live in the ContextMAX window while a build runs, filled in from the build's
   own events, and ends exactly as the Complete Atlas page draws the finished index. Positions come
   from the data alone, so the same index always gives the same picture. */
"use strict";
var CMXAtlas = (function () {
  var W = 1640, H = 1000, CX = 450, CY = 545, R0 = 345;
  var DX0 = 930, DX1 = 1600, DY0 = 236, DY1 = 975;
  var SETS = {
    calls: { color: "--code", label: "calls between modules", title: "a function of one module calls a function of another" },
    dcode: { color: "--code", label: "names code", title: "a document names functions or constants of a module" },
    vcode: { color: "--ok", label: "value in code", title: "a value a document states, found in the code of a module (red when the code has another value)" },
    quotes: { color: "--doc", dash: [5, 4], label: "document number", title: "a document quotes another document's number" },
    cites: { color: "--doc", label: "cites", title: "a document writes another document's title or file name" },
    shares: { color: "--ok", label: "shared values", title: "two documents state the same named values (red when they differ)" },
    anchor: { color: "--ok", label: "same value", title: "for a name many documents state: linked to the first document that states the same value" },
    differs: { color: "--conflict", label: "values differ", title: "most documents agree on a value; this one states another" },
    samepart: { color: "--text-3", dash: [10, 6], label: "same part", title: "about the same part of the code, next stage" },
    fcalls: { color: "--code", label: "calls", title: "a function calls another" },
    fout: { color: "--code", label: "calls out", title: "a function calls into another module" },
    fin: { color: "--text-2", dash: [6, 4], label: "called from", title: "another module calls this function" },
    fdocs: { color: "--doc", label: "names this function", title: "a document names this function" }
  };
  var DOC_ORDER = ["samepart", "anchor", "shares", "quotes", "cites", "differs"];
  var VOUT = ["match", "mismatch", "unit unknown", "units differ"];

  function lists(n) { var a = new Array(n); for (var i = 0; i < n; i++) a[i] = []; return a; }
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function ease(u) { return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; }

  /* == the data, with the lists the drawing and the clicks look things up in == */
  function emptyDocs() { return { k: [], t: [], s: [], x: [], e: [], fo: [], rel: [], p: [], tx: [], cp: [] }; }
  function model(D) {
    D = D || {};
    var m = {
      project: D.project || "", targets: D.targets || [], modules: D.modules || [], calls: D.calls || [],
      fn: D.functions || { m: [], n: [], q: [], f: [], l: [], c: [], k: [], r: [] }, files: D.files || [], fcalls: D.fcalls || [],
      stages: D.stages || [], docs: D.docs || emptyDocs(), dcode: [], fdocs: D.fdocs || [], kinds: [], links: { k: [], a: [], b: [], d: [] },
      vcode: D.vcode || []
    };
    indexCode(m); indexDocs(m);
    m.modVals = lists(m.modules.length); m.docVals = lists(m.docs.k.length);
    m.vcode.forEach(function (r, i) { if (m.modVals[r[1]]) m.modVals[r[1]].push(i); if (m.docVals[r[0]]) m.docVals[r[0]].push(i); });
    addDcode(m, D.dcode || []);
    (D.kinds || []).forEach(function (k) { kindIndex(m, k); });
    if (D.links) addLinks(m, D.links.k.map(function (k) { return D.kinds[k]; }), D.links.a, D.links.b, D.links.d);
    return m;
  }
  function indexCode(m) {
    m.modCalls = lists(m.modules.length);
    m.calls.forEach(function (c, i) { m.modCalls[c[0]].push(i); if (c[1] !== c[0]) m.modCalls[c[1]].push(i); });
    m.modFns = lists(m.modules.length);
    m.fn.m.forEach(function (mi, f) { if (mi >= 0) m.modFns[mi].push(f); });
    m.modByName = {};
    m.modules.forEach(function (x, i) { m.modByName[x[1]] = m.modByName[x[1]] === undefined ? i : m.modByName[x[1]]; });
    m.modDocs = lists(m.modules.length);
    m.dcode.forEach(function (r, i) { if (m.modDocs[r[1]]) m.modDocs[r[1]].push(i); });
  }
  function indexDocs(m) {
    var n = m.docs.k.length;
    m.docCode = lists(n); m.docLinks = lists(n); m.docMain = new Int32Array(n).fill(-1);
    m.docAt = {}; m.docs.k.forEach(function (k, i) { m.docAt[k] = i; });
    m.dcode.forEach(function (r, i) { m.docCode[r[0]].push(i); if (r[5] || m.docMain[r[0]] < 0) m.docMain[r[0]] = r[1]; });
    m.links.a.forEach(function (a, i) { m.docLinks[a].push(i); m.docLinks[m.links.b[i]].push(i); });
  }
  function kindIndex(m, k) { var i = m.kinds.indexOf(k); if (i < 0) { m.kinds.push(k); i = m.kinds.length - 1; } return i; }
  function addDcode(m, rows) {
    rows.forEach(function (r) {
      var i = m.dcode.length; m.dcode.push(r);
      if (m.modDocs[r[1]]) m.modDocs[r[1]].push(i);
      if (m.docCode[r[0]]) { m.docCode[r[0]].push(i); if (r[5] || m.docMain[r[0]] < 0) m.docMain[r[0]] = r[1]; }
    });
  }
  function addLinks(m, kinds, a, b, d) {
    for (var j = 0; j < a.length; j++) {
      var i = m.links.k.length;
      m.links.k.push(kindIndex(m, kinds[j])); m.links.a.push(a[j]); m.links.b.push(b[j]); m.links.d.push(d ? d[j] : null);
      if (m.docLinks[a[j]]) m.docLinks[a[j]].push(i);
      if (m.docLinks[b[j]]) m.docLinks[b[j]].push(i);
    }
  }

  /* == where everything goes: worked out from the data alone == */
  function groupKey(name) {
    if (name.indexOf("/") >= 0) return name.split("/")[0];
    var cut = name.search(/[_\-.]/);
    return cut > 0 ? name.slice(0, cut) : name;
  }
  function layout(m) {
    var L = { mod: [], doc: [], heads: [], groups: [], targets: [], pitch: 10, size: 6, rmax: 8, cols: [] };
    var n = m.modules.length;
    if (n) {
      var fmax = 1; m.modules.forEach(function (x) { fmax = Math.max(fmax, x[2]); });
      var rmax = n <= 12 ? 30 : n <= 40 ? 20 : n <= 120 ? 12 : n <= 400 ? 8 : n <= 1200 ? 5 : 3.5;
      var multi = m.targets.length > 1, slots = n + (multi ? 2 * m.targets.length : 0);
      var rings = clamp(Math.ceil(slots * (2 * rmax + 3) / (2 * Math.PI * R0)), 1, 6);
      var radii = []; for (var k = 0; k < rings; k++) radii.push(R0 - k * (2.4 * rmax + 6));
      var slot = 0, prevT = -1, tStart = {};
      m.modules.forEach(function (x, i) {
        if (multi && x[0] !== prevT) { slot += prevT === -1 ? 1 : 2; prevT = x[0]; tStart[x[0]] = slot; }
        var a = -Math.PI / 2 + 2 * Math.PI * (slot + 0.5) / slots, r = radii[i % rings];
        L.mod.push({ x: CX + r * Math.cos(a), y: CY + r * Math.sin(a), r: Math.max(2, rmax * (0.42 + 0.58 * Math.sqrt(x[2] / fmax))), a: a });
        slot++;
      });
      L.rmax = rmax;
      if (n <= 40) {
        m.modules.forEach(function (x, i) { L.groups.push({ a: L.mod[i].a, text: x[1], r: R0 + rmax + 14 }); });
      } else {
        var byGroup = {};
        m.modules.forEach(function (x, i) { var g = x[0] + "|" + groupKey(x[1]); (byGroup[g] = byGroup[g] || { text: groupKey(x[1]), a: [] }).a.push(L.mod[i].a); });
        Object.keys(byGroup).forEach(function (g) {
          var G = byGroup[g]; if (G.a.length < 2 && n > 120) return;
          var sx = 0, sy = 0; G.a.forEach(function (a) { sx += Math.cos(a); sy += Math.sin(a); });
          L.groups.push({ a: Math.atan2(sy, sx), text: G.text, r: R0 + rmax + 16 });
        });
      }
      if (multi) m.targets.forEach(function (t, ti) {
        var a = -Math.PI / 2 + 2 * Math.PI * (tStart[ti] - 0.5) / slots;
        L.targets.push({ a: a, text: t.label, r: R0 + rmax + 42 });
      });
    }
    var S = m.stages.length, nd = m.docs.k.length;
    if (S && nd) {
      var cols = lists(S);
      for (var d = 0; d < nd; d++) cols[m.docs.s[d]].push(d);
      cols.forEach(function (c) {
        c.sort(function (a, b) {
          var ma = m.docMain[a], mb = m.docMain[b];
          if ((ma < 0) !== (mb < 0)) return ma < 0 ? 1 : -1;
          if (ma !== mb) return ma - mb;
          var ta = m.docs.t[a].toLowerCase(), tb = m.docs.t[b].toLowerCase();
          return ta < tb ? -1 : ta > tb ? 1 : a - b;
        });
      });
      var gap = 14, colW = (DX1 - DX0 - gap * (S - 1)) / S, availH = DY1 - DY0, most = 1;
      cols.forEach(function (c) { most = Math.max(most, c.length); });
      L.doc = new Array(nd);
      if (most * 18 <= availH) {
        /* few documents: one per row, each with its title */
        var py = Math.min(40, Math.floor(availH / most));
        L.pitch = py; L.size = Math.min(13, py * 0.6); L.titles = true; L.titleW = colW - L.size - 6;
        cols.forEach(function (c, s) {
          var left = DX0 + s * (colW + gap);
          L.cols.push({ x0: left, x1: left + colW });
          L.heads.push({ x: left + colW / 2, text: m.stages[s], count: c.length });
          c.forEach(function (d, i) { L.doc[d] = { x: left + L.size / 2 + 1, y: DY0 + i * py + py / 2 }; });
        });
      } else {
        var p = clamp(Math.floor(Math.sqrt(colW * availH / most)), 3, 34);
        while (p > 3 && Math.ceil(most / Math.max(1, Math.floor(colW / p))) * p > availH) p--;
        var perRow = Math.max(1, Math.floor(colW / p));
        L.pitch = p; L.size = Math.max(2.2, p * 0.72); L.titleW = p - 6;
        cols.forEach(function (c, s) {
          var left = DX0 + s * (colW + gap);
          L.cols.push({ x0: left, x1: left + colW });
          L.heads.push({ x: left + colW / 2, text: m.stages[s], count: c.length });
          c.forEach(function (d, i) { L.doc[d] = { x: left + (i % perRow) * p + p / 2, y: DY0 + Math.floor(i / perRow) * p + p / 2 }; });
        });
      }
    }
    return L;
  }

  /* == the geometry of each kind of line, in drawing units == */
  function quad(a, c, b, out) { out.push(a.x, a.y, c.x, c.y, b.x, b.y); }
  function geom(set, i, m, L, D) {
    var g = [], a, b;
    if (set === "calls") {
      var c = m.calls[i]; a = L.mod[c[0]]; b = L.mod[c[1]]; if (!a || !b) return null;
      var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      quad(a, { x: mx + (CX - mx) * 0.72, y: my + (CY - my) * 0.72 }, b, g); return { t: "q", p: g };
    }
    if (set === "dcode" || set === "vcode") {
      var r = m[set][i]; a = L.doc[r[0]]; b = L.mod[r[1]]; if (!a || !b) return null;
      return { t: "c", p: [a.x, a.y, a.x - 260, a.y, CX + (b.x - CX) * 1.65, CY + (b.y - CY) * 1.65, b.x, b.y] };
    }
    if (set === "fcalls" || set === "fout" || set === "fin" || set === "fdocs") {
      var e = D.edges[set][i]; a = e.from; b = e.to;
      if (set === "fdocs") return { t: "c", p: [a.x, a.y, a.x - 240, a.y, CX + (b.x - CX) * 1.9, CY + (b.y - CY) * 1.9, b.x, b.y] };
      var qx = (a.x + b.x) / 2, qy = (a.y + b.y) / 2, pull = set === "fcalls" ? 0.6 : 0.25;
      quad(a, { x: qx + (CX - qx) * pull, y: qy + (CY - qy) * pull }, b, g); return { t: "q", p: g };
    }
    a = L.doc[m.links.a[i]]; b = L.doc[m.links.b[i]]; if (!a || !b) return null;
    if (Math.abs(a.x - b.x) < (L.titles ? 2 : L.pitch * 6)) {
      var x = Math.max(a.x, b.x) + (L.titles ? -14 : 18) - Math.abs(a.y - b.y) * (L.titles ? 0.22 : -0.16);
      quad(a, { x: x, y: (a.y + b.y) / 2 }, b, g); return { t: "q", p: g };
    }
    /* across columns: a shallow arch, so a line between documents on one row does not hide behind them */
    quad(a, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - Math.abs(a.x - b.x) * 0.14 }, b, g); return { t: "q", p: g };
  }
  function trace(ctx, G) {
    var p = G.p; ctx.moveTo(p[0], p[1]);
    if (G.t === "l") ctx.lineTo(p[2], p[3]);
    else if (G.t === "q") ctx.quadraticCurveTo(p[2], p[3], p[4], p[5]);
    else ctx.bezierCurveTo(p[2], p[3], p[4], p[5], p[6], p[7]);
  }
  function sample(G) {
    var p = G.p, pts = [], k, t, u;
    if (G.t === "l") return p.slice();
    var steps = G.t === "q" ? 8 : 12;
    for (k = 0; k <= steps; k++) {
      t = k / steps; u = 1 - t;
      if (G.t === "q") pts.push(u * u * p[0] + 2 * u * t * p[2] + t * t * p[4], u * u * p[1] + 2 * u * t * p[3] + t * t * p[5]);
      else pts.push(u * u * u * p[0] + 3 * u * u * t * p[2] + 3 * u * t * t * p[4] + t * t * t * p[6],
                    u * u * u * p[1] + 3 * u * u * t * p[3] + 3 * u * t * t * p[5] + t * t * t * p[7]);
    }
    return pts;
  }
  function segDist(px, py, ax, ay, bx, by) {
    var dx = bx - ax, dy = by - ay, l = dx * dx + dy * dy, t = l ? clamp(((px - ax) * dx + (py - ay) * dy) / l, 0, 1) : 0;
    var x = ax + t * dx - px, y = ay + t * dy - py; return x * x + y * y;
  }

  /* == the drawing == */
  function create(host, opts) {
    opts = opts || {};
    var canvas = document.createElement("canvas"); canvas.className = "atlas-canvas";
    canvas.setAttribute("aria-label", "Complete Atlas: code modules on the left, documents by lifecycle stage on the right, and the links between them");
    canvas.tabIndex = 0;
    host.appendChild(canvas);
    var tip = document.createElement("div"); tip.className = "atlas-tip"; tip.hidden = true; host.appendChild(tip);
    var ctx = canvas.getContext("2d");
    var S = { m: model({}), L: layout(model({})), view: { s: 1, x: 0, y: 0 }, dpr: 1, on: {}, sel: null, hover: null, drill: null,
              layers: {}, layerView: null, interacting: false, dirty: true, live: null, tween: null, moved: false };
    var C = {};
    function colors() { ["--paper", "--surface", "--text", "--text-2", "--text-3", "--doc", "--doc-ink", "--code", "--code-tint", "--ok", "--conflict", "--rule", "--focus", "--doc-tint"].forEach(function (k) { C[k] = getComputedStyle(document.documentElement).getPropertyValue(k).trim(); }); }
    colors();
    Object.keys(SETS).forEach(function (k) { S.on[k] = k !== "samepart" && k !== "anchor"; });
    if (opts.on) Object.keys(opts.on).forEach(function (k) { S.on[k] = opts.on[k]; });

    function size() {
      var r = host.getBoundingClientRect();
      S.dpr = Math.min(1.5, window.devicePixelRatio || 1);
      canvas.width = Math.max(1, Math.round(r.width * S.dpr)); canvas.height = Math.max(1, Math.round(r.height * S.dpr));
      canvas.style.width = r.width + "px"; canvas.style.height = r.height + "px";
      if (!S.moved) fit(); else dropLayers();          /* a view the viewer moved stays where it is */
      S.dirty = true;
    }
    function fit() {
      /* the drawing spans x 0..W and y 90..H, plus room on the left for the names around the wheel */
      var cw = canvas.width / S.dpr, ch = canvas.height / S.dpr, x0 = -70, y0 = 90;
      var s = Math.min(cw / (W - x0 + 20), ch / (H - y0 + 30));
      S.view = { s: s, x: (cw - (W - x0) * s) / 2 - x0 * s, y: (ch - (H - y0) * s) / 2 - y0 * s + 4 };
      S.moved = false; dropLayers(); S.dirty = true;
    }
    function toScreen(x, y) { return [x * S.view.s + S.view.x, y * S.view.s + S.view.y]; }
    function toWorld(px, py) { return [(px - S.view.x) / S.view.s, (py - S.view.y) / S.view.s]; }

    /* -- which lines exist, kind by kind -- */
    function setsShown() {
      if (S.drill) return ["fcalls", "fout", "fin", "fdocs"].filter(function (k) { return S.on[k] !== false; });
      if (S.live && S.live.inbox) return S.on.calls ? ["calls"] : [];
      var out = [];
      DOC_ORDER.forEach(function (k) { if (S.on[k] && S.m.kinds.indexOf(k) >= 0) out.push(k); });
      S.m.kinds.forEach(function (k) { if (DOC_ORDER.indexOf(k) < 0 && S.on[k] !== false) out.push(k); });
      if (S.on.calls) out.push("calls");
      if (S.on.dcode) out.push("dcode");
      if (S.on.vcode && S.m.vcode.length) out.push("vcode");
      return out;
    }
    function items(set) {
      if (S.drill) return S.drill.edges[set] ? S.drill.edges[set].length : 0;
      if (set === "calls") return S.m.calls.length;
      if (set === "dcode") return S.m.dcode.length;
      if (set === "vcode") return S.m.vcode.length;
      return S.m.links.k.length;
    }
    function inSet(set, i) {
      if (S.drill || set === "calls" || set === "dcode" || set === "vcode") return true;
      return S.m.kinds[S.m.links.k[i]] === set;
    }
    var counts = {};
    function countOf(set) {
      if (counts[set] !== undefined) return counts[set];
      if (S.drill || set === "calls" || set === "dcode" || set === "vcode") return items(set);
      var ki = S.m.kinds.indexOf(set), n = 0; S.m.links.k.forEach(function (k) { if (k === ki) n++; }); counts[set] = n; return n;
    }
    function alphaOf(set, i) {
      var n = Math.max(1, countOf(set));
      if (set === "calls") return clamp(6 / Math.sqrt(n), 0.03, 0.8) * (0.45 + 0.55 * Math.min(1, Math.log(1 + S.m.calls[i][2]) / 5));
      if (set === "differs") return clamp(14 / Math.sqrt(n), 0.1, 0.85);
      if (set === "vcode") return clamp(14 / Math.sqrt(n), 0.2, 0.9);
      if (set === "dcode" || set === "fdocs") return clamp(7 / Math.sqrt(n), 0.03, 0.7);
      return clamp(7 / Math.sqrt(n), 0.02, 0.7);
    }
    function widthOf(set) { var n = countOf(set); return n < 150 ? 1.5 : n < 3000 ? 1.1 : 0.8; }
    function colorOf(set, i) {
      if (set === "shares" || set === "anchor") { var d = S.m.links.d[i]; return d && d[2] ? C["--conflict"] : C["--ok"]; }
      if (set === "vcode") { var o = S.m.vcode[i][2]; return o === 1 || o === 3 ? C["--conflict"] : o === 2 ? C["--text-3"] : C["--ok"]; }
      return C[SETS[set] ? SETS[set].color : "--text-3"];
    }

    /* -- layers: lines already drawn at the current view; a pan or zoom reuses them until it rests -- */
    function dropLayers() { Object.keys(S.layers).forEach(function (k) { S.layers[k].n = 0; S.layers[k].valid = false; }); S.layerView = null; }
    function layer(set) {
      var l = S.layers[set];
      if (!l) { l = S.layers[set] = { c: document.createElement("canvas"), n: 0, valid: false }; l.x = l.c.getContext("2d"); }
      if (l.c.width !== canvas.width || l.c.height !== canvas.height) { l.c.width = canvas.width; l.c.height = canvas.height; l.n = 0; l.valid = false; }
      return l;
    }
    function drawInto(set, l, from, to) {
      var x = l.x, k = S.view.s * S.dpr, st = SETS[set] || {};
      x.setTransform(k, 0, 0, k, S.view.x * S.dpr, S.view.y * S.dpr);
      x.lineWidth = widthOf(set) / S.view.s;
      x.setLineDash(st.dash ? st.dash.map(function (v) { return v / S.view.s; }) : []);
      var lastC = null, lastA = -1;
      for (var i = from; i < to; i++) {
        if (!inSet(set, i)) continue;
        var G = geom(set, i, S.m, S.L, S.drill); if (!G) continue;
        var c = colorOf(set, i), a = alphaOf(set, i);
        if (c !== lastC || Math.abs(a - lastA) > 0.01) {
          if (lastC !== null) x.stroke();
          x.strokeStyle = c; x.globalAlpha = a; lastC = c; lastA = a; x.beginPath();
        }
        trace(x, G);
      }
      if (lastC !== null) x.stroke();
      x.globalAlpha = 1; x.setLineDash([]);
    }
    function syncLayers() {
      var v = S.view, same = S.layerView && S.layerView.s === v.s && S.layerView.x === v.x && S.layerView.y === v.y;
      if (!same) { Object.keys(S.layers).forEach(function (k) { var l = S.layers[k]; l.x.setTransform(1, 0, 0, 1, 0, 0); l.x.clearRect(0, 0, l.c.width, l.c.height); l.n = 0; }); S.layerView = { s: v.s, x: v.x, y: v.y }; }
      setsShown().forEach(function (set) {
        var l = layer(set), n = items(set), cnt = countOf(set);
        /* lines are fainter the more there are: when a kind has grown by half since its lines were drawn
           (the live build), all of them are drawn again at the strength the final count gives */
        if (l.n > n || (l.n && cnt > l.basis * 1.5)) { l.x.setTransform(1, 0, 0, 1, 0, 0); l.x.clearRect(0, 0, l.c.width, l.c.height); l.n = 0; }
        if (!l.n) l.basis = cnt;
        if (l.n < n) { drawInto(set, l, l.n, n); l.n = n; }
      });
    }

    /* -- one frame -- */
    function frame() {
      var now = performance.now(), anim = false;
      if (S.tween) { S.tween.u = clamp((now - S.tween.t0) / S.tween.dur, 0, 1); if (S.tween.u < 1) anim = true; else S.tween = null; }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = C["--paper"]; ctx.fillRect(0, 0, canvas.width, canvas.height);
      var lines = !S.tween;
      if (lines) {
        if (S.interacting && S.layerView) {
          var k = S.view.s / S.layerView.s;
          ctx.setTransform(k, 0, 0, k, (S.view.x - S.layerView.x * k) * S.dpr, (S.view.y - S.layerView.y * k) * S.dpr);
        } else syncLayers();
        ctx.globalAlpha = S.sel ? 0.16 : 1;
        setsShown().forEach(function (set) { if (S.layers[set]) ctx.drawImage(S.layers[set].c, 0, 0); });
        ctx.globalAlpha = 1;
      }
      ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
      if (lines && S.sel) highlight();
      nodes();
      labels();
      if (S.live && S.live.gate) gateSweep(now);
      if (anim || (S.live && S.live.gate)) S.dirty = true;
    }
    function loop() { if (S.dirty) { S.dirty = false; frame(); } requestAnimationFrame(loop); }

    function dot(x, y, s) { var p = toScreen(x, y); ctx.rect(p[0] - s / 2, p[1] - s / 2, s, s); }
    function nodes() {
      var m = S.m, L = S.L, k = S.view.s, live = S.live;
      if (live && live.inbox) { inboxDots(); return; }
      var tw = S.tween ? ease(S.tween.u) : 1;
      var near = S.sel ? selectedNodes() : null;
      if (S.drill) { drillNodes(near); }
      else {
        ctx.lineWidth = 1.2;
        L.mod.forEach(function (p, i) {
          var q = toScreen(p.x, p.y), r = Math.max(1.5, p.r * k);
          if (S.tween && S.tween.mod) r *= clamp((tw * 1.4) - i / L.mod.length * 0.4, 0, 1);
          ctx.globalAlpha = near && !near.mod[i] ? 0.25 : 1;
          ctx.beginPath(); ctx.arc(q[0], q[1], r, 0, Math.PI * 2);
          ctx.fillStyle = S.sel && S.sel.t === "mod" && S.sel.i === i ? C["--code"] : C["--surface"]; ctx.fill();
          ctx.strokeStyle = C["--code"]; ctx.stroke();
        });
        ctx.globalAlpha = 1;
      }
      var size = Math.max(1.6, L.size * k), nd = m.docs.k.length;
      var groups = { hi: [], code: [], plain: [], dim: [] };
      for (var d = 0; d < nd; d++) {
        var to = L.doc[d]; if (!to) continue;
        var x = to.x, y = to.y;
        if (S.tween && S.tween.from && S.tween.from[d]) { var f = S.tween.from[d]; x = f.x + (to.x - f.x) * tw; y = f.y + (to.y - f.y) * tw; }
        var g = near ? (near.doc[d] ? "hi" : "dim") : (m.docCode[d].length || (S.drill && S.drill.docs[d]) ? "code" : "plain");
        if (S.drill && !near && !S.drill.docs[d]) g = "dim";
        groups[g].push(x, y);
      }
      [["dim", C["--doc"], 0.18], ["plain", C["--doc"], 0.42], ["code", C["--doc"], 0.92], ["hi", C["--doc"], 1]].forEach(function (z) {
        var arr = groups[z[0]]; if (!arr.length) return;
        ctx.globalAlpha = z[2]; ctx.fillStyle = z[1]; ctx.beginPath();
        for (var i = 0; i < arr.length; i += 2) dot(arr[i], arr[i + 1], size);
        ctx.fill();
      });
      ctx.globalAlpha = 1;
      if (S.sel && S.sel.t === "doc" && L.doc[S.sel.i]) ring(L.doc[S.sel.i], size / 2 + 3);
      if (S.hover && S.hover.t === "doc" && L.doc[S.hover.i]) ring(L.doc[S.hover.i], size / 2 + 2, true);
      if (S.hover && S.hover.t === "mod" && !S.drill && L.mod[S.hover.i]) ring(L.mod[S.hover.i], L.mod[S.hover.i].r * k + 3, true);
      if (L.titles || L.pitch * k >= 70) docTitles(near);
    }
    function ring(p, r, soft) {
      var q = toScreen(p.x, p.y); ctx.beginPath(); ctx.arc(q[0], q[1], r, 0, Math.PI * 2);
      ctx.strokeStyle = C["--focus"]; ctx.lineWidth = soft ? 1.5 : 2.5; ctx.stroke();
    }
    function docTitles(near) {
      var L = S.L, k = S.view.s, cw = canvas.width / S.dpr, ch = canvas.height / S.dpr, w = L.titleW * k;
      if (w < 24) return;
      ctx.font = "11px 'IBM Plex Sans', 'Segoe UI', sans-serif"; ctx.fillStyle = C["--text"];
      ctx.textBaseline = L.titles ? "middle" : "top";
      S.m.docs.t.forEach(function (t, d) {
        var p = L.doc[d]; if (!p) return; var q = toScreen(p.x, p.y);
        if (q[0] < -w || q[0] > cw || q[1] < -20 || q[1] > ch) return;
        var s = t;
        if (ctx.measureText(s).width > w) {
          var lo = 0, hi = s.length;
          while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (ctx.measureText(t.slice(0, mid) + "…").width <= w) lo = mid; else hi = mid - 1; }
          s = t.slice(0, lo) + "…";
        }
        ctx.globalAlpha = near && !near.doc[d] ? 0.35 : 1;
        if (L.titles) ctx.fillText(s, q[0] + L.size * k / 2 + 5, q[1]);
        else ctx.fillText(s, q[0] - w / 2, q[1] + L.size * k / 2 + 3);
      });
      ctx.globalAlpha = 1; ctx.textBaseline = "alphabetic";
    }
    function labels() {
      var L = S.L, k = S.view.s;
      ctx.textAlign = "left"; ctx.fillStyle = C["--text-2"]; ctx.font = "600 13px 'IBM Plex Sans', 'Segoe UI', sans-serif";
      var t1 = toScreen(CX - R0, 120), t2 = toScreen(DX0, 120);
      if (S.m.modules.length || S.m.docs.k.length) {
        if (S.m.modules.length) ctx.fillText(S.drill ? "CODE · " + S.m.modules[S.drill.mi][1] + " · " + S.drill.fns.length + " functions" :
          "CODE · " + S.m.modules.length.toLocaleString("en-US") + " modules", t1[0], t1[1]);
        if (S.m.docs.k.length) ctx.fillText("DOCUMENTS · " + S.m.docs.k.length.toLocaleString("en-US") + " by lifecycle stage", t2[0], t2[1]);
      }
      ctx.font = "500 12px 'IBM Plex Sans', 'Segoe UI', sans-serif"; ctx.textAlign = "center";
      L.heads.forEach(function (h) {
        var q = toScreen(h.x, DY0); ctx.fillStyle = C["--text-2"]; ctx.fillText(h.text, q[0], q[1] - 22);
        ctx.fillStyle = C["--text-3"]; ctx.font = "11px 'IBM Plex Mono', Consolas, monospace";
        ctx.fillText(h.count.toLocaleString("en-US"), q[0], q[1] - 7); ctx.font = "500 12px 'IBM Plex Sans', 'Segoe UI', sans-serif";
      });
      if (!S.drill) {
        ctx.fillStyle = C["--text-3"];
        /* names around the wheel: just outside its outer edge, pushed outwards in screen pixels so that
           no zoom level puts them on the circles */
        var edge = R0 + L.rmax;
        ctx.textBaseline = "middle";
        L.groups.forEach(function (g) {
          var c = Math.cos(g.a), s = Math.sin(g.a), q = toScreen(CX + edge * c, CY + edge * s);
          ctx.textAlign = c > 0.3 ? "left" : c < -0.3 ? "right" : "center";
          ctx.fillText(g.text, q[0] + c * 10, q[1] + s * 16);
        });
        ctx.font = "600 12px 'IBM Plex Sans', 'Segoe UI', sans-serif"; ctx.fillStyle = C["--text-2"];
        L.targets.forEach(function (g) {
          var c = Math.cos(g.a), s = Math.sin(g.a), q = toScreen(CX + edge * c, CY + edge * s);
          ctx.textAlign = c > 0.3 ? "left" : c < -0.3 ? "right" : "center";
          ctx.fillText(g.text, q[0] + c * 34, q[1] + s * 40);
        });
        ctx.textBaseline = "alphabetic";
        if (L.rmax * k >= 9 && S.m.modules.length > 40) {
          ctx.font = "11px 'IBM Plex Sans', 'Segoe UI', sans-serif"; ctx.fillStyle = C["--text"];
          L.mod.forEach(function (p, i) { var q = toScreen(p.x, p.y); ctx.textAlign = "center"; ctx.fillText(S.m.modules[i][1], q[0], q[1] - p.r * k - 4); });
        }
      }
      ctx.textAlign = "left";
    }

    /* -- what a selection touches, drawn on top of the faded rest -- */
    function selectedNodes() {
      var m = S.m, out = { mod: {}, doc: {}, fn: {} }, sel = S.sel;
      if (S.drill) {
        if (sel.t === "fn") { out.fn[sel.i] = 1; incident().forEach(function (e) { mark(e.e.fromRef, out); mark(e.e.toRef, out); }); }
        else if (sel.t === "doc") { out.doc[sel.i] = 1; incident().forEach(function (e) { mark(e.e.fromRef, out); mark(e.e.toRef, out); }); }
        else if (sel.t === "edge") { var e = S.drill.edges[sel.set][sel.i]; mark(e.fromRef, out); mark(e.toRef, out); }
        else if (sel.t === "nmod") out.mod[sel.i] = 1;
        return out;
      }
      if (sel.t === "mod") {
        out.mod[sel.i] = 1;
        m.modCalls[sel.i].forEach(function (c) { out.mod[m.calls[c][0]] = 1; out.mod[m.calls[c][1]] = 1; });
        m.modDocs[sel.i].forEach(function (r) { out.doc[m.dcode[r][0]] = 1; });
        if (S.on.vcode) m.modVals[sel.i].forEach(function (r) { out.doc[m.vcode[r][0]] = 1; });
      } else if (sel.t === "doc") {
        out.doc[sel.i] = 1;
        m.docCode[sel.i].forEach(function (r) { out.mod[m.dcode[r][1]] = 1; });
        if (S.on.vcode) m.docVals[sel.i].forEach(function (r) { out.mod[m.vcode[r][1]] = 1; });
        m.docLinks[sel.i].forEach(function (l) { if (S.on[m.kinds[m.links.k[l]]]) { out.doc[m.links.a[l]] = 1; out.doc[m.links.b[l]] = 1; } });
      } else if (sel.t === "edge") {
        if (sel.set === "calls") { out.mod[m.calls[sel.i][0]] = 1; out.mod[m.calls[sel.i][1]] = 1; }
        else if (sel.set === "dcode" || sel.set === "vcode") { out.doc[m[sel.set][sel.i][0]] = 1; out.mod[m[sel.set][sel.i][1]] = 1; }
        else { out.doc[m.links.a[sel.i]] = 1; out.doc[m.links.b[sel.i]] = 1; }
      }
      return out;
    }
    function mark(ref, out) { if (!ref) return; out[ref.t === "nmod" ? "mod" : ref.t][ref.i] = 1; }
    function incident() {
      var m = S.m, sel = S.sel, out = [];
      if (!sel) return out;
      if (S.drill) {
        Object.keys(S.drill.edges).forEach(function (set) {
          if (S.on[set] === false) return;
          S.drill.edges[set].forEach(function (e, i) {
            var hit = sel.t === "edge" ? (sel.set === set && sel.i === i) : (e.fromRef && e.fromRef.t === sel.t && e.fromRef.i === sel.i) || (e.toRef && e.toRef.t === sel.t && e.toRef.i === sel.i);
            if (hit) out.push({ set: set, i: i, e: e });
          });
        });
        return out;
      }
      if (sel.t === "mod") {
        if (S.on.calls) m.modCalls[sel.i].forEach(function (c) { out.push({ set: "calls", i: c }); });
        if (S.on.dcode) m.modDocs[sel.i].forEach(function (r) { out.push({ set: "dcode", i: r }); });
        if (S.on.vcode) m.modVals[sel.i].forEach(function (r) { out.push({ set: "vcode", i: r }); });
      } else if (sel.t === "doc") {
        if (S.on.dcode) m.docCode[sel.i].forEach(function (r) { out.push({ set: "dcode", i: r }); });
        if (S.on.vcode) m.docVals[sel.i].forEach(function (r) { out.push({ set: "vcode", i: r }); });
        m.docLinks[sel.i].forEach(function (l) { var k = m.kinds[m.links.k[l]]; if (S.on[k]) out.push({ set: k, i: l }); });
      } else if (sel.t === "edge") out.push({ set: sel.set, i: sel.i });
      return out;
    }
    function highlight() {
      var k = S.view.s;
      ctx.setTransform(k * S.dpr, 0, 0, k * S.dpr, S.view.x * S.dpr, S.view.y * S.dpr);
      incident().forEach(function (h) {
        var G = geom(h.set, h.i, S.m, S.L, S.drill); if (!G) return;
        ctx.beginPath(); trace(ctx, G);
        ctx.strokeStyle = colorOf(h.set, h.i); ctx.globalAlpha = 0.95;
        ctx.lineWidth = (S.sel.t === "edge" ? 3 : 1.6) / k; ctx.setLineDash((SETS[h.set] && SETS[h.set].dash || []).map(function (v) { return v / k; }));
        ctx.stroke();
      });
      ctx.setLineDash([]); ctx.globalAlpha = 1;
      ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    }

    /* -- a module opened: its functions on a ring, the modules it talks to around them -- */
    function openModule(mi) {
      var m = S.m, fns = m.modFns[mi].slice();
      fns.sort(function (a, b) { return m.fn.f[a] - m.fn.f[b] || m.fn.l[a] - m.fn.l[b]; });
      var at = {}, n = fns.length, rF = clamp(n * 7 / (2 * Math.PI), 130, 330);
      var pos = fns.map(function (f, i) { var a = -Math.PI / 2 + 2 * Math.PI * (i + 0.5) / Math.max(1, n); at[f] = i; return { x: CX + rF * Math.cos(a), y: CY + rF * Math.sin(a), a: a }; });
      var inside = [], outAgg = {}, inAgg = {};
      m.fcalls.forEach(function (c) {
        var a = at[c[0]], b = at[c[1]];
        if (a !== undefined && b !== undefined) { if (a !== b) inside.push([a, b]); }
        else if (a !== undefined) { var om = m.fn.m[c[1]]; if (om >= 0) { var key = a + ":" + om; outAgg[key] = (outAgg[key] || 0) + 1; } }
        else if (b !== undefined) { var im = m.fn.m[c[0]]; if (im >= 0) { var key2 = im + ":" + b; inAgg[key2] = (inAgg[key2] || 0) + 1; } }
      });
      var near = {};
      Object.keys(outAgg).concat(Object.keys(inAgg)).forEach(function (k, j) { near[j < Object.keys(outAgg).length ? +k.split(":")[1] : +k.split(":")[0]] = 1; });
      var others = Object.keys(near).map(Number).sort(function (a, b) { return a - b; }), onum = {};
      var opos = others.map(function (o, j) { var a = -Math.PI / 2 + 2 * Math.PI * (j + 0.5) / Math.max(1, others.length); onum[o] = j; return { x: CX + (rF + 95) * Math.cos(a), y: CY + (rF + 95) * Math.sin(a), a: a, mi: o }; });
      var D = { mi: mi, fns: fns, pos: pos, others: opos, edges: { fcalls: [], fout: [], fin: [], fdocs: [] }, docs: {},
                fr: clamp(0.38 * 2 * Math.PI * rF / Math.max(1, n), 1.2, 9), rF: rF };
      inside.forEach(function (c) { D.edges.fcalls.push({ from: pos[c[0]], to: pos[c[1]], fromRef: { t: "fn", i: c[0] }, toRef: { t: "fn", i: c[1] } }); });
      Object.keys(outAgg).sort().forEach(function (k) { var p = k.split(":").map(Number); D.edges.fout.push({ from: pos[p[0]], to: opos[onum[p[1]]], n: outAgg[k], fromRef: { t: "fn", i: p[0] }, toRef: { t: "nmod", i: onum[p[1]] } }); });
      Object.keys(inAgg).sort().forEach(function (k) { var p = k.split(":").map(Number); D.edges.fin.push({ from: opos[onum[p[0]]], to: pos[p[1]], n: inAgg[k], fromRef: { t: "nmod", i: onum[p[0]] }, toRef: { t: "fn", i: p[1] } }); });
      m.fdocs.forEach(function (r) {
        var i = at[r[0]]; if (i === undefined || !S.L.doc[r[1]]) return;
        D.edges.fdocs.push({ from: S.L.doc[r[1]], to: pos[i], n: r[2], fromRef: { t: "doc", i: r[1] }, toRef: { t: "fn", i: i } }); D.docs[r[1]] = 1;
      });
      S.drill = D; S.sel = null; S.hover = null; tip.hidden = true; dropLayers(); S.dirty = true;
      if (opts.onMode) opts.onMode(D);
    }
    function closeModule() { if (!S.drill) return; var mi = S.drill.mi; S.drill = null; S.sel = { t: "mod", i: mi }; dropLayers(); S.dirty = true; if (opts.onMode) opts.onMode(null); if (opts.onSelect) opts.onSelect(S.sel); }
    function drillNodes(near) {
      var D = S.drill, k = S.view.s, m = S.m, r = Math.max(1.5, D.fr * k);
      var ring0 = toScreen(CX, CY);
      ctx.beginPath(); ctx.arc(ring0[0], ring0[1], 26 * k, 0, Math.PI * 2); ctx.fillStyle = C["--code-tint"]; ctx.fill();
      ctx.fillStyle = C["--text"]; ctx.font = "600 13px 'IBM Plex Sans', 'Segoe UI', sans-serif"; ctx.textAlign = "center";
      ctx.fillText(m.modules[D.mi][1], ring0[0], ring0[1] + 4);
      var roomO = 2 * Math.PI * (D.rF + 95) * k / Math.max(1, D.others.length);
      D.others.forEach(function (o, j) {
        var q = toScreen(o.x, o.y); ctx.globalAlpha = near && !near.mod[j] ? 0.3 : 1;
        ctx.beginPath(); ctx.arc(q[0], q[1], Math.min(7, Math.max(2.5, roomO * 0.35)), 0, Math.PI * 2); ctx.fillStyle = C["--surface"]; ctx.fill(); ctx.strokeStyle = C["--text-3"]; ctx.lineWidth = 1.2; ctx.stroke();
        if (roomO < 13 && !(near && near.mod[j])) return;
        ctx.fillStyle = C["--text-2"]; ctx.font = "11px 'IBM Plex Sans', 'Segoe UI', sans-serif";
        ctx.textAlign = Math.cos(o.a) > 0.3 ? "left" : Math.cos(o.a) < -0.3 ? "right" : "center";
        ctx.fillText(m.modules[o.mi][1], q[0] + Math.cos(o.a) * 12, q[1] + Math.sin(o.a) * 12 + 4);
      });
      D.pos.forEach(function (p, i) {
        var q = toScreen(p.x, p.y), f = D.fns[i], role = m.fn.r[f];
        ctx.globalAlpha = near && !near.fn[i] ? 0.22 : 1;
        ctx.beginPath(); ctx.arc(q[0], q[1], r, 0, Math.PI * 2);
        ctx.fillStyle = S.sel && S.sel.t === "fn" && S.sel.i === i ? C["--code"] : role === "product" ? C["--text"] : C["--surface"]; ctx.fill();
        if (role !== "product") { ctx.strokeStyle = C["--text-3"]; ctx.lineWidth = 1.2; ctx.stroke(); }
      });
      ctx.globalAlpha = 1;
      var roomF = 2 * Math.PI * D.rF * k / Math.max(1, D.fns.length);
      if (roomF >= 12 || near) {
        ctx.font = "11px 'IBM Plex Mono', Consolas, monospace"; ctx.fillStyle = C["--text-2"];
        D.pos.forEach(function (p, i) {
          if (roomF < 12 && !near.fn[i]) return;
          var q = toScreen(p.x, p.y), name = m.fn.q[D.fns[i]] || m.fn.n[D.fns[i]];
          ctx.textAlign = Math.cos(p.a) > 0.3 ? "left" : Math.cos(p.a) < -0.3 ? "right" : "center";
          ctx.fillText(name.length > 28 ? name.slice(0, 27) + "…" : name, q[0] + Math.cos(p.a) * (r + 5), q[1] + Math.sin(p.a) * (r + 5) + 4);
        });
      }
      if (S.hover && S.hover.t === "fn") ring(D.pos[S.hover.i], r + 3, true);
      ctx.textAlign = "left";
    }

    /* -- finding what is under the pointer: nodes first, then the nearest line -- */
    var grid = null;
    function buildGrid() {
      var L = S.L, cell = Math.max(8, L.pitch * 3); grid = { cell: cell, map: {} };
      L.doc.forEach(function (p, d) { if (!p) return; var key = Math.floor(p.x / cell) + ":" + Math.floor(p.y / cell); (grid.map[key] = grid.map[key] || []).push(d); });
    }
    function pickNode(wx, wy, tolPx) {
      var k = S.view.s, tol = tolPx / k, best = null, bd = Infinity;
      if (S.drill) {
        var r = Math.max(S.drill.fr, 1.5 / k) + tol;
        S.drill.pos.forEach(function (p, i) { var d = (p.x - wx) * (p.x - wx) + (p.y - wy) * (p.y - wy); if (d < r * r && d < bd) { bd = d; best = { t: "fn", i: i }; } });
        S.drill.others.forEach(function (p, j) { var d = (p.x - wx) * (p.x - wx) + (p.y - wy) * (p.y - wy); var rr = 8 / k + tol; if (d < rr * rr && d < bd) { bd = d; best = { t: "nmod", i: j }; } });
      } else {
        S.L.mod.forEach(function (p, i) { var d = (p.x - wx) * (p.x - wx) + (p.y - wy) * (p.y - wy), rr = p.r + tol; if (d < rr * rr && d < bd) { bd = d; best = { t: "mod", i: i }; } });
      }
      if (best) return best;
      if (!grid) buildGrid();
      var cx = Math.floor(wx / grid.cell), cy = Math.floor(wy / grid.cell), half = S.L.size / 2 + tol;
      for (var dx = -1; dx <= 1; dx++) for (var dy = -1; dy <= 1; dy++) {
        (grid.map[(cx + dx) + ":" + (cy + dy)] || []).forEach(function (d) {
          var p = S.L.doc[d], ex = Math.abs(p.x - wx), ey = Math.abs(p.y - wy);
          if (ex <= half && ey <= half && ex + ey < bd) { bd = ex + ey; best = { t: "doc", i: d }; }
        });
      }
      return best;
    }
    var boxes = {};
    function pickLine(wx, wy, tolPx) {
      var tol = tolPx / S.view.s, tol2 = tol * tol, best = null, bd = tol2;
      setsShown().forEach(function (set) {
        var key = (S.drill ? "d" + S.drill.mi + ":" : "") + set, B = boxes[key], n = items(set);
        if (!B || B.n !== n) {
          B = boxes[key] = { n: n, pts: new Array(n), bb: new Float32Array(n * 4) };
          for (var i = 0; i < n; i++) {
            if (!inSet(set, i)) { B.bb[i * 4] = Infinity; continue; }
            var G = geom(set, i, S.m, S.L, S.drill); if (!G) { B.bb[i * 4] = Infinity; continue; }
            var pts = sample(G), x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
            for (var j = 0; j < pts.length; j += 2) { x0 = Math.min(x0, pts[j]); x1 = Math.max(x1, pts[j]); y0 = Math.min(y0, pts[j + 1]); y1 = Math.max(y1, pts[j + 1]); }
            B.pts[i] = pts; B.bb[i * 4] = x0; B.bb[i * 4 + 1] = y0; B.bb[i * 4 + 2] = x1; B.bb[i * 4 + 3] = y1;
          }
        }
        for (var q = 0; q < n; q++) {
          var b = q * 4;
          if (wx < B.bb[b] - tol || wx > B.bb[b + 2] + tol || wy < B.bb[b + 1] - tol || wy > B.bb[b + 3] + tol) continue;
          var P = B.pts[q];
          for (var s = 0; s + 3 < P.length; s += 2) {
            var dd = segDist(wx, wy, P[s], P[s + 1], P[s + 2], P[s + 3]);
            if (dd < bd) { bd = dd; best = { t: "edge", set: set, i: q }; }
          }
        }
      });
      return best;
    }
    function pick(px, py, lines) {
      var w = toWorld(px, py);
      return pickNode(w[0], w[1], 3) || (lines ? pickLine(w[0], w[1], 5) : null);
    }

    /* -- pointer, wheel and keys -- */
    var drag = null, lastHover = 0;
    function local(ev) { var r = canvas.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; }
    canvas.addEventListener("pointerdown", function (ev) { if (ev.button !== 0) return; var p = local(ev); drag = { x: p[0], y: p[1], vx: S.view.x, vy: S.view.y, moved: false }; canvas.setPointerCapture(ev.pointerId); });
    canvas.addEventListener("pointermove", function (ev) {
      var p = local(ev);
      if (drag) {
        if (Math.abs(p[0] - drag.x) + Math.abs(p[1] - drag.y) > 4) drag.moved = true;
        if (drag.moved) { S.view.x = drag.vx + p[0] - drag.x; S.view.y = drag.vy + p[1] - drag.y; S.moved = S.interacting = true; tip.hidden = true; S.dirty = true; }
        return;
      }
      var now = performance.now(); if (now - lastHover < 50) return; lastHover = now;
      var h = pick(p[0], p[1], !S.tween);
      var same = h && S.hover && h.t === S.hover.t && h.i === S.hover.i && h.set === S.hover.set;
      if (!same) { S.hover = h; S.dirty = true; }
      if (h) { var t = describe(S.m, S.drill, h); if (t) { tip.textContent = t; tip.hidden = false; tip.style.left = Math.min(p[0] + 14, host.clientWidth - 300) + "px"; tip.style.top = (p[1] + 14) + "px"; } else tip.hidden = true; }
      else tip.hidden = true;
      canvas.style.cursor = h ? "pointer" : "grab";
    });
    canvas.addEventListener("pointerleave", function () { if (!drag) { S.hover = null; tip.hidden = true; S.dirty = true; } });
    canvas.addEventListener("pointerup", function (ev) {
      var p = local(ev), moved = drag && drag.moved; drag = null;
      if (moved) { settle(); return; }
      var h = pick(p[0], p[1], !S.tween);
      select(h && h.t === "nmod" ? { t: "mod", i: S.drill.others[h.i].mi, fromDrill: true } : h);
    });
    canvas.addEventListener("dblclick", function (ev) {
      var p = local(ev), h = pick(p[0], p[1], false);
      if (h && h.t === "mod" && !S.drill && S.m.modFns[h.i] && S.m.modFns[h.i].length) openModule(h.i);
      else if (h && h.t === "nmod") { var mi = S.drill.others[h.i].mi; closeModule(); openModule(mi); }
    });
    var settleTimer = null;
    function settle() { clearTimeout(settleTimer); settleTimer = setTimeout(function () { S.interacting = false; S.dirty = true; }, 140); }
    function zoomAt(f, px, py) {
      var s = clamp(S.view.s * f, 0.15, 60); f = s / S.view.s;
      S.view.x = px - (px - S.view.x) * f; S.view.y = py - (py - S.view.y) * f; S.view.s = s; S.moved = true;
      S.interacting = true; tip.hidden = true; S.dirty = true; settle();
    }
    canvas.addEventListener("wheel", function (ev) { ev.preventDefault(); var p = local(ev); zoomAt(ev.deltaY > 0 ? 1 / 1.18 : 1.18, p[0], p[1]); }, { passive: false });
    canvas.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { if (S.sel) select(null); else closeModule(); }
      else if (ev.key === "+" || ev.key === "=") zoomAt(1.25, canvas.clientWidth / 2, canvas.clientHeight / 2);
      else if (ev.key === "-") zoomAt(1 / 1.25, canvas.clientWidth / 2, canvas.clientHeight / 2);
    });
    function select(sel) {
      if (sel && sel.fromDrill) { closeModule(); sel = { t: "mod", i: sel.i }; }
      S.sel = sel || null; S.dirty = true;
      if (opts.onSelect) opts.onSelect(S.sel);
    }
    function center(x, y, s) {
      var cw = canvas.width / S.dpr, ch = canvas.height / S.dpr;
      if (s) S.view.s = s;
      S.moved = true;
      S.view.x = cw / 2 - x * S.view.s; S.view.y = ch / 2 - y * S.view.s; dropLayers(); S.dirty = true;
    }

    /* -- the build, as it happens: the window feeds the events the build prints (util.live). Code files and
       documents wait in two trays while they are read; the modules then take their places on the wheel, the
       documents their stage columns, and the lines arrive kind by kind. The last event leaves exactly the
       drawing the Complete Atlas page makes from the finished index. -- */
    function fresh() { S.drill = null; S.sel = null; S.hover = null; S.tween = null; grid = null; boxes = {}; counts = {}; dropLayers(); S.dirty = true; }
    var live = {
      begin: function () {
        S.live = { inbox: true, codeTotal: 0, codeRead: 0, keys: [], read: 0, gate: null };
        S.m = model({}); S.L = layout(S.m); fresh();
      },
      codeFiles: function (n) { S.live.codeTotal += n; S.dirty = true; },
      codeRead: function (n) { S.live.codeRead = Math.min(S.live.codeTotal, S.live.codeRead + n); S.dirty = true; },
      docList: function (keys, read) { S.live.keys = keys; S.live.read = read; S.dirty = true; },
      read: function (n) { S.live.read = n; S.dirty = true; },
      code: function (c) {
        S.m = model({ targets: c.targets, modules: c.modules, calls: c.calls });
        S.live.codeRead = S.live.codeTotal; S.L = layout(S.m); fresh();
        S.tween = { t0: performance.now(), dur: 1100, u: 0, mod: true };
      },
      stages: function (d) {
        var before = inboxDocPositions();
        S.m.stages = d.stages; S.m.docs = d.docs; S.m.dcode = []; S.m.kinds = []; S.m.links = { k: [], a: [], b: [], d: [] };
        indexCode(S.m); indexDocs(S.m); S.L = layout(S.m); S.live.inbox = false; fresh();
        var from = new Array(d.docs.k.length);
        d.docs.k.forEach(function (key, i) { if (before[key]) from[i] = before[key]; });
        S.tween = { t0: performance.now(), dur: 1200, u: 0, from: from };
      },
      dcode: function (rows) { addDcode(S.m, rows); counts = {}; boxes = {}; S.dirty = true; },
      placed: function () {
        /* the documents that name code move beside it: each column sorted by the module it names most */
        var old = S.L; S.L = layout(S.m); fresh();
        S.tween = { t0: performance.now(), dur: 1000, u: 0, from: old.doc.slice() };
      },
      links: function (ev) {
        addLinks(S.m, ev.k.map(function (i) { return ev.kinds[i]; }), ev.a, ev.b, ev.d);
        counts = {}; boxes = {}; S.dirty = true;
      },
      gate: function (state) {
        S.live.gate = state === "checking" ? { t0: performance.now() } : null;
        counts = {}; dropLayers(); S.dirty = true;
      },
      done: function () { S.live.gate = null; counts = {}; boxes = {}; grid = null; dropLayers(); S.dirty = true; },
      busy: function () { return !!S.tween; },
      model: function () { return S.m; }
    };
    function inboxGrid(n, x0, x1, y0) {
      var pitch = clamp(Math.floor(Math.sqrt((x1 - x0) * 420 / Math.max(1, n))), 3, 22), per = Math.max(1, Math.floor((x1 - x0) / pitch));
      return { pitch: pitch, at: function (i) { return { x: x0 + (i % per) * pitch + pitch / 2, y: y0 + Math.floor(i / per) * pitch + pitch / 2 }; } };
    }
    function inboxDocPositions() {
      var out = {}, g = inboxGrid(S.live.keys.length, DX0, DX1, 330);
      S.live.keys.forEach(function (key, i) { out[key] = g.at(i); });
      return out;
    }
    function tray(g, from, to, color, alpha) {
      if (to <= from) return;
      var k = S.view.s, s = Math.max(1.4, g.pitch * 0.62 * k);
      ctx.fillStyle = color; ctx.globalAlpha = alpha; ctx.beginPath();
      for (var i = from; i < to; i++) { var p = g.at(i); dot(p.x, p.y, s); }
      ctx.fill(); ctx.globalAlpha = 1;
    }
    function inboxDots() {
      var lv = S.live, k = S.view.s, nd = lv.keys.length, nm = S.m.modules.length;
      ctx.font = "600 13px 'IBM Plex Sans', 'Segoe UI', sans-serif"; ctx.fillStyle = C["--text-2"]; ctx.textAlign = "left";
      var t1 = toScreen(70, 300), t2 = toScreen(DX0, 300);
      if (lv.codeTotal && !nm) ctx.fillText("CODE FILES · " + lv.codeTotal.toLocaleString("en-US") + " · read " + lv.codeRead.toLocaleString("en-US"), t1[0], t1[1]);
      if (nd) ctx.fillText("DOCUMENTS · " + nd.toLocaleString("en-US") + " · read " + Math.min(lv.read, nd).toLocaleString("en-US"), t2[0], t2[1]);
      var fade = nm ? (S.tween && S.tween.mod ? 1 - ease(S.tween.u) : 0) : 1;
      if (fade > 0 && lv.codeTotal) {
        var gc = inboxGrid(lv.codeTotal, 70, 790, 330);
        tray(gc, 0, lv.codeRead, C["--code"], 0.8 * fade);
        tray(gc, lv.codeRead, lv.codeTotal, C["--text-3"], 0.4 * fade);
      }
      if (nd) {
        var gd = inboxGrid(nd, DX0, DX1, 330);
        tray(gd, 0, Math.min(lv.read, nd), C["--doc"], 0.85);
        tray(gd, Math.min(lv.read, nd), nd, C["--text-3"], 0.4);
      }
      if (nm) {
        ctx.lineWidth = 1.2; ctx.strokeStyle = C["--code"];
        var tw = S.tween && S.tween.mod ? ease(S.tween.u) : 1;
        S.L.mod.forEach(function (p, i) {
          var g = clamp(tw * 1.4 - i / nm * 0.4, 0, 1); if (g <= 0) return;
          var q = toScreen(p.x, p.y); ctx.beginPath(); ctx.arc(q[0], q[1], Math.max(1.5, p.r * k * g), 0, Math.PI * 2);
          ctx.fillStyle = C["--surface"]; ctx.fill(); ctx.stroke();
        });
      }
    }
    function gateSweep(now) {
      /* the validation gate at work: a band passes over everything the build made */
      var u = ((now - S.live.gate.t0) / 1500) % 1, x = DX1 + 20 - u * (DX1 + 20 - (CX - R0 - 30));
      var q = toScreen(x, 130), q2 = toScreen(x, DY1);
      ctx.globalAlpha = 0.85; ctx.fillStyle = C["--ok"]; ctx.fillRect(q[0] - 1, q[1], 3, q2[1] - q[1]);
      ctx.globalAlpha = 0.12; ctx.fillRect(q[0], q[1], 40 * S.view.s, q2[1] - q[1]); ctx.globalAlpha = 1;
    }

    var ro = window.ResizeObserver ? new ResizeObserver(function () { size(); }) : null;
    if (ro) ro.observe(host); else window.addEventListener("resize", size);
    if (window.CMX && CMX.onTheme) CMX.onTheme(function () { colors(); dropLayers(); S.dirty = true; });
    size(); requestAnimationFrame(loop);
    return {
      setData: function (D) { S.m = model(D); S.L = layout(S.m); S.live = null; S.drill = null; S.sel = null; grid = null; boxes = {}; counts = {}; dropLayers(); S.dirty = true; },
      model: function () { return S.m; }, layoutOf: function () { return S.L; },
      select: select, selected: function () { return S.sel; }, open: openModule, close: closeModule, drilled: function () { return S.drill; },
      fit: fit, center: center, screenOf: toScreen, zoom: function (f) { zoomAt(f, canvas.clientWidth / 2, canvas.clientHeight / 2); },
      setOn: function (k, v) { S.on[k] = v; counts = {}; S.dirty = true; if (!S.sel) return; if (opts.onSelect) opts.onSelect(S.sel); },
      isOn: function (k) { return !!S.on[k]; },
      redraw: function () { colors(); dropLayers(); S.dirty = true; },
      live: live
    };
  }

  /* == what the pointer is on, in one line: the hover tip on the page and in the live build == */
  function setName(set) { return SETS[set] ? SETS[set].label : set; }
  function describe(m, Dr, h) {
    if (h.t === "mod") return m.modules[h.i][1] + " · " + m.modules[h.i][2] + " functions · " + m.modDocs[h.i].length + " documents name it";
    if (h.t === "doc") return m.docs.t[h.i] + " · " + m.stages[m.docs.s[h.i]];
    if (h.t === "fn") { var f = Dr.fns[h.i]; return (m.fn.q[f] || m.fn.n[f]) + " · " + m.fn.c[f] + " callers"; }
    if (h.t === "nmod") return m.modules[Dr.others[h.i].mi][1] + " (double-click to open)";
    if (h.t === "edge") return edgeText(m, Dr, h);
    return "";
  }
  function edgeText(m, Dr, h) {
    var set = h.set, i = h.i;
    if (set === "calls") { var c = m.calls[i]; return m.modules[c[0]][1] + " calls " + m.modules[c[1]][1] + " · " + c[2] + " call" + (c[2] === 1 ? "" : "s"); }
    if (set === "dcode") { var r = m.dcode[i]; return m.docs.t[r[0]] + " names " + m.modules[r[1]][1] + " · " + r[2] + " name" + (r[2] === 1 ? "" : "s"); }
    if (set === "vcode") { var v = m.vcode[i]; return (v[3] || v[5]) + ": " + v[4] + " in " + m.docs.t[v[0]] + ", " + v[6] + " in " + v[5] + " · " + VOUT[v[2]]; }
    if (Dr) {
      var e = Dr.edges[set][i];
      var nm = function (ref) { return ref.t === "fn" ? (m.fn.q[Dr.fns[ref.i]] || m.fn.n[Dr.fns[ref.i]]) : ref.t === "doc" ? m.docs.t[ref.i] : m.modules[Dr.others[ref.i].mi][1]; };
      return nm(e.fromRef) + " → " + nm(e.toRef) + (e.n ? " · " + e.n : "");
    }
    var a = m.docs.t[m.links.a[i]], b = m.docs.t[m.links.b[i]], dt = m.links.d[i];
    var extra = set === "cites" ? " · " + dt + "×" : set === "quotes" ? " · " + dt : set === "samepart" ? " · " + dt :
      (set === "shares" || set === "anchor") && dt ? " · " + dt[0] + " values" + (dt[2] ? ", " + dt[2] + " differ" : "") :
      set === "differs" && dt && dt.length ? " · " + dt[0][0] + ": " + dt[0][1] + " vs " + dt[0][2] : "";
    return a + " → " + b + " · " + setName(set) + extra;
  }

  /* == the Complete Atlas page: the drawing, the drawer, the switches, the search == */
  function page() {
    var D = CMX.pageData(), safe = CMX.safe, $ = CMX.$, side = $("#drawer"), controls = $("#controls"), crumbs = $("#crumbs");
    var host = $("#canvas"), views = $("#views");
    if (views) views.style.display = "none";
    var A = create(host, { onSelect: show, onMode: mode });
    CMXAtlas.current = A;
    A.setData(D);
    var m = A.model();
    var targetName = function (mi) { return (m.targets[m.modules[mi][0]] || {}).name; };
    var name = setName;
    function docLink(d) { return '<a href="#" data-doc="' + d + '">' + safe(m.docs.t[d]) + "</a>"; }
    /* a code base's file or folder on this PC (a shared copy has no paths: no buttons then) */
    function codePath(ti, rel) {
      var t = m.targets[ti] || {};
      return t.root ? t.root.replace(/[\\\/]+$/, "") + (rel ? "\\" + rel.replace(/\//g, "\\") : "") : "";
    }
    function modLink(mi) { return '<a href="#" data-mod="' + mi + '">' + safe(m.modules[mi][1]) + "</a>"; }
    function overview() {
      var c = D.counts;
      side.innerHTML = "<h2>Complete Atlas</h2><p class=\"quiet\">" + CMX.num(c.modules) + " modules with " + CMX.num(c.functions) + " functions, " +
        CMX.num(c.documents) + " documents, and every link between them.</p>" +
        "<h3>Lines</h3><ul>" + legendRows() + "</ul>" +
        '<div class="remark">Click a module, a document or a line to see what it connects. Double-click a module to open it: its functions, the modules it calls and is called from, and the documents that name each function. Drag to move, scroll to zoom, Esc to step back.</div>';
    }
    function legendRows() {
      var rows = [["calls", m.calls.length], ["dcode", m.dcode.length], ["vcode", m.vcode.length]];
      m.kinds.forEach(function (k, i) { rows.push([k, (D.counts.links || {})[k] || 0]); });
      return rows.filter(function (r) { return r[1]; }).map(function (r) {
        return "<li><span>" + swatch(r[0]) + safe(name(r[0])) + "</span><span>" + CMX.num(r[1]) + "</span></li>";
      }).join("");
    }
    function valueRow(v, other) {
      var bad = v[2] === 1 || v[2] === 3;
      return '<li style="display:block">' + (other === "doc" ? docLink(v[0]) : modLink(v[1])) + '<br><span class="fixed" style="font-size:12.5px">' +
        safe(v[3] || v[5]) + ": " + safe(v[4]) + " · code " + safe(v[5]) + " = " + safe(v[6]) + '</span> <span style="font-size:12.5px;' + (bad ? "color:var(--conflict);font-weight:600" : "") + '">' + safe(VOUT[v[2]]) + "</span></li>";
    }
    function swatch(set) {
      var st = SETS[set] || {}, col = "var(" + (st.color || "--text-3") + ")";
      return '<i style="display:inline-block;width:20px;vertical-align:middle;margin-right:7px;border-top:' + (st.dash ? "2px dashed " : "2.5px solid ") + col + '"></i>';
    }
    function show(sel) {
      if (!sel) { overview(); return; }
      var h = "", t = sel.t;
      if (t === "mod") {
        var mi = sel.i, x = m.modules[mi], tn = targetName(mi);
        h += "<h2>" + safe(x[1]) + '</h2><div class="hstack"><span class="badge is-code">module</span>' + (x[4] ? '<span class="badge">' + safe(x[4]) + "</span>" : "") + "</div>";
        h += '<p class="quiet">' + CMX.num(x[2]) + " functions in " + CMX.num(x[3]) + " files" + (m.targets.length > 1 ? " · " + safe(m.targets[x[0]].label) : "") + "</p>";
        var opened = A.drilled() && A.drilled().mi === mi;
        h += '<div class="hstack">' + (opened ? '<button type="button" class="btn" data-back="1">Back to all modules</button>' :
             x[2] ? '<button type="button" class="btn" data-open="' + mi + '">Open its functions</button>' : "") +
             '<a class="btn ghost" href="code-' + safe(tn) + '.html#view=bubbles">Code page</a>' +
             (codePath(x[0], x[5]) ? '<button type="button" class="btn ghost" data-file="' + safe(codePath(x[0], x[5])) + '" data-how="open">Open its folder</button>' : "") + "</div>";
        var outs = [], ins = [];
        m.modCalls[mi].forEach(function (c) { var r = m.calls[c]; if (r[0] === mi) outs.push(r); else ins.push(r); });
        outs.sort(function (a, b) { return b[2] - a[2]; }); ins.sort(function (a, b) { return b[2] - a[2]; });
        if (outs.length) h += "<h3>Calls into</h3><ul>" + outs.slice(0, 15).map(function (r) { return "<li>" + modLink(r[1]) + "<span>" + CMX.num(r[2]) + "</span></li>"; }).join("") + "</ul>";
        if (ins.length) h += "<h3>Called from</h3><ul>" + ins.slice(0, 15).map(function (r) { return "<li>" + modLink(r[0]) + "<span>" + CMX.num(r[2]) + "</span></li>"; }).join("") + "</ul>";
        if (m.modVals[mi].length) h += "<h3>Values documents state, in this module · " + CMX.num(m.modVals[mi].length) + "</h3><ul>" + m.modVals[mi].slice(0, 40).map(function (r) { return valueRow(m.vcode[r], "doc"); }).join("") + "</ul>";
        var ds = m.modDocs[mi].map(function (r) { return m.dcode[r]; }).sort(function (a, b) { return b[2] - a[2]; });
        h += "<h3>Documents that name it · " + CMX.num(ds.length) + "</h3>" + (ds.length ? "<ul>" + ds.slice(0, 40).map(function (r) {
          return "<li>" + docLink(r[0]) + "<span>" + r[2] + " name" + (r[2] === 1 ? "" : "s") + "</span></li>"; }).join("") + "</ul>" : '<p class="quiet">None.</p>');
      } else if (t === "doc") {
        var d = sel.i;
        h += "<h2>" + safe(m.docs.t[d]) + '</h2><div class="hstack"><span class="badge is-doc">' + safe(m.stages[m.docs.s[d]]) + "</span>" +
             (m.docs.e[d] ? '<span class="badge">' + safe(m.docs.e[d]) + "</span>" : "") + (m.docs.cp[d] > 1 ? '<span class="badge">' + m.docs.cp[d] + " copies</span>" : "") + "</div>";
        h += '<p class="quiet" style="font-size:12.5px">' + safe(m.docs.fo[d]) + " › " + safe(m.docs.rel[d]) + "</p>";
        var acts = [];
        if (m.docs.p[d]) { acts.push('<button type="button" class="btn" data-file="' + safe(m.docs.p[d]) + '" data-how="open">Open document</button>'); acts.push('<button type="button" class="btn ghost" data-file="' + safe(m.docs.p[d]) + '" data-how="select">Show in folder</button>'); }
        acts.push('<a class="btn ghost" href="documents.html#doc=' + encodeURIComponent(m.docs.k[d]) + '">Documents page</a>');
        h += '<div class="hstack">' + acts.join("") + "</div>";
        var cs = m.docCode[d].map(function (r) { return m.dcode[r]; });
        if (cs.length) h += "<h3>Names code</h3><ul>" + cs.map(function (r) {
          var tn2 = targetName(r[1]);
          return "<li>" + modLink(r[1]) + "<span>" + ["one name", "some names", "strong"][r[3]] + "</span></li>" +
            '<li style="display:block;font-size:12.5px" class="fixed">' + r[4].map(function (s) { return '<a href="code-' + safe(tn2) + ".html#fn=" + encodeURIComponent(s[0]) + '">' + safe(s[0]) + "</a>"; }).join(", ") + "</li>";
        }).join("") + "</ul>";
        if (m.docVals[d].length) h += "<h3>Its values in the code · " + CMX.num(m.docVals[d].length) + "</h3><ul>" + m.docVals[d].map(function (r) { return valueRow(m.vcode[r], "mod"); }).join("") + "</ul>";
        var by = {};
        m.docLinks[d].forEach(function (l) { var k = m.kinds[m.links.k[l]]; (by[k] = by[k] || []).push(l); });
        Object.keys(by).forEach(function (k) {
          h += "<h3>" + swatch(k) + safe(name(k)) + " · " + CMX.num(by[k].length) + "</h3><ul>" + by[k].slice(0, 25).map(function (l) {
            var other = m.links.a[l] === d ? m.links.b[l] : m.links.a[l];
            return "<li>" + docLink(other) + '<span><a href="#" data-edge="' + k + ":" + l + '">details</a></span></li>';
          }).join("") + (by[k].length > 25 ? '<li><span class="quiet">and ' + CMX.num(by[k].length - 25) + " more</span></li>" : "") + "</ul>";
        });
      } else if (t === "fn") {
        var Dr = A.drilled(), f = Dr.fns[sel.i], fname = m.fn.q[f] || m.fn.n[f], tn3 = targetName(Dr.mi);
        h += "<h2>" + safe(fname) + '</h2><div class="hstack"><span class="badge is-code">function</span><span class="badge">' + safe(m.fn.r[f]) + "</span></div>";
        h += '<p class="quiet fixed" style="font-size:12.5px">' + safe(m.files[m.fn.f[f]][1]) + " · line " + m.fn.l[f] + "</p>";
        h += '<p class="quiet">' + CMX.num(m.fn.c[f]) + " callers · calls " + CMX.num(m.fn.k[f]) + "</p>";
        var fr = m.files[m.fn.f[f]], fp = codePath(fr[0], fr[1]), ed = CMX.editorLink((m.targets[fr[0]] || {}).root, fr[1], m.fn.l[f]);
        h += '<div class="hstack">' + (ed ? '<a class="btn" href="' + safe(ed) + '">Open in editor</a>' : "") +
             (fp ? '<button type="button" class="btn ghost" data-file="' + safe(fp) + '" data-how="select">Show in folder</button>' : "") +
             '<a class="btn ghost" href="code-' + safe(tn3) + ".html#fn=" + encodeURIComponent(m.fn.n[f]) + '">Code page</a></div>';
        var named = Dr.edges.fdocs.filter(function (e) { return e.toRef.i === sel.i; });
        h += "<h3>Documents that name it · " + named.length + "</h3>" + (named.length ? "<ul>" + named.map(function (e) { return "<li>" + docLink(e.fromRef.i) + "<span>" + e.n + "×</span></li>"; }).join("") + "</ul>" : '<p class="quiet">None.</p>');
      } else if (t === "edge") {
        h += edgeDrawer(sel);
      }
      side.innerHTML = h;
    }
    function edgeDrawer(sel) {
      var set = sel.set, i = sel.i, h = "<h2>" + swatch(set) + safe(name(set)) + '</h2><p class="quiet">' + safe((SETS[set] || {}).title || "") + "</p>";
      if (set === "calls") {
        var c = m.calls[i];
        h += "<ul><li>" + modLink(c[0]) + "<span>calls</span></li><li>" + modLink(c[1]) + "<span>" + CMX.num(c[2]) + " calls</span></li></ul>";
        var ex = [];
        for (var q = 0; q < m.fcalls.length && ex.length < 12; q++) { var p = m.fcalls[q]; if (m.fn.m[p[0]] === c[0] && m.fn.m[p[1]] === c[1]) ex.push(p); }
        if (ex.length) h += "<h3>For example</h3><ul>" + ex.map(function (p) { return '<li class="fixed" style="font-size:12.5px"><span>' + safe(m.fn.q[p[0]] || m.fn.n[p[0]]) + "</span><span>" + safe(m.fn.q[p[1]] || m.fn.n[p[1]]) + "</span></li>"; }).join("") + "</ul>";
        return h;
      }
      if (set === "vcode") {
        var v = m.vcode[i];
        h += "<ul><li>" + docLink(v[0]) + "<span>" + safe(v[4]) + "</span></li><li>" + modLink(v[1]) + "<span class=\"fixed\">" + safe(v[5]) + " = " + safe(v[6]) + "</span></li></ul>";
        h += "<p><b" + (v[2] === 1 || v[2] === 3 ? ' style="color:var(--conflict)"' : "") + ">" + safe(VOUT[v[2]]) + "</b>: " + safe(v[7]) + "</p>";
        if (v[3]) h += '<p class="quiet">Value name: <b>' + safe(v[3]) + "</b>. The values page compares every place it is stated.</p>";
        return h;
      }
      if (set === "dcode") {
        var r = m.dcode[i], tn = targetName(r[1]);
        h += "<ul><li>" + docLink(r[0]) + "<span>names</span></li><li>" + modLink(r[1]) + "<span>" + ["one name", "some names", "strong"][r[3]] + "</span></li></ul>";
        h += "<h3>Names used · " + r[2] + "</h3><ul>" + r[4].map(function (s) { return '<li class="fixed" style="font-size:12.5px"><a href="code-' + safe(tn) + ".html#fn=" + encodeURIComponent(s[0]) + '">' + safe(s[0]) + "</a><span>" + s[2] + "×</span></li>"; }).join("") + "</ul>";
        return h;
      }
      if (A.drilled()) { return h + "<p>" + safe(edgeText(m, A.drilled(), sel)) + "</p>"; }
      var a = m.links.a[i], b = m.links.b[i], dt = m.links.d[i];
      h += "<ul><li>" + docLink(a) + "<span>from</span></li><li>" + docLink(b) + "<span>to</span></li></ul>";
      if (set === "cites") h += '<p class="quiet">The title or file name is written ' + dt + " time" + (dt === 1 ? "" : "s") + ".</p>";
      else if (set === "quotes") h += '<p>Quotes <b class="fixed">' + safe(dt) + "</b>.</p>";
      else if (set === "samepart") h += '<p class="quiet">Both are about <b>' + safe(dt) + "</b>, at consecutive stages.</p>";
      else if (set === "shares" || set === "anchor") {
        h += "<p>" + CMX.num(dt[0]) + " named values in both: " + (dt[2] ? '<b style="color:var(--conflict)">' + dt[2] + " differ</b>" : '<span style="color:var(--ok)">all agree</span>') + ".</p>";
        if (dt[3].length) h += "<h3>Shared</h3><ul>" + dt[3].map(function (s) { return "<li><span>" + safe(s) + "</span></li>"; }).join("") + "</ul>";
        if (dt[4].length) h += '<h3 style="color:var(--conflict)">Differ</h3><ul>' + dt[4].map(function (s) { return "<li><span>" + safe(s) + "</span></li>"; }).join("") + "</ul>";
      } else if (set === "differs" && dt) {
        h += "<ul>" + dt.map(function (v) { return '<li style="display:block"><b>' + safe(v[0]) + '</b><br><span class="fixed" style="color:var(--conflict)">' + safe(v[1]) + (v[3] ? " @" + safe(v[3]) : "") + '</span> here, <span class="fixed">' + safe(v[2]) + (v[4] ? " @" + safe(v[4]) : "") + "</span> in most documents</li>"; }).join("") + "</ul>";
      }
      return h;
    }
    function mode(Dr) {
      crumbs.innerHTML = Dr ? '<a data-back="1">All modules</a><span class="divider">›</span><b>' + safe(m.modules[Dr.mi][1]) + "</b>" : "";
      toggles();
      if (Dr) show({ t: "mod", i: Dr.mi });
    }
    crumbs.addEventListener("click", function (ev) { if (ev.target.closest("[data-back]")) A.close(); });
    function toggles() {
      var sets = A.drilled() ? ["fcalls", "fout", "fin", "fdocs"] : ["calls", "dcode"].concat(m.vcode.length ? ["vcode"] : [], DOC_ORDER.filter(function (k) { return m.kinds.indexOf(k) >= 0 && (D.counts.links || {})[k]; }));
      controls.innerHTML = sets.map(function (k) {
        var on = A.isOn(k);
        return '<button type="button" class="switch' + (on ? " is-on" : "") + '" data-set="' + k + '" aria-pressed="' + on + '" title="' + safe((SETS[k] || {}).title || "") + '">' + swatch(k) + safe(name(k)) + "</button>";
      }).join("") + '<button type="button" class="switch" data-all="1" title="Show every kind of line">All links on</button>' +
        '<button type="button" class="switch" data-all="0" title="Hide every line: the modules and documents only">All links off</button>';
      controls.dataset.sets = sets.join(" ");
    }
    controls.addEventListener("click", function (ev) {
      var all = ev.target.closest("[data-all]");
      if (all) { controls.dataset.sets.split(" ").forEach(function (k) { A.setOn(k, all.getAttribute("data-all") === "1"); }); toggles(); return; }
      var b = ev.target.closest("[data-set]"); if (!b) return;
      var k = b.getAttribute("data-set"); A.setOn(k, !A.isOn(k)); toggles();
    });
    side.addEventListener("click", function (ev) {
      var a = ev.target.closest("[data-doc]"); if (a) { ev.preventDefault(); focusDoc(+a.getAttribute("data-doc")); return; }
      a = ev.target.closest("[data-mod]"); if (a) { ev.preventDefault(); if (A.drilled()) A.close(); focusMod(+a.getAttribute("data-mod")); return; }
      a = ev.target.closest("[data-open]"); if (a) { A.open(+a.getAttribute("data-open")); return; }
      a = ev.target.closest("[data-back]"); if (a) { A.close(); return; }
      a = ev.target.closest("[data-edge]"); if (a) { ev.preventDefault(); var p = a.getAttribute("data-edge").split(":"); A.select({ t: "edge", set: p[0], i: +p[1] }); }
    });
    function focusDoc(d) { var p = A.layoutOf().doc[d]; if (A.drilled()) A.close(); if (p) A.center(p.x, p.y); A.select({ t: "doc", i: d }); }
    function focusMod(mi) { var p = A.layoutOf().mod[mi]; if (p) A.center(p.x, p.y); A.select({ t: "mod", i: mi }); }
    var find = $("#find");
    if (find) find.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter") return;
      var q = find.value.trim().toLowerCase(); if (!q) return;
      var mi = m.modules.findIndex(function (x) { return x[1].toLowerCase() === q; });
      if (mi < 0) mi = m.modules.findIndex(function (x) { return x[1].toLowerCase().indexOf(q) >= 0; });
      if (mi >= 0) { focusMod(mi); return; }
      var d = m.docs.t.findIndex(function (t, i) { return t.toLowerCase().indexOf(q) >= 0 || m.docs.k[i].toLowerCase() === q; });
      if (d >= 0) { focusDoc(d); return; }
      var f = m.fn.n.findIndex(function (n, i) { return n.toLowerCase() === q || (m.fn.q[i] || "").toLowerCase() === q; });
      if (f >= 0 && m.fn.m[f] >= 0) { A.open(m.fn.m[f]); var Dr = A.drilled(); A.select({ t: "fn", i: Dr.fns.indexOf(f) }); }
    });
    var zc = document.createElement("div"); zc.className = "zoomctl";
    zc.innerHTML = '<button type="button" aria-label="Zoom in" title="Zoom in">+</button><button type="button" aria-label="Zoom out" title="Zoom out">&minus;</button>' +
      '<button type="button" class="reset" title="Back to the whole map">Reset view</button>';
    var zb = zc.querySelectorAll("button");
    zb[0].onclick = function () { A.zoom(1.3); }; zb[1].onclick = function () { A.zoom(1 / 1.3); }; zb[2].onclick = function () { A.fit(); };
    host.appendChild(zc);
    toggles(); overview();
    var hm = /(?:^|[#&])(doc|mod|fn)=([^&]+)/.exec(location.hash);
    if (hm) {
      var v = decodeURIComponent(hm[2]);
      setTimeout(function () {
        if (hm[1] === "doc" && m.docAt[v] !== undefined) focusDoc(m.docAt[v]);
        else if (hm[1] === "mod" && m.modByName[v] !== undefined) focusMod(m.modByName[v]);
        else if (hm[1] === "fn") { find.value = v; find.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" })); }
      }, 50);
    }
  }

  document.addEventListener("DOMContentLoaded", function () { if (document.body.getAttribute("data-page") === "atlas") page(); });
  return { create: create, model: model, layout: layout, SETS: SETS };
})();
