/* ContextMAX connections page: code bases and the hand-written links between them. */
"use strict";
(function () {
  var D = CMX.pageData(), safe = CMX.safe, canvas = CMX.$("#canvas"), side = CMX.$("#drawer");
  var KINDS = { "relay": { dash: null, label: "hands over at run time" }, "bus-registers": { dash: null, width: 6, label: "register bus" },
                protocol: { dash: "10 5", label: "protocol" }, "cabled": { dash: "3 5", label: "cabled" }, "common-source": { dash: "12 5 2 5", label: "shared source" } };
  function draw() {
    var labels = {}, list = [];
    D.targets.forEach(function (t) { labels[t.name] = { label: t.label, sub: t.summary, ext: false, link: "code-" + t.name + ".html" }; list.push(t.name); });
    D.links.forEach(function (l) { [l.from, l.to].forEach(function (n) { if (!labels[n]) { labels[n] = { label: n, sub: "outside the folders", ext: true }; list.push(n); } }); });
    var cols = Math.max(2, Math.ceil(Math.sqrt(list.length))), pos = {};
    list.forEach(function (n, i) { pos[n] = [(i % cols) * 340, Math.floor(i / cols) * 200]; });
    var svg = CMX.freshSvg(canvas);
    D.links.forEach(function (l) {
      var a = pos[l.from], b = pos[l.to], k = KINDS[l.kind] || { dash: "6 4", label: l.kind || "link" };
      var p = CMX.el("path", { d: CMX.arc(a[0] + 130, a[1] + 40, b[0] + 130, b[1] + 40, 0.1), fill: "none", stroke: CMX.css("--code"), "stroke-width": k.width || 2.5, "stroke-dasharray": k.dash || (l.draft ? "2 6" : null), style: "cursor:pointer" }, svg);
      CMX.el("title", {}, p, (l.label || k.label));
      var mx = (a[0] + b[0]) / 2 + 130, my = (a[1] + b[1]) / 2 + 40;
      CMX.el("text", { x: mx, y: my - 10, "text-anchor": "middle", class: "small", style: "paint-order:stroke;stroke:var(--paper);stroke-width:5px" }, svg, l.label || k.label);
      p.addEventListener("click", function () {
        side.innerHTML = "<h2>" + safe(l.label || k.label) + '</h2><p class="quiet">' + safe(l.from) + " → " + safe(l.to) + " · " + safe(k.label) + (l.draft ? " · draft" : "") + "</p>" + (l.detail ? "<p>" + safe(l.detail) + "</p>" : "") +
          (l.evidence ? "<h3>Evidence in the code</h3><p class=\"fixed\">" + safe([].concat(l.evidence).join(", ")) + "</p>" : '<div class="remark">No code evidence written down for this link yet.</div>');
      });
    });
    list.forEach(function (n) {
      var p = pos[n], x = labels[n], g = CMX.el("g", { style: "cursor:pointer" }, svg);
      if (x.ext) CMX.el("rect", { x: p[0], y: p[1], width: 260, height: 80, rx: 12, fill: "none", stroke: CMX.css("--cat"), "stroke-width": 2, "stroke-dasharray": "7 5" }, g);
      else { CMX.el("rect", { x: p[0], y: p[1], width: 260, height: 80, rx: 12, fill: CMX.css("--surface"), stroke: CMX.css("--text"), "stroke-width": 1.5 }, g);
             CMX.el("rect", { x: p[0] + 5, y: p[1] + 5, width: 250, height: 70, rx: 9, fill: "none", stroke: CMX.css("--text"), "stroke-width": 1.5 }, g); }
      CMX.el("text", { x: p[0] + 130, y: p[1] + 36, "text-anchor": "middle", class: "head fixed" }, g, x.label);
      CMX.el("text", { x: p[0] + 130, y: p[1] + 56, "text-anchor": "middle", class: "small" }, g, x.sub || "");
      if (x.link) g.addEventListener("click", function () { location.href = x.link; });
    });
    var rows = Math.ceil(list.length / cols);
    var pz = CMX.panZoom(svg, cols * 340 - 80, rows * 200 - 120); CMX.zoomButtons(canvas, pz);
  }
  if (!D.targets.length && !D.links.length) canvas.innerHTML = '<div class="empty">No code base has been mapped yet.</div>';
  else draw();
  side.innerHTML = D.links.length ? '<h2>' + D.links.length + " links</h2><p class=\"quiet\">Click a line for what crosses it and the code that proves it.</p>" :
    "<h2>No links written yet</h2><p>A call graph cannot see a link between two programs, two chips, or a program and a device. Write them down once in</p><p class=\"fixed\" style=\"word-break:break-all\">" + safe(D.file) +
    '</p><p>as a list of entries like:</p><pre class="fixed" style="white-space:pre-wrap;background:var(--surface-2);padding:10px;border-radius:8px;font-size:12px">[{"from": "main-app", "to": "updater",\n  "kind": "relay",\n  "label": "jumps to the updater on request",\n  "evidence": ["start_update"]}]</pre><p class="quiet">Kinds: handover, bus-registers, protocol, wiring, common-source. Names are code-base names, or anything outside the folders (a PC, a device).</p>';
  CMX.onTheme(function () { if (D.targets.length || D.links.length) draw(); });
})();
