(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function h(tag, attrs) {
    var e = document.createElement(tag), k, args = arguments;
    attrs = attrs || {};
    for (k in attrs) { if (k === "class") e.className = attrs[k]; else e.setAttribute(k, attrs[k]); }
    (function add(list) {
      list.forEach(function (c) {
        if (c === null || c === undefined || c === false) return;
        if (Array.isArray(c)) return add(c);
        e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
      });
    })([].slice.call(args, 2));
    return e;
  }
  function num(n) { return Number(n).toLocaleString("en-GB", { maximumFractionDigits: 2 }); }
  function ago(ts) {
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 90) return "just now";
    if (s < 5400) return Math.round(s / 60) + " min ago";
    if (s < 129600) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " days ago";
  }
  function statusClass(s) { return s === "verified" ? "ok" : (s === "rejected" ? "bad" : "warn"); }
  var KIND = {
    evidence: "Computational evidence",
    counterexample: "Counterexample candidate",
    witness: "Witness",
    observation: "Observation",
    proof: "Proof claim"
  };
  function stat(label, value, cls) { return h("div", { class: "stat " + (cls || "") }, h("b", {}, value), h("span", {}, label)); }

  function renderStats(s) {
    var ps = s.problems, exps = 0, ver = 0, best = null, i, k;
    for (i = 0; i < ps.length; i++) {
      exps += ps[i].experiments;
      ver += ps[i].claims.verified || 0;
      var sp = ps[i].performance && ps[i].performance.speedup_vs_baseline;
      if (sp && (best === null || sp > best)) best = sp;
    }
    var box = $("stats");
    box.replaceChildren(
      stat("Active problems", ps.length),
      stat("Experiments", num(exps)),
      stat("Verified claims", num(ver), ver ? "good" : ""),
      stat("Self-improvement", best ? num(best) + "×" : "–", best ? "good" : ""),
      stat("Memory journal", s.journal && s.journal.ok ? "Intact" : "BROKEN", s.journal && s.journal.ok ? "good" : "bad")
    );
    $("updated").textContent = s.generated_at ? "Last updated " + ago(s.generated_at) + " · " + new Date(s.generated_at * 1000).toUTCString() : "";
  }

  function problemStatus(s, p) {
    if (p.status && p.status.alert) return ["Alert: review needed", "bad"];
    var last = 0, i;
    for (i = 0; i < s.experiments.length; i++) if (s.experiments[i].problem_id === p.id) last = Math.max(last, s.experiments[i].started || 0);
    var gen = s.generated_at || Date.now() / 1000;
    return gen - last < 7200 ? ["Active research", "ok"] : ["Paused", "warn"];
  }

  function renderProblems(s) {
    var list = $("problem-list");
    if (!s.problems.length) { list.replaceChildren(h("div", { class: "empty" }, "No research data published yet.")); return; }
    list.replaceChildren.apply(list, s.problems.map(function (p, idx) {
      var st = problemStatus(s, p), kv = h("dl", { class: "kv" }), k, v;
      for (k in (p.status || {})) {
        v = p.status[k];
        if (v === null || v === undefined || v === "") continue;
        kv.append(h("dt", {}, k.replace(/_/g, " ")), h("dd", {}, typeof v === "number" ? num(v) : (typeof v === "object" ? JSON.stringify(v) : v)));
      }
      var cl = Object.keys(p.claims || {}).map(function (x) { return x + ": " + p.claims[x]; }).join(" · ") || "none";
      kv.append(h("dt", {}, "experiments"), h("dd", {}, num(p.experiments)), h("dt", {}, "claims"), h("dd", {}, cl));
      var perf = p.performance || {};
      if (perf.speedup_vs_baseline) kv.append(h("dt", {}, "best strategy"), h("dd", {}, perf.best_arm + " · " + num(perf.speedup_vs_baseline) + "× baseline"));
      var rows = Object.keys(p.arm_stats || {}).map(function (a) {
        var r = p.arm_stats[a];
        return h("tr", {}, h("td", {}, a), h("td", {}, r.pulls), h("td", {}, (r.total_reward / r.pulls).toFixed(3)));
      });
      return h("article", { class: "card" },
        h("div", { class: "top mono" }, h("span", {}, String(idx + 1).padStart(2, "0") + " / " + String(s.problems.length).padStart(2, "0") + "  FL / " + (p.domain || "research").toUpperCase()), h("span", { class: "chip " + st[1] }, st[0])),
        h("h3", {}, p.title), h("p", {}, p.statement), kv,
        rows.length ? h("table", { class: "mini" }, h("tr", {}, h("th", {}, "Strategy"), h("th", {}, "Runs"), h("th", {}, "Mean reward")), rows) : null,
        p.source ? h("p", { class: "mut", style: "margin:12px 0 0;font-size:12.5px" }, "Source: " + p.source) : null);
    }));
  }

  var COLORS = ["#3dff9a", "#6fd3ff", "#ffc857", "#c792ff"];
  function renderChart(s) {
    var box = $("chart"), groups = {}, names, W = 800, H = 280, pad = 44, i;
    s.problems.forEach(function (p) { (p.series || []).forEach(function (pt) { (groups[pt.name.slice(5)] = groups[pt.name.slice(5)] || []).push(pt.value); }); });
    names = Object.keys(groups);
    if (!names.length) { box.replaceChildren(h("div", { class: "empty" }, "Waiting for the first experiments.")); return; }
    var all = [].concat.apply([], names.map(function (n) { return groups[n]; })).filter(function (v) { return v > 0; });
    var lo = Math.log10(Math.min.apply(null, all)) - 0.1, hi = Math.log10(Math.max.apply(null, all)) + 0.1;
    var maxLen = Math.max.apply(null, names.map(function (n) { return groups[n].length; }));
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Throughput per experiment by strategy");
    function el(t, a) { var e = document.createElementNS(ns, t), k; for (k in a) e.setAttribute(k, a[k]); svg.appendChild(e); return e; }
    function X(i) { return pad + (W - pad - 16) * (maxLen <= 1 ? 0.5 : i / (maxLen - 1)); }
    function Y(v) { return H - 30 - (H - 50) * ((Math.log10(v) - lo) / (hi - lo)); }
    for (i = Math.ceil(lo); i <= Math.floor(hi); i++) {
      el("line", { x1: pad, x2: W - 10, y1: Y(Math.pow(10, i)), y2: Y(Math.pow(10, i)), stroke: "rgba(255,255,255,.08)" });
      var t = el("text", { x: 6, y: Y(Math.pow(10, i)) + 4, fill: "#8aa097", "font-size": 11 }); t.textContent = "10^" + i;
    }
    names.forEach(function (n, j) {
      var pts = groups[n].map(function (v, k) { return X(k) + "," + Y(v); });
      el("polyline", { points: pts.join(" "), fill: "none", stroke: COLORS[j % 4], "stroke-width": 2.5, "stroke-linejoin": "round" });
      groups[n].forEach(function (v, k) { el("circle", { cx: X(k), cy: Y(v), r: 3.5, fill: COLORS[j % 4] }); });
    });
    var lg = h("div", { class: "legend" }, names.map(function (n, j) { return h("span", {}, h("i", { style: "background:" + COLORS[j % 4] }), n.replace(/_/g, " ")); }));
    var cap = h("div", { class: "legend" }, h("span", {}, "x: experiment order · y: items per second (log scale)"));
    box.replaceChildren(svg, lg, cap);
  }

  function renderClaims(s) {
    var box = $("claim-list");
    if (!s.claims.length) { box.replaceChildren(h("div", { class: "empty" }, "No claims recorded yet.")); return; }
    box.replaceChildren.apply(box, s.claims.map(function (c) {
      return h("div", { class: "row" }, h("div", { class: "id" }, "#" + c.id),
        h("div", { class: "body" }, h("p", {}, c.statement),
          h("div", { class: "meta" }, h("span", { class: "chip " + statusClass(c.status) }, c.status.replace(/_/g, " ")), h("span", { class: "chip" }, KIND[c.kind] || c.kind),
            h("span", {}, (c.verifications || []).map(function (v) { return v.verifier.replace(/_/g, " ") + ": " + v.verdict; }).join(" · ")))));
    }));
  }
  function renderExperiments(s) {
    var box = $("exp-list");
    if (!s.experiments.length) { box.replaceChildren(h("div", { class: "empty" }, "No experiments yet.")); return; }
    box.replaceChildren.apply(box, s.experiments.map(function (e) {
      return h("div", { class: "row" }, h("div", { class: "id" }, "#" + e.id),
        h("div", { class: "body" }, h("p", {}, e.summary || e.status),
          h("div", { class: "meta" }, h("span", { class: "chip" }, e.arm.replace(/_/g, " ")), h("span", {}, (e.duration || 0).toFixed(1) + " s"), h("span", {}, e.status))));
    }));
  }
  function renderLessons(s) {
    var box = $("lesson-list");
    if (!s.lessons.length) { box.replaceChildren(h("div", { class: "empty" }, "No lessons recorded yet.")); return; }
    box.replaceChildren.apply(box, s.lessons.map(function (l, i) {
      return h("div", { class: "row" }, h("div", { class: "id" }, l.tag.toUpperCase()), h("div", { class: "body" }, h("p", {}, l.text)));
    }));
  }

  fetch("data/state.json?t=" + Date.now(), { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (s) {
      s.problems = s.problems || []; s.experiments = s.experiments || []; s.claims = s.claims || []; s.lessons = s.lessons || []; s.journal = s.journal || {};
      renderStats(s); renderProblems(s); renderChart(s); renderClaims(s); renderExperiments(s); renderLessons(s);
    })
    .catch(function (e) { $("updated").textContent = "Could not load research data (" + e.message + ")."; });
})();
