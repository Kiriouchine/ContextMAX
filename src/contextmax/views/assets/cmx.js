/* ContextMAX shared page script: theme, view switching, pan and zoom, opening files, small helpers.
   No framework, and no network beyond this PC: a page the ContextMAX window serves talks to that window
   only. Every page works offline from the working folder. */
"use strict";
var CMX = (function () {
  var store = {
    get: function (k) { try { return window.localStorage.getItem("cmx:" + k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem("cmx:" + k, v); } catch (e) { /* private window */ } }
  };

  function safe(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function pageData(id) { var el = document.getElementById(id || "cmx-data"); return el ? JSON.parse(el.textContent) : null; }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  /* ---- theme: follows Windows unless the viewer picks one ---- */
  var themeListeners = [];
  function theme() { return document.documentElement.getAttribute("data-theme") || "light"; }
  function applyTheme(t, quiet) {
    document.documentElement.setAttribute("data-theme", t);
    var b = $("#theme"); if (b) { b.textContent = t === "dark" ? "Light" : "Dark"; b.setAttribute("aria-label", "Switch to " + (t === "dark" ? "light" : "dark") + " mode"); }
    if (!quiet) themeListeners.forEach(function (f) { f(t); });
  }
  function initialTheme() {
    var asked = /[?&]theme=(light|dark)/.exec(location.search);
    if (asked) return asked[1];
    var saved = store.get("theme");
    var sys = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    return saved || sys;
  }
  /* set before the first paint, so nothing is drawn in the wrong colours */
  document.documentElement.setAttribute("data-theme", initialTheme());
  function initTheme() {
    applyTheme(theme(), true);       /* the colours were set before the first paint: nothing to redraw, no selection lost */
    var b = $("#theme");
    if (b) b.addEventListener("click", function () { var t = theme() === "dark" ? "light" : "dark"; store.set("theme", t); applyTheme(t); });
  }
  function onTheme(f) { themeListeners.push(f); }

  /* ---- views: buttons above the canvas, remembered per page ---- */
  function initViews(page, views, start) {
    var bar = $("#views"); if (!bar) return;
    bar.innerHTML = views.map(function (v) { return '<button type="button" data-view="' + v.id + '" title="' + safe(v.title || "") + '">' + safe(v.label) + "</button>"; }).join("");
    var current = null;
    function pick(id) {
      var v = views.filter(function (x) { return x.id === id; })[0] || views[0];
      if (current && current.leave) current.leave();
      current = v;
      $$("button", bar).forEach(function (b) { var on = b.getAttribute("data-view") === v.id; b.classList.toggle("is-on", on); b.setAttribute("aria-pressed", on ? "true" : "false"); });
      store.set("view:" + page, v.id);
      /* only view= changes: a link's doc= or fn= stays, for the page to select it */
      var rest = location.hash.replace(/^#/, "").split("&").filter(function (p) { return p && !/^view=/.test(p); }).join("&");
      if (history.replaceState) history.replaceState(null, "", "#view=" + v.id + (rest ? "&" + rest : ""));
      v.enter();
    }
    bar.addEventListener("click", function (ev) { var b = ev.target.closest("button[data-view]"); if (b) pick(b.getAttribute("data-view")); });
    var m = /view=([a-z]+)/.exec(location.hash);
    pick((m && m[1]) || start || store.get("view:" + page) || views[0].id);
    return { pick: pick, current: function () { return current; } };
  }

  /* ---- an <svg> that pans with the mouse and zooms with the wheel ---- */
  function panZoom(svg, width, height) {
    var vb = { x: -40, y: -40, w: width + 80, h: height + 80 };
    function set() { svg.setAttribute("viewBox", vb.x + " " + vb.y + " " + vb.w + " " + vb.h); }
    function fit() {
      var r = svg.getBoundingClientRect(), ar = (r.width || 1) / (r.height || 1);
      var w = width + 80, h = height + 80;
      if (w / h > ar) { vb.w = w; vb.h = w / ar; } else { vb.h = h; vb.w = h * ar; }
      vb.x = -40 - (vb.w - w) / 2; vb.y = -40 - (vb.h - h) / 2; set();
    }
    function zoom(f, cx, cy) {
      var r = svg.getBoundingClientRect();
      var px = cx === undefined ? 0.5 : (cx - r.left) / r.width, py = cy === undefined ? 0.5 : (cy - r.top) / r.height;
      var nw = Math.max(80, Math.min(vb.w * f, (width + 80) * 8)), nh = nw * vb.h / vb.w;
      vb.x += (vb.w - nw) * px; vb.y += (vb.h - nh) * py; vb.w = nw; vb.h = nh; set();
    }
    function center(x, y, scale) {
      var r = svg.getBoundingClientRect(), ar = (r.width || 1) / (r.height || 1);
      vb.w = scale || Math.min(vb.w, 900); vb.h = vb.w / ar; vb.x = x - vb.w / 2; vb.y = y - vb.h / 2; set();
    }
    var drag = null;
    svg.addEventListener("wheel", function (ev) { ev.preventDefault(); zoom(ev.deltaY > 0 ? 1.15 : 1 / 1.15, ev.clientX, ev.clientY); }, { passive: false });
    svg.addEventListener("pointerdown", function (ev) { if (ev.button !== 0) return; drag = { x: ev.clientX, y: ev.clientY, vx: vb.x, vy: vb.y, moved: false }; });
    window.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      var r = svg.getBoundingClientRect(), k = vb.w / r.width;
      if (Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) > 4) drag.moved = true;
      vb.x = drag.vx - (ev.clientX - drag.x) * k; vb.y = drag.vy - (ev.clientY - drag.y) * k; set();
    });
    window.addEventListener("pointerup", function () { if (drag && drag.moved) svg.dataset.dragged = "1"; drag = null; setTimeout(function () { delete svg.dataset.dragged; }, 0); });
    fit();
    /* a map drawn again (a switch turned, the theme changed) keeps the view the viewer left it at */
    function view() { return { x: vb.x, y: vb.y, w: vb.w, h: vb.h }; }
    function setView(v) { if (v) { vb.x = v.x; vb.y = v.y; vb.w = v.w; vb.h = v.h; set(); } }
    return { fit: fit, zoom: zoom, center: center, view: view, setView: setView };
  }

  /* the zoom buttons of every map: in, out, and back to the whole map */
  function zoomButtons(host, pz) {
    var box = document.createElement("div"); box.className = "zoomctl";
    box.innerHTML = '<button type="button" aria-label="Zoom in" title="Zoom in">+</button><button type="button" aria-label="Zoom out" title="Zoom out">&minus;</button>' +
      '<button type="button" class="reset" title="Back to the whole map">Reset view</button>';
    var b = box.querySelectorAll("button");
    b[0].onclick = function () { pz.zoom(1 / 1.3); }; b[1].onclick = function () { pz.zoom(1.3); }; b[2].onclick = function () { pz.fit(); };
    host.appendChild(box);
  }
  /* the same for a network map (vis-network): its view is a centre and a scale */
  function visZoom(net) {
    return {
      zoom: function (f) { net.moveTo({ scale: net.getScale() / f }); },
      fit: function () { net.fit({ animation: { duration: 300 } }); },
      view: function () { return { position: net.getViewPosition(), scale: net.getScale() }; },
      setView: function (v) { if (v) net.moveTo({ position: v.position, scale: v.scale }); }
    };
  }

  var SVGNS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent, text) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function freshSvg(host) {
    host.innerHTML = "";
    var svg = el("svg", { role: "img" }, host);
    return svg;
  }
  /* a soft curve from (x1,y1) to (x2,y2): horizontal tangents, like a drafted wire */
  function wire(x1, y1, x2, y2) {
    var dx = Math.max(30, Math.abs(x2 - x1) * 0.45);
    return "M" + x1 + "," + y1 + " C" + (x1 + dx) + "," + y1 + " " + (x2 - dx) + "," + y2 + " " + x2 + "," + y2;
  }
  function arc(x1, y1, x2, y2, bend) {
    var mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1, len = Math.sqrt(dx * dx + dy * dy) || 1;
    var b = bend === undefined ? 0.18 : bend;
    return "M" + x1 + "," + y1 + " Q" + (mx - dy / len * len * b) + "," + (my + dx / len * len * b) + " " + x2 + "," + y2;
  }

  /* module colours: twelve hues that read on paper and at night alike */
  var HUES = ["#2457C5", "#C2410C", "#0E7C74", "#7C3AED", "#B7791F", "#BE185D", "#4D7C0F", "#0369A1", "#9F1239", "#475569", "#A16207", "#15803D"];
  var HUES_DARK = ["#7FA6FF", "#FB8F4E", "#4FC1B4", "#B794F6", "#E5B649", "#F472B6", "#9BD15A", "#5BB8F0", "#FB7185", "#A3B1C2", "#F2C14E", "#4ADE80"];
  function color(i) { var p = theme() === "dark" ? HUES_DARK : HUES; return p[i % p.length]; }

  function editorLink(root, rel, line) {
    if (!root) return null;
    var p = (root.replace(/[\\\/]+$/, "") + "/" + rel).replace(/\\/g, "/");
    return "vscode://file/" + encodeURI(p) + (line ? ":" + line : "");
  }

  /* a link's doc= or fn= has done its work once the page selected it: the address then shows the view only */
  function dropHash(name) {
    if (!history.replaceState) return;
    var h = location.hash.replace(/^#/, "").split("&").filter(function (p) { return p && p.indexOf(name + "=") !== 0; }).join("&");
    history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
  }

  function num(n) { return n === null || n === undefined ? "" : Number(n).toLocaleString("en-US"); }

  /* ---- the ContextMAX window: set when it serves this page (window.CMX_PANEL holds its token) ---- */
  function panel() { return window.CMX_PANEL || null; }
  function ask(action, body) {
    var P = panel();
    if (!P) return Promise.reject(new Error("open this page from the ContextMAX window"));
    return fetch("/api/" + action, { method: "POST", headers: { "Content-Type": "application/json", "X-CMX-Token": P.token },
                                     body: JSON.stringify(Object.assign({ slug: P.slug }, body || {})) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.statusText); return j; }); });
  }
  function note(button, text, bad) {
    var host = button && button.parentNode; if (!host) return;
    var n = host.querySelector(".cmx-note");
    if (!n) { n = document.createElement("span"); n.className = "quiet cmx-note"; host.appendChild(n); }
    n.textContent = text; n.style.color = bad ? "var(--conflict)" : "";
  }
  /* "Open document" and "Show in folder": the window opens the file; a page opened from disk follows a
     contextmax-open: link, which setup.cmd registers for this user. Either way only files in a project's
     folders, and only documents, are opened. */
  function openFile(path, how, button) {
    if (panel()) {
      ask("files", { path: path, how: how }).then(function (j) { note(button, j.message); }, function (e) { note(button, e.message, true); });
    } else {
      location.href = "contextmax-open:" + how + "?path=" + encodeURIComponent(path);
    }
  }
  /* ---- Ask your AI (Home): the assistants this PC has, started from the window ---- */
  function initAsk() {
    var box = $("#ask-actions"); if (!box) return;
    var P = panel();
    if (box.getAttribute("data-portable")) {
      box.innerHTML = '<span class="quiet">This is a shared copy. With ContextMAX installed, the PC that built the project starts an assistant from here.</span>';
      return;
    }
    if (!P) {
      var root = box.getAttribute("data-root");
      box.innerHTML = (root ? '<a class="btn ghost" href="vscode://file/' + encodeURI(root.replace(/\\/g, "/")) + '">Open in VS Code</a>' : "") +
        '<span class="quiet">Open this project from the ContextMAX window to start Claude, Codex or a model on this PC from here.</span>';
      return;
    }
    box.innerHTML = '<span class="quiet">Looking for assistants on this PC …</span>';
    ask("assistants").then(function (r) {
      var on = r.tools.filter(function (t) { return t.ok; }), off = r.tools.filter(function (t) { return !t.ok; });
      var html = on.map(function (t, i) {
        return '<button type="button" class="btn' + (i ? " ghost" : "") + '" data-assistant="' + safe(t.id) + '" title="' + safe(t.title) + '">' + safe(t.label) + "</button>";
      });
      html.push('<a class="btn ghost" target="_blank" rel="noopener" href="/ask?slug=' + encodeURIComponent(P.slug) + '" title="' +
        safe(r.servers.length ? "Ollama, llama.cpp or LM Studio on this PC: nothing leaves the PC" : "no model server runs on this PC yet") + '">A model on this PC</a>');
      box.innerHTML = html.join("") + (off.length ? '<span class="quiet" style="flex-basis:100%">Not on this PC: ' +
        off.map(function (t) { return safe(t.label) + " (" + safe(t.why) + ")"; }).join(", ") + "</span>" : "");
    }, function (e) { box.innerHTML = '<span class="quiet">' + safe(e.message) + "</span>"; });
    box.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-assistant]"); if (!b) return;
      b.disabled = true;
      note(b, b.getAttribute("data-assistant") === "vscode-claude" ? "Starting VS Code; Claude's chat opens once the project's window is there …" : "Starting …");
      ask("assistant", { tool: b.getAttribute("data-assistant") }).then(function (j) { note(b, j.message); b.disabled = false; },
        function (e) { note(b, e.message, true); b.disabled = false; });
    });
  }
  document.addEventListener("DOMContentLoaded", initAsk);
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest && ev.target.closest("[data-file]");
    if (!b) return;
    ev.preventDefault();
    openFile(b.getAttribute("data-file"), b.getAttribute("data-how") || "open", b);
  });

  document.addEventListener("DOMContentLoaded", initTheme);
  return { safe: safe, $: $, $$: $$, pageData: pageData, css: css, store: store, theme: theme, onTheme: onTheme,
           initViews: initViews, panZoom: panZoom, zoomButtons: zoomButtons, visZoom: visZoom, el: el, freshSvg: freshSvg,
           wire: wire, arc: arc, color: color, editorLink: editorLink, num: num, dropHash: dropHash, panel: panel, ask: ask, note: note,
           openFile: openFile };
})();
