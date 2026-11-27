(function () {
  "use strict";
  var CFG = window.RSI_CONFIG || {};
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
  function clock(ts) { var d = new Date(ts * 1000); return d.toTimeString().slice(0, 8); }
  function statusClass(s) { return s === "verified" ? "ok" : (s === "rejected" ? "bad" : "warn"); }
  var KIND = { evidence: "Computational evidence", counterexample: "Counterexample candidate", witness: "Witness", observation: "Observation", proof: "Proof claim" };
  function stat(label, value, cls) { return h("div", { class: "stat " + (cls || "") }, h("b", {}, value), h("span", {}, label)); }
  function role(name) { return name.indexOf("Solver:") === 0 ? "solver" : name.toLowerCase(); }
  var seen = 0, firstLoad = true, ACTIVE_WINDOW = 300;

  function lastEventTs(s) { return s.events && s.events.length ? s.events[0].ts : 0; }
  function renderLive(s) {
    var last = lastEventTs(s), age = Date.now() / 1000 - last, dot = $("live-dot"), txt = $("live-text");
    if (!last) { dot.className = "dot off"; txt.textContent = "NO ACTIVITY YET"; }
    else if (age < 300) { dot.className = "dot live"; txt.textContent = "LIVE"; }
    else { dot.className = "dot idle"; txt.textContent = "IDLE · LAST ACTIVITY " + ago(last).toUpperCase(); }
  }
  function renderStats(s) {
    var ps = s.problems, exps = 0, ver = 0, best = null, events = (s.agents || []).reduce(function (a, g) { return a + g.events; }, 0), i;
    for (i = 0; i < ps.length; i++) {
      exps += ps[i].experiments; ver += ps[i].claims.verified || 0;
      var sp = ps[i].performance && ps[i].performance.speedup_vs_baseline;
      if (sp && (best === null || sp > best)) best = sp;
    }
    $("stats").replaceChildren(
      stat("Agents", (s.agents || []).length), stat("Experiments", num(exps)),
      stat("Verified claims", num(ver), ver ? "good" : ""), stat("Self-improvement", best ? num(best) + "×" : "–", best ? "good" : ""),
      stat("Prizes claimed", "0"), stat("Memory journal", s.journal && s.journal.ok ? "Intact" : "BROKEN", s.journal && s.journal.ok ? "good" : "bad"));
    $("updated").textContent = s.generated_at ? "Data published " + ago(s.generated_at) + " · " + num(events) + " logged agent actions" : "";
  }

  function renderNetwork(s) {
    var agents = s.agents || [], now = Date.now() / 1000, ns = "http://www.w3.org/2000/svg", W = 720, H = 360, i;
    if (!agents.length) { $("net").replaceChildren(h("div", { class: "empty" }, "No agent activity recorded yet.")); $("roster").replaceChildren(); return; }
    var by = {}; agents.forEach(function (a) { by[a.name] = a; });
    var solvers = agents.filter(function (a) { return a.name.indexOf("Solver:") === 0; });
    var pos = { Conductor: [360, 170], RSI: [120, 70], Auditor: [600, 70] };
    solvers.forEach(function (a, j) { pos[a.name] = [W * (j + 1) / (solvers.length + 1), 300]; });
    var svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Agent network");
    function el(t, a, parent) { var e = document.createElementNS(ns, t), k; for (k in a) e.setAttribute(k, a[k]); (parent || svg).appendChild(e); return e; }
    function active(n) { return by[n] && now - by[n].last_ts < ACTIVE_WINDOW; }
    function edge(a, b, cls) {
      if (!pos[a] || !pos[b]) return;
      el("line", { x1: pos[a][0], y1: pos[a][1], x2: pos[b][0], y2: pos[b][1], class: "edge " + (cls || "") + (active(a) && active(b) ? " active" : "") });
    }
    ["RSI", "Auditor"].concat(solvers.map(function (a) { return a.name; })).forEach(function (n) { edge("Conductor", n); });
    edge("RSI", "Auditor", "gate");
    Object.keys(pos).forEach(function (n) {
      if (!by[n]) return;
      var g = el("g", { class: "node n-" + role(n) + (active(n) ? " active" : "") });
      el("circle", { class: "ring", cx: pos[n][0], cy: pos[n][1], r: 26 }, g);
      el("circle", { class: "core", cx: pos[n][0], cy: pos[n][1], r: 26 }, g);
      var lab = n.indexOf("Solver:") === 0 ? "SOLVER" : n.toUpperCase();
      var t1 = el("text", { x: pos[n][0], y: pos[n][1] + 4 }, g); t1.textContent = lab.slice(0, 9);
      var t2 = el("text", { x: pos[n][0], y: pos[n][1] + 46, class: "sub" }, g); t2.textContent = n.indexOf("Solver:") === 0 ? n.slice(7).replace(/_/g, " ").slice(0, 22) : (by[n].events + " actions");
    });
    $("net").replaceChildren(svg);
    $("roster").replaceChildren.apply($("roster"), agents.map(function (a) {
      var on = active(a.name), col = { conductor: "#e9f2ed", rsi: "#c792ff", auditor: "#ffc857", solver: "#6fd3ff" }[role(a.name)];
      return h("div", { class: "agent" }, h("span", { class: "ic", style: "background:" + col }), h("span", { class: "nm" }, a.name.replace(/_/g, " ")),
        h("span", { class: "st " + (on ? "on" : "") }, on ? "ACTIVE" : "idle · " + ago(a.last_ts)), h("span", { class: "rl" }, a.role));
    }));
  }

  function renderFeed(s) {
    var feed = $("feed"), evs = s.events || [], maxId = evs.length ? evs[0].id : 0;
    $("feed-count").textContent = evs.length ? "last " + evs.length + " events" : "";
    if (!evs.length) { feed.replaceChildren(h("div", { class: "empty" }, "Waiting for agent activity…")); return; }
    feed.replaceChildren.apply(feed, evs.map(function (e) {
      var isNew = !firstLoad && e.id > seen;
      return h("div", { class: "ev k-" + e.kind + (isNew ? " new" : "") }, h("span", { class: "tm" }, clock(e.ts)),
        h("span", { class: "ag a-" + role(e.agent) }, e.agent.replace(/_/g, " ").toUpperCase()), h("span", { class: "ms" }, e.message));
    }));
    seen = Math.max(seen, maxId); firstLoad = false;
  }

  function problemStatus(s, p) {
    if (p.status && p.status.alert) return ["Alert: review needed", "bad"];
    var last = 0, i;
    for (i = 0; i < s.events.length; i++) if (s.events[i].problem_id === p.id) { last = s.events[i].ts; break; }
    if (!last) { for (i = 0; i < s.experiments.length; i++) if (s.experiments[i].problem_id === p.id) { last = Math.max(last, s.experiments[i].started || 0); } }
    return Date.now() / 1000 - last < 600 ? ["Active research", "ok"] : ["Idle", "warn"];
  }
  function renderProblems(s) {
    var list = $("problem-list");
    if (!s.problems.length) { list.replaceChildren(h("div", { class: "empty" }, "No research data published yet.")); return; }
    list.replaceChildren.apply(list, s.problems.map(function (p, idx) {
      var st = problemStatus(s, p), kv = h("dl", { class: "kv" }), k, v, pz = p.prize || {};
      for (k in (p.status || {})) {
        if (k === "references") continue;
        v = p.status[k]; if (v === null || v === undefined || v === "") continue;
        kv.append(h("dt", {}, k.replace(/_/g, " ")), h("dd", {}, typeof v === "number" ? num(v) : (typeof v === "object" ? JSON.stringify(v) : v)));
      }
      var cl = Object.keys(p.claims || {}).map(function (x) { return x + ": " + p.claims[x]; }).join(" · ") || "none";
      kv.append(h("dt", {}, "experiments"), h("dd", {}, num(p.experiments)), h("dt", {}, "claims"), h("dd", {}, cl));
      var perf = p.performance || {};
      if (perf.speedup_vs_baseline) kv.append(h("dt", {}, "best strategy"), h("dd", {}, perf.best_arm.replace(/_/g, " ") + " · " + num(perf.speedup_vs_baseline) + "× baseline"));
      var rows = Object.keys(p.arm_stats || {}).map(function (a) {
        var r = p.arm_stats[a]; return h("tr", {}, h("td", {}, a.replace(/_/g, " ")), h("td", {}, r.pulls), h("td", {}, (r.total_reward / r.pulls).toFixed(3)));
      });
      return h("article", { class: "card" },
        h("div", { class: "top mono" }, h("span", {}, String(idx + 1).padStart(2, "0") + " / " + String(s.problems.length).padStart(2, "0") + "  FL / " + (p.domain || "research").toUpperCase()), h("span", { class: "chip " + st[1] }, st[0])),
        h("h3", {}, p.title), h("p", {}, p.statement),
        pz.reward ? h("div", { class: "prize" }, h("b", {}, "PRIZE LEDGER · NOT CLAIMED" + (pz.terms_verified ? "" : " · TERMS UNVERIFIED")), pz.reward, pz.status ? h("div", { class: "mut", style: "margin-top:4px" }, pz.status) : null) : null,
        kv, rows.length ? h("table", { class: "mini" }, h("tr", {}, h("th", {}, "Strategy"), h("th", {}, "Runs"), h("th", {}, "Mean reward")), rows) : null,
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
    var ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Throughput per experiment by strategy");
    function el(t, a) { var e = document.createElementNS(ns, t), k; for (k in a) e.setAttribute(k, a[k]); svg.appendChild(e); return e; }
    function X(i) { return pad + (W - pad - 16) * (maxLen <= 1 ? 0.5 : i / (maxLen - 1)); }
    function Y(v) { return H - 30 - (H - 50) * ((Math.log10(v) - lo) / (hi - lo)); }
    for (i = Math.ceil(lo); i <= Math.floor(hi); i++) {
      el("line", { x1: pad, x2: W - 10, y1: Y(Math.pow(10, i)), y2: Y(Math.pow(10, i)), stroke: "rgba(255,255,255,.08)" });
      var t = el("text", { x: 6, y: Y(Math.pow(10, i)) + 4, fill: "#8aa097", "font-size": 11 }); t.textContent = "10^" + i;
    }
    names.forEach(function (n, j) {
      el("polyline", { points: groups[n].map(function (v, k) { return X(k) + "," + Y(v); }).join(" "), fill: "none", stroke: COLORS[j % 4], "stroke-width": 2.5, "stroke-linejoin": "round" });
      groups[n].forEach(function (v, k) { el("circle", { cx: X(k), cy: Y(v), r: 3.5, fill: COLORS[j % 4] }); });
    });
    box.replaceChildren(svg, h("div", { class: "legend" }, names.map(function (n, j) { return h("span", {}, h("i", { style: "background:" + COLORS[j % 4] }), n.replace(/_/g, " ")); })),
      h("div", { class: "legend" }, h("span", {}, "x: experiment order · y: items per second (log scale)")));
  }

  function renderBest(s) {
    var box = $("best-chart"), p = null, i;
    for (i = 0; i < s.problems.length; i++) if ((s.problems[i].best_series || []).length > 1) { p = s.problems[i]; break; }
    if (!p) { box.replaceChildren(h("div", { class: "empty" }, "No improving bound recorded yet.")); return; }
    var ys = p.best_series.map(function (r) { return r.value; }), refs = (p.status && p.status.references) || {}, W = 800, H = 300, pad = 56;
    var ymin = Math.min.apply(null, ys), ymax = Math.max.apply(null, ys), r;
    for (r in refs) { if (refs[r] > ymin - 0.004 && refs[r] < ymax + 0.004) { ymin = Math.min(ymin, refs[r]); ymax = Math.max(ymax, refs[r]); } }
    var lo = ymin - (ymax - ymin) * 0.08 - 1e-6, hi = ymax + (ymax - ymin) * 0.08 + 1e-6;
    var ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Best upper bound over time");
    function el(t, a, txt) { var e = document.createElementNS(ns, t), k; for (k in a) e.setAttribute(k, a[k]); if (txt) e.textContent = txt; svg.appendChild(e); return e; }
    function X(i) { return pad + (W - pad - 14) * (ys.length <= 1 ? 0.5 : i / (ys.length - 1)); }
    function Y(v) { return H - 28 - (H - 48) * ((v - lo) / (hi - lo)); }
    for (r in refs) { if (refs[r] >= lo && refs[r] <= hi) { el("line", { x1: pad, x2: W - 10, y1: Y(refs[r]), y2: Y(refs[r]), stroke: "rgba(255,200,87,.55)", "stroke-dasharray": "5 5" }); el("text", { x: pad + 4, y: Y(refs[r]) - 5, fill: "#ffc857", "font-size": 11 }, r + " " + refs[r]); } }
    var pts = []; ys.forEach(function (v, k) { pts.push(X(k) + "," + Y(v)); });
    el("polyline", { points: pts.join(" "), fill: "none", stroke: "#3dff9a", "stroke-width": 2.5, "stroke-linejoin": "round" });
    el("circle", { cx: X(ys.length - 1), cy: Y(ys[ys.length - 1]), r: 4.5, fill: "#3dff9a" });
    el("text", { x: 6, y: Y(hi) + 12, fill: "#8aa097", "font-size": 11 }, hi.toFixed(4)); el("text", { x: 6, y: Y(lo), fill: "#8aa097", "font-size": 11 }, lo.toFixed(4));
    box.replaceChildren(svg, h("div", { class: "legend" }, h("span", {}, "Best verified upper bound on the Erdős minimum overlap constant over time (lower is better). Dashed lines: published records."))); 
  }

  function listOrEmpty(boxId, items, msg, mk) {
    var box = $(boxId);
    if (!items.length) { box.replaceChildren(h("div", { class: "empty" }, msg)); return; }
    box.replaceChildren.apply(box, items.map(mk));
  }
  function renderRest(s) {
    listOrEmpty("claim-list", s.claims, "No claims recorded yet.", function (c) {
      return h("div", { class: "row" }, h("div", { class: "id" }, "#" + c.id), h("div", { class: "body" }, h("p", {}, c.statement),
        h("div", { class: "meta" }, h("span", { class: "chip " + statusClass(c.status) }, c.status.replace(/_/g, " ")), h("span", { class: "chip" }, KIND[c.kind] || c.kind),
          h("span", {}, (c.verifications || []).map(function (v) { return v.verifier.replace(/_/g, " ") + ": " + v.verdict; }).join(" · ")))));
    });
    listOrEmpty("lesson-list", s.lessons, "No lessons recorded yet.", function (l) {
      return h("div", { class: "row" }, h("div", { class: "id" }, l.tag.toUpperCase()), h("div", { class: "body" }, h("p", {}, l.text)));
    });
  }

  function render(s) {
    ["problems", "experiments", "claims", "lessons", "events", "agents"].forEach(function (k) { s[k] = s[k] || []; });
    s.journal = s.journal || {};
    renderLive(s); renderStats(s); renderNetwork(s); renderFeed(s); renderProblems(s); renderChart(s); renderBest(s); renderRest(s);
  }
  function get(url) { return fetch(url + (url.indexOf("?") < 0 ? "?" : "&") + "t=" + Date.now(), { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  function load() {
    var p = CFG.liveUrl ? get(CFG.liveUrl).catch(function () { return get("data/state.json"); }) : get("data/state.json");
    p.then(render).catch(function (e) { $("updated").textContent = "Could not load research data (" + e.message + ")."; });
  }
  load();
  setInterval(load, (CFG.pollSeconds || 20) * 1000);
})();
