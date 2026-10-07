/* ContextMAX shared page script: theme, view switching, pan and zoom, small helpers.
   No network, no framework. Every page works offline from the working folder. */
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
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    var b = $("#theme"); if (b) { b.textContent = t === "dark" ? "Light" : "Dark"; b.setAttribute("aria-label", "Switch to " + (t === "dark" ? "light" : "dark") + " mode"); }
    themeListeners.forEach(function (f) { f(t); });
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
    applyTheme(theme());
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
      if (history.replaceState) history.replaceState(null, "", "#view=" + v.id + (location.hash.indexOf("&") > 0 ? location.hash.slice(location.hash.indexOf("&")) : ""));
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
    return { fit: fit, zoom: zoom, center: center };
  }

  function zoomButtons(host, pz) {
    var box = document.createElement("div"); box.className = "zoomctl";
    box.innerHTML = '<button type="button" aria-label="Zoom in">+</button><button type="button" aria-label="Zoom out">&minus;</button><button type="button" aria-label="Fit to screen">&#9634;</button>';
    var b = box.querySelectorAll("button");
    b[0].onclick = function () { pz.zoom(1 / 1.3); }; b[1].onclick = function () { pz.zoom(1.3); }; b[2].onclick = function () { pz.fit(); };
    host.appendChild(box);
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

  function num(n) { return n === null || n === undefined ? "" : Number(n).toLocaleString("en-US"); }

  document.addEventListener("DOMContentLoaded", initTheme);
  return { safe: safe, $: $, $$: $$, pageData: pageData, css: css, store: store, theme: theme, onTheme: onTheme,
           initViews: initViews, panZoom: panZoom, zoomButtons: zoomButtons, el: el, freshSvg: freshSvg,
           wire: wire, arc: arc, color: color, editorLink: editorLink, num: num };
})();
