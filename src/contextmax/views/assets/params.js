/* ContextMAX parameters page: find a value by its name, compare it across documents, trace a formula. */
"use strict";
(function () {
  var D = CMX.pageData(), safe = CMX.safe, $ = CMX.$;
  var V = D.variables, list = $("#vars"), main = $("#detail"), q = $("#find");
  var KIND = { cell_entry: "typed in a cell", computed_value: "result of a formula", prose_value: "written in the text" };
  var only = "all";

  function renderList() {
    var term = q.value.trim().toLowerCase();
    var hits = V.filter(function (v) {
      if (only === "shared" && v[2] < 2) return false;
      if (only === "differ" && !(v[2] > 1 && v[4] === "differ")) return false;
      return !term || v[1].indexOf(term) >= 0;
    }).slice(0, 400);
    list.innerHTML = hits.length ? hits.map(function (v) {
      var badge = v[2] > 1 ? (v[4] === "match" ? '<span class="status ok">match</span>' : '<span class="status bad">differ</span>') : '<span class="quiet" style="font-size:12px">1 document</span>';
      return '<li><a href="#" data-val="' + safe(v[1]) + '" class="fixed">' + safe(v[0]) + "</a><span>" + (v[2] > 1 ? v[2] + " docs " : "") + badge + "</span></li>";
    }).join("") : '<li class="quiet">No named value matches. A bare number is not a name: search for what the number measures.</li>';
  }
  function trace(doc, sheet, cell, depth, seen) {
    var cells = D.cells[doc]; if (!cells) return "";
    var key = sheet + "!" + cell; if (seen[key] || depth > 8) return ""; seen[key] = true;
    var c = cells[key];
    if (!c) return '<li class="fixed">' + safe(key) + ' <span class="quiet">(text or empty: not a number)</span></li>';
    var h = '<li><span class="fixed"><b>' + safe(key) + " = " + safe(c[0]) + (c[1] ? " " + safe(c[1]) : "") + "</b></span> " + (c[2] ? '<span class="quiet">' + safe(c[2]) + "</span> " : "") +
      (c[3] ? '<span class="fixed quiet">' + safe(c[3]) + "</span>" : '<span class="quiet">typed in</span>');
    if (c[3]) {
      var refs = [], m, re = /(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_.]*))!)?\$?([A-Z]{1,3})\$?(\d{1,7})/g;
      var body = c[3].replace(/"[^"]*"/g, " ");
      while ((m = re.exec(body))) refs.push([m[1] || m[2] || sheet, m[3] + m[4]]);
      var lits = (body.replace(re, " ").match(/(?:^|[^A-Za-z0-9_.$])(\d+(?:\.\d+)?)(?![A-Za-z0-9_.(])/g) || []).map(function (x) { return x.replace(/^[^0-9]/, ""); });
      if (refs.length || lits.length) {
        h += '<ul style="margin:6px 0 0 8px;padding-left:14px;border-left:1.5px solid var(--rule)">';
        refs.forEach(function (r) { h += trace(doc, r[0], r[1], depth + 1, seen); });
        lits.forEach(function (l) { h += '<li><span class="fixed">' + safe(l) + '</span> <span class="quiet">constant inside the formula, no unit given</span></li>'; });
        h += "</ul>";
      }
    }
    return h + "</li>";
  }
  function showVar(key) {
    var v = V.filter(function (x) { return x[1] === key; })[0], rows = D.rows[key] || [];
    /* the verdict counts documents, not rows: two copies of one document count once */
    var nums = {}, seen = {};
    rows.forEach(function (r) { var k = r[9] + "|" + r[1]; if (!seen[k]) { seen[k] = 1; nums[r[9]] = (nums[r[9]] || 0) + 1; } });
    var uniqueValues = Object.keys(nums);
    var verdict = rows.length < 2 ? '<span class="quiet">stated once</span>' : uniqueValues.length === 1 ? '<span class="status ok">Match: ' + safe(rows[0][3]) + (rows[0][4] ? " " + safe(rows[0][4]) : "") + " everywhere</span>"
      : '<span class="status bad">Mismatch: ' + uniqueValues.map(function (d) { var r = rows.filter(function (x) { return x[9] === d; })[0]; return safe(r[3]) + (r[4] ? " " + safe(r[4]) : "") + " in " + nums[d]; }).join(", ") + "</span>";
    var common = (function () { var c = {}; rows.forEach(function (r) { c[r[9]] = (c[r[9]] || 0) + 1; }); var best = null; Object.keys(c).forEach(function (k) { if (best === null || c[k] > c[best]) best = k; }); return best; })();
    var h = '<div class="hstack" style="margin:0 0 14px"><h1 class="headline fixed" style="font-size:28px">' + safe(v ? v[0] : key) + "</h1>" + verdict + "</div>";
    h += '<div class="tablebox"><table class="listing"><thead><tr><th>Document</th><th>Where</th><th>Value</th><th>Found as</th><th></th></tr></thead><tbody>' + rows.map(function (r, i) {
      var odd = uniqueValues.length > 1 && r[9] !== common;
      var traceBtn = r[7] && D.cells[r[10]] ? '<button type="button" class="switch" data-trace="' + i + '">Trace</button>' : "";
      return "<tr" + (odd ? ' class="bad"' : "") + '><td><a href="documents.html#doc=' + encodeURIComponent(r[1]) + '">' + safe(r[0]) + '</a><div class="quiet" style="font-size:12px">' + safe(r[2]) + "</div></td>" +
        '<td class="fixed" style="font-size:13px">' + safe(r[5] || "text") + (r[8] ? ' <span class="badge">hidden</span>' : "") + (r[11] ? '<div class="quiet" style="font-family:inherit;font-size:12px">' + safe(r[11]) + "</div>" : "") + "</td>" +
        '<td class="fixed"' + (odd ? ' style="color:var(--conflict);font-weight:600"' : "") + ">" + safe(r[3]) + (r[4] ? " " + safe(r[4]) : "") + "</td>" +
        "<td>" + safe(KIND[r[6]] || r[6]) + (r[7] ? '<div class="fixed quiet" style="font-size:12px">' + safe(r[7]) + "</div>" : "") + "</td><td>" + traceBtn + "</td></tr>";
    }).join("") + "</tbody></table></div><div id=\"trace\"></div>";
    main.innerHTML = h;
    CMX.$$("[data-trace]", main).forEach(function (b) {
      b.onclick = function () {
        var r = rows[+b.getAttribute("data-trace")], at = r[5].split("!");
        $("#trace").innerHTML = '<div class="tile" style="margin-top:16px"><b>Where ' + safe(r[5]) + ' in “' + safe(r[0]) + '” comes from</b><ul style="list-style:none;padding:0;margin:8px 0;display:flex;flex-direction:column;gap:6px">' +
          trace(r[10], at.slice(0, -1).join("!"), at[at.length - 1], 0, {}) + '</ul><p class="quiet" style="margin:0">Read from the cells already in the index. To check the live workbook: <span class="fixed">contextmax sheet ' + safe(D.project) + ' --key ' + safe(r[10]) + " --trace " + safe(r[5]) + "</span></p></div>";
      };
    });
    if (history.replaceState) history.replaceState(null, "", "#v=" + encodeURIComponent(key));
  }
  list.addEventListener("click", function (ev) { var a = ev.target.closest("[data-val]"); if (a) { ev.preventDefault(); showVar(a.getAttribute("data-val")); } });
  q.addEventListener("input", renderList);
  CMX.$$("[data-only]").forEach(function (b) {
    b.onclick = function () { only = b.getAttribute("data-only"); CMX.$$("[data-only]").forEach(function (x) { x.classList.toggle("is-on", x === b); x.setAttribute("aria-pressed", x === b); }); renderList(); };
  });
  renderList();
  var m = /v=([^&]+)/.exec(location.hash);
  if (m) showVar(decodeURIComponent(m[1]));
  else if (V.length) { var first = V.filter(function (v) { return v[2] > 1; })[0] || V[0]; showVar(first[1]); }
  else main.innerHTML = '<div class="tile"><p>No named values yet. Values get a name from the label beside them in a workbook, or from text such as <span class="fixed">settle time: 12 ms</span>.</p></div>';
})();
