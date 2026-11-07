"use strict";
const $ = (s, e = document) => e.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ago = t => { if (!t) return "never"; const s = Math.max(0, Date.now() / 1000 - t); return s < 60 ? Math.floor(s) + "s ago" : s < 3600 ? Math.floor(s / 60) + "m ago" : s < 86400 ? Math.floor(s / 3600) + "h ago" : Math.floor(s / 86400) + "d ago" };
const clock = t => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
async function api(path, body) {
  const r = await fetch("/api/" + path, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (r.status === 401) { document.body.innerHTML = "<div style='padding:40px'>Not authorised. Open the dashboard with the link printed by Hukum (it contains the access token).</div>"; throw new Error("401"); }
  return r.json();
}
function toast(msg, kind = "") { const d = document.createElement("div"); d.className = kind; d.textContent = msg; $("#toast").appendChild(d); setTimeout(() => d.remove(), 6500); }
const tag = (t, k = "") => `<span class="tag ${k}">${esc(t)}</span>`;
const sevTag = s => tag(s, { error: "err", warning: "warn", info: "info" }[s] || "");
const empty = t => `<div class="empty">${esc(t)}</div>`;
let S = {}, cur = "overview", timer = null, ov = null;

const NAV = [["overview", "Overview"], ["chat", "Hukum Chat"], ["monitor", "Live Monitor"], ["apps", "Applications"], ["projects", "Projects"], ["agents", "AI Agents"],
["tasks", "Task Manager"], ["whatsapp", "WhatsApp"], ["notifications", "Notifications"], ["activity", "Activity History"], ["memory", "Memory"], ["automation", "Automation"],
["integrations", "Integrations"], ["system", "System"], ["security", "Security & Audit"], ["settings", "Settings"]];
function drawNav() {
  const n = ov ? (ov.notifications.counts.error || 0) + (ov.notifications.counts.warning || 0) : 0;
  $("#nav").innerHTML = NAV.map(([k, l]) => `<a class="${k === cur ? "on" : ""}" onclick="go('${k}')">${l}${k === "notifications" && n ? `<span class="badge">${n}</span>` : ""}</a>`).join("");
}
function go(v) { cur = v; location.hash = v; drawNav(); clearInterval(timer); timer = null; $("#main").innerHTML = '<div class="mut thinking">Loading</div>'; V[v]().catch(e => { $("#main").innerHTML = `<div class="banner">Could not load this page: ${esc(e.message)}</div>` }); }
function every(ms, fn) { clearInterval(timer); timer = setInterval(() => { if (!document.hidden) fn().catch(() => { }) }, ms); }
const head = (t, s) => `<h1>${esc(t)}</h1><div class="sub">${s || ""}</div>`;
const meter = (v, label, unit = "%") => { v = v ?? 0; const c = v > 90 ? "err" : v > 75 ? "warn" : ""; return `<div class="card"><div class="mut">${label}</div><div class="stat">${Math.round(v)}<small>${unit}</small></div><div class="bar ${c}"><i style="width:${Math.min(100, v)}%"></i></div></div>`; };

// ---------------------------------------------------------------- views
const V = {};
V.overview = async () => {
  const draw = async () => {
    const o = ov = await api("overview"); const s = o.system;
    $("#main").innerHTML = head("Overview", "Everything Hukum can see right now. <span class='tag obs'>observed</span> = read from the screen or system, <span class='tag inf'>inferred</span> = a guess.") +
      (o.estop.on ? `<div class="banner"><b>Emergency stop is ON</b> (${esc(o.estop.reason)}). Nothing will run until you release it.</div>` : "") +
      `<div class="grid g4">${meter(s.cpu, "CPU")}${meter(s.ram, "RAM")}${meter(s.gpu, "GPU")}<div class="card"><div class="mut">Battery</div><div class="stat">${s.battery ? s.battery.percent : "-"}<small>${s.battery ? (s.battery.charging ? "% charging" : "% on battery") : "no battery"}</small></div></div></div>` +
      `<div class="grid g2" style="margin-top:14px"><div class="card hot"><h2>What you seem to be doing <span class="tag inf">inferred</span></h2>${o.context.app ? `<div>${esc(o.context.activity)}</div><div class="mut">${esc(o.context.app)} - ${esc(o.context.title || "")}</div>` : '<div class="mut">Nothing in front.</div>'}</div>
      <div class="card"><h2>Machine</h2><div>${esc(s.summary)}</div>${s.findings.map(f => `<div class="mut">• ${esc(f)}</div>`).join("")}</div></div>` +
      `<div class="grid g2" style="margin-top:14px"><div class="card"><h2>Recent observations</h2>${o.observations.length ? o.observations.map(x => `<div style="margin-bottom:8px">${sevTag(x.severity)} <b>${esc(x.title)}</b> <span class="mut">${esc(x.app)} - ${ago(x.ts)}</span><div class="mono mut">${esc(x.observed)}</div></div>`).join("") : empty("Nothing notable. Start monitoring to let Hukum watch your approved apps.")}</div>
      <div class="card"><h2>Coding agents</h2>${o.agents.length ? o.agents.map(j => `<div>#${j.id} ${esc(j.agent)} ${tag(j.status, j.status === "done" ? "ok" : j.status === "failed" ? "err" : "info")} <span class="mut">${esc(j.prompt.slice(0, 60))}</span></div>`).join("") : empty("No agent jobs yet.")}
      <h3>Open tasks</h3>${o.tasks.length ? o.tasks.map(t => `<div>• ${esc(t.title)} ${t.overdue ? tag("overdue", "err") : ""}</div>`).join("") : '<div class="mut">None.</div>'}</div></div>
      <div class="card" style="margin-top:14px"><h2>Ask Hukum</h2><div class="compose"><input id="quick" placeholder="e.g. open vscode, system status, what are my projects"><button class="btn pri" onclick="quick()">Go</button></div><div id="qout"></div></div>`;
    $("#quick").addEventListener("keydown", e => { if (e.key === "Enter") quick() });
  };
  await draw(); every(5000, draw);
};
window.quick = async () => { const t = $("#quick").value.trim(); if (!t) return; $("#qout").innerHTML = '<div class="mut thinking">Working</div>'; await api("chat", { text: t }); chatWait.quick = true; };

const chatWait = {}; let chatLog = [];
V.chat = async () => {
  const h = await api("chat/history"); chatLog = h.map(m => ({ role: m.role, text: m.text }));
  $("#main").innerHTML = head("Hukum Chat", "Type or speak. Risky actions always ask first.") + `<div class="chat"><div class="msgs" id="msgs"></div>
  <div class="compose"><button class="btn mic" id="mic" title="Speak" onclick="mic()">🎤</button><input id="cin" placeholder="Tell Hukum what to do..." autofocus><button class="btn pri" onclick="send()">Send</button></div></div>`;
  drawChat(); $("#cin").addEventListener("keydown", e => { if (e.key === "Enter") send() });
};
function drawChat() { const m = $("#msgs"); if (!m) return; m.innerHTML = chatLog.map(x => `<div class="m ${x.role === "user" ? "u" : "a"}">${esc(x.text)}${x.steps ? `<small>${x.steps.map(s => `${s.ok ? "✔" : "✖"} ${esc(s.tool)} ${s.risk ? "(" + esc(s.risk) + ")" : ""}`).join(" · ")}${x.via ? " · via " + esc(x.via) : ""}</small>` : ""}</div>`).join("") + (chatWait.pending ? '<div class="m a thinking">Working</div>' : ""); m.scrollTop = m.scrollHeight; }
window.send = async (txt) => { const i = $("#cin"); const t = (txt || i.value).trim(); if (!t) return; i.value = ""; chatLog.push({ role: "user", text: t }); chatWait.pending = true; drawChat(); await api("chat", { text: t }); };
function speak(t) { if (!S["voice.speak_replies"] || !window.speechSynthesis) return; const u = new SpeechSynthesisUtterance(t.slice(0, 400)); u.rate = S["voice.rate"] || 1; const v = speechSynthesis.getVoices().find(v => v.name === S["voice.voice"]); if (v) u.voice = v; speechSynthesis.cancel(); speechSynthesis.speak(u) }
let rec = null, wake = null;
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
window.mic = () => {
  if (!S["voice.enabled"]) return toast("Voice is switched off in Settings > Voice", "w");
  if (!SR) return toast("This browser has no speech recognition. Use Chrome or Edge.", "e");
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.lang = S["voice.lang"] || "en-IN"; rec.interimResults = false;
  $("#mic")?.classList.add("on");
  rec.onresult = e => { const t = e.results[0][0].transcript; if (cur !== "chat") go("chat"); setTimeout(() => send(t), 150) };
  rec.onerror = e => toast("Microphone: " + e.error, "e");
  rec.onend = () => { rec = null; $("#mic")?.classList.remove("on") };
  rec.start();
};
function startWake() {
  if (wake) { try { wake.stop() } catch { } wake = null }
  if (!S["voice.wake"] || !SR || !S["voice.enabled"]) return;
  wake = new SR(); wake.continuous = true; wake.lang = S["voice.lang"] || "en-IN";
  wake.onresult = e => { const t = e.results[e.results.length - 1][0].transcript.toLowerCase(); const w = (S["voice.wake_word"] || "hey hukum").toLowerCase(); const i = t.indexOf(w); if (i >= 0) { const cmd = t.slice(i + w.length).trim(); if (cmd) { go("chat"); setTimeout(() => send(cmd), 150) } else { toast("Listening...", "s"); window.mic() } } };
  wake.onend = () => { if (S["voice.wake"]) setTimeout(() => { try { wake.start() } catch { } }, 800) };
  try { wake.start() } catch { }
}

V.monitor = async () => {
  const draw = async () => {
    const [m, w] = await Promise.all([api("monitor"), api("windows")]); const st = m.status;
    $("#main").innerHTML = head("Live Monitor", "Hukum reads only the apps you approve (Settings > Monitoring). Passwords, banking and private windows are never captured.") +
      `<div class="card hot"><div class="row"><span class="tag ${st.mode === "running" ? "ok" : "warn"}">${esc(st.mode)}</span><span class="mut">${st.passes} passes · last ${ago(st.last_pass)} · every ${st.interval_s}s · schedule ${esc(st.schedule)}</span><span class="sp"></span>
      <button class="btn pri" ${st.mode === "running" ? "disabled" : ""} onclick="mon('${st.mode === "paused" ? "resume" : "start"}')">${st.mode === "paused" ? "Resume" : "Start"}</button>
      <button class="btn" ${st.mode !== "running" ? "disabled" : ""} onclick="mon('pause')">Pause</button><button class="btn danger" ${st.mode === "stopped" ? "disabled" : ""} onclick="mon('stop')">Stop</button><button class="btn" onclick="mon('tick')">Look now</button></div>
      <div class="mut" style="margin-top:8px">Scope: ${st.scope.map(esc).join(", ")}${st.last_error ? `<br><span style="color:var(--warn)">Last error: ${esc(st.last_error)}</span>` : ""}</div></div>
      <div class="grid g2" style="margin-top:14px"><div class="card"><h2>Inferred context</h2>${m.context.app ? esc(m.context.activity) + `<div class="mut">${esc(m.context.app)} · ${esc(m.context.title || "")}</div>` : "-"} ${tag("inferred", "inf")}
      <h3>Detectors</h3><div class="row">${m.detectors.map(d => `<span class="tag ${{ error: "err", warning: "warn", info: "info" }[d.severity]}" title="${esc(d.title)}">${esc(d.id)}</span>`).join("")}</div></div>
      <div class="card"><h2>Windows (what Hukum would see)</h2><table><tbody>${w.slice(0, 14).map(x => `<tr><td>${esc(x.app)}</td><td class="mut">${esc(x.title.slice(0, 44))}</td><td>${x.title === "(private)" ? tag("private", "warn") : `<button class="btn sm" onclick="look(${x.hwnd})">Read</button>`}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="card" style="margin-top:14px"><h2>Observations</h2>${m.recent.length ? `<table><tr><th>When</th><th>Severity</th><th>What</th><th>Observed on screen</th><th>Inferred meaning</th></tr>${m.recent.map(o => `<tr><td>${clock(o.ts)}</td><td>${sevTag(o.severity)}</td><td>${esc(o.title)}<div class="mut">${esc(o.app)} · ${esc(o.source)}</div></td><td class="mono">${esc(o.observed)}</td><td class="mut">${esc(o.inferred)}</td></tr>`).join("")}</table>` : empty("No detections yet.")}</div><div id="lookout"></div>`;
  };
  await draw(); every(5000, draw);
};
window.mon = async m => { const r = await api("monitor/control", { mode: m }); if (r.error) toast(r.error, "e"); V.monitor() };
window.look = async h => { const r = await api("monitor/look", { hwnd: h }); $("#lookout").innerHTML = `<div class="card" style="margin-top:14px"><h2>${r.ok ? esc(r.result.title) + " " + tag("OCR", "obs") : "Not read"}</h2>${r.ok ? `<pre>${esc(r.result.text)}</pre>` : `<div class="banner">${esc(r.error)}</div>`}</div>`; $("#lookout").scrollIntoView() };

V.apps = async () => {
  const draw = async () => {
    const a = await api("apps");
    $("#main").innerHTML = head("Applications", "Launch, focus and close are verified against the real window list. Close only asks apps to close.") +
      `<div class="card"><table><tr><th>App</th><th>State</th><th>Window</th><th>CPU</th><th>RAM</th><th>Active</th><th></th></tr>${a.map(x => `<tr><td><b>${esc(x.name)}</b> ${tag(x.kind)}</td><td>${x.running ? tag(x.foreground ? "in front" : "running", "ok") : tag("closed")}</td><td class="mut">${esc((x.active_window || "").slice(0, 36))}</td><td>${x.cpu}%</td><td>${x.mem_mb} MB</td><td class="mut">${ago(x.last_activity)}</td>
      <td class="row"><button class="btn sm" onclick="appact('launch','${x.id}')">${x.running ? "New" : "Launch"}</button><button class="btn sm" ${x.running ? "" : "disabled"} onclick="appact('focus','${x.id}')">Focus</button><button class="btn sm danger" ${x.running ? "" : "disabled"} onclick="appact('close','${x.id}')">Close</button></td></tr>`).join("")}</table></div>`;
  };
  await draw(); every(6000, draw);
};
window.appact = async (action, name) => { const r = await api("apps/action", { action, name }); if (!r.ok) toast(r.error, "e"); else toast(action + " " + name + " ✔", "s"); if (cur === "apps") V.apps() };

V.projects = async () => {
  const p = await api("projects");
  $("#main").innerHTML = head("Projects", "Detected from your allowed folders. Env files show key NAMES only, never values.") + `<div class="row" style="margin-bottom:12px"><button class="btn" onclick="rescan()">Rescan</button><span class="mut">${p.projects.length} projects · ${p.servers.length} dev servers running</span></div>` +
    (p.servers.length ? `<div class="card" style="margin-bottom:14px"><h2>Running servers</h2>${p.servers.map(s => `<div>${tag(":" + s.ports.join(","), "ok")} ${esc(s.name)} <b>${esc(s.project || "")}</b> <span class="mut mono">${esc(s.cmd.slice(0, 90))}</span></div>`).join("")}</div>` : "") +
    `<div class="grid g2">${p.projects.map(x => `<div class="card"><div class="row"><b>${esc(x.name)}</b>${(x.languages || []).map(l => tag(l, "info")).join("")}${(x.frameworks || []).map(l => tag(l)).join("")}<span class="sp"></span>${x.git ? tag(x.git.branch) : ""}${x.git && x.git.dirty ? tag(x.git.dirty + " changed", "warn") : x.git ? tag("clean", "ok") : ""}</div>
    <div class="mut mono" style="margin:6px 0">${esc(x.path)}</div>${x.git && x.git.last_commit ? `<div class="mut">last commit: ${esc(x.git.last_commit.split("|").slice(1).join(" · "))}</div>` : ""}
    ${x.ports && x.ports.length ? `<div>Ports: ${x.ports.join(", ")}</div>` : ""}${x.env_keys && x.env_keys.length ? `<div class="mut">Env keys: ${x.env_keys.slice(0, 8).map(esc).join(", ")}</div>` : ""}
    ${Object.keys(x.scripts || {}).length ? `<div class="mut">Scripts: ${Object.keys(x.scripts).slice(0, 8).map(esc).join(", ")}</div>` : ""}<div class="row" style="margin-top:8px"><button class="btn sm" onclick="askAgent('${esc(x.name)}')">Give to an agent</button><button class="btn sm" onclick="app2('${esc(x.path.replace(/\\/g, "\\\\"))}')">Open in VS Code</button></div></div>`).join("")}</div>`;
};
window.rescan = async () => { toast("Scanning..."); await api("projects/scan", {}); V.projects() };
window.app2 = async path => { const r = await api("apps/action", { action: "launch", name: "vscode", path }); toast(r.ok ? "Opened" : r.error, r.ok ? "s" : "e") };
window.askAgent = name => { go("agents"); setTimeout(() => { const s = $("#aproj"); if (s) s.value = name }, 400) };

V.agents = async () => {
  const draw = async (keepForm) => {
    const [a, p] = await Promise.all([api("agents"), api("projects")]);
    const f = keepForm && $("#aprompt") ? { p: $("#aprompt").value, pr: $("#aproj")?.value, ag: $("#aagent")?.value, ro: $("#aro")?.checked, v: $("#averify")?.value } : null;
    $("#main").innerHTML = head("AI Agents", "Hand coding work to Codex, Antigravity or Claude. One writer per repository; jobs can depend on each other.") +
      `<div class="grid g3">${Object.entries(a.drivers).map(([k, v]) => `<div class="card"><b>${esc(k)}</b> ${tag(v.available ? "ready" : "unavailable", v.available ? "ok" : "err")}<div class="mut">${esc(v.mode)}</div><div class="mut">${esc(v.note || "")}</div></div>`).join("")}</div>
      <div class="card" style="margin-top:14px"><h2>New job</h2><div class="row"><select id="aagent" style="width:150px">${Object.keys(a.drivers).map(k => `<option>${k}</option>`).join("")}</select><select id="aproj" class="grow">${p.projects.map(x => `<option>${esc(x.name)}</option>`).join("")}</select><label class="row"><input type="checkbox" id="aro"> read-only</label></div>
      <textarea id="aprompt" rows="3" style="margin-top:8px" placeholder="What should the agent do?"></textarea><div class="row" style="margin-top:8px"><input id="averify" class="grow" placeholder="Optional check command that must pass, e.g. python -m unittest"><button class="btn pri" onclick="runAgent()">Run</button></div></div>
      <div class="card" style="margin-top:14px"><h2>Jobs</h2>${a.jobs.length ? `<table><tr><th>#</th><th>Agent</th><th>Repo</th><th>Status</th><th>Task</th><th></th></tr>${a.jobs.map(j => `<tr><td>${j.id}</td><td>${esc(j.agent)}${j.readonly ? " " + tag("read-only") : ""}</td><td class="mut">${esc(j.repo.split("\\").pop())}</td><td>${tag(j.status, { done: "ok", failed: "err", running: "info" }[j.status] || "")}${j.verify_result ? " " + tag(j.verify_result.split("\n")[0], j.verify_result.startsWith("PASS") ? "ok" : "err") : ""}</td><td>${esc(j.prompt.slice(0, 70))}<div class="mut">${j.files.length ? j.files.length + " file(s) changed · " : ""}${ago(j.updated)}</div></td><td class="row"><button class="btn sm" onclick="jobOut(${j.id})">Output</button>${["queued", "running"].includes(j.status) ? `<button class="btn sm danger" onclick="jobCancel(${j.id})">Cancel</button>` : ""}</td></tr>`).join("")}</table>` : empty("No jobs yet.")}</div><div id="jobview"></div>`;
    if (f) { $("#aprompt").value = f.p; if (f.pr) $("#aproj").value = f.pr; if (f.ag) $("#aagent").value = f.ag; $("#aro").checked = f.ro; $("#averify").value = f.v }
  };
  await draw(); every(4000, () => draw(true));
};
window.runAgent = async () => { const r = await api("agents/run", { agent: $("#aagent").value, project: $("#aproj").value, prompt: $("#aprompt").value, readonly: $("#aro").checked, verify: $("#averify").value }); toast(r.ok ? "Queued job #" + r.result.id : r.error, r.ok ? "s" : "e"); if (r.ok) $("#aprompt").value = ""; V.agents() };
window.jobCancel = async id => { await api("agents/cancel", { id }); V.agents() };
window.jobOut = async id => { const j = await api("agents/job?id=" + id); $("#jobview").innerHTML = `<div class="card" style="margin-top:14px"><h2>Job #${id} output</h2><pre>${esc(j.output || "(nothing yet)")}</pre>${j.verify_result ? `<h3>Verification</h3><pre>${esc(j.verify_result)}</pre>` : ""}${j.files.length ? `<h3>Files changed</h3><pre>${esc(j.files.join("\n"))}</pre>` : ""}</div>`; $("#jobview").scrollIntoView() };

V.tasks = async () => {
  const t = await api("tasks"); const cols = { todo: "To do", doing: "In progress", done: "Done" };
  $("#main").innerHTML = head("Task Manager", "Tasks, deadlines and dependencies. Agent results update their task automatically.") +
    `<div class="card"><div class="row"><input id="tt" class="grow" placeholder="New task"><input id="td" type="date" style="width:160px"><select id="tp" style="width:110px"><option value="1">High</option><option value="2" selected>Normal</option><option value="3">Low</option></select><button class="btn pri" onclick="addTask()">Add</button></div></div>
    <div class="grid g3" style="margin-top:14px">${Object.entries(cols).map(([k, l]) => `<div class="card"><h2>${l} <span class="mut">${t.filter(x => x.status === k).length}</span></h2>${t.filter(x => x.status === k).map(x => `<div class="card" style="background:var(--card2);margin-bottom:8px"><div>${esc(x.title)}</div><div class="row mut" style="margin-top:6px">${x.due ? tag(x.due, x.overdue ? "err" : "") : ""}${tag("P" + x.priority)}${x.project ? tag(x.project) : ""}${x.blocked ? tag("blocked", "warn") : ""}</div><div class="row" style="margin-top:6px">${k !== "todo" ? `<button class="btn sm" onclick="tstat(${x.id},'todo')">←</button>` : ""}${k === "todo" ? `<button class="btn sm" onclick="tstat(${x.id},'doing')">Start</button>` : ""}${k === "doing" ? `<button class="btn sm" onclick="tstat(${x.id},'done')">Done</button>` : ""}<button class="btn sm danger" onclick="tdel(${x.id})">✕</button></div></div>`).join("") || '<div class="mut">-</div>'}</div>`).join("")}</div>`;
  $("#tt").addEventListener("keydown", e => { if (e.key === "Enter") addTask() });
};
window.addTask = async () => { const title = $("#tt").value.trim(); if (!title) return; const r = await api("tasks", { title, due: $("#td").value, priority: +$("#tp").value }); if (r.error) toast(r.error, "e"); V.tasks() };
window.tstat = async (id, status) => { await api("tasks/update", { id, status }); V.tasks() };
window.tdel = async id => { await api("tasks/delete", { id }); V.tasks() };

V.whatsapp = async () => {
  const w = await api("whatsapp");
  $("#main").innerHTML = head("WhatsApp", "Through your phone only. Hukum shows you the exact message and recipient and waits for approval before anything is sent.") +
    (w.paused ? `<div class="banner">Outgoing messages are paused (Settings > Communication).</div>` : "") +
    `<div class="grid g3"><div class="card"><div class="mut">Phone link (gateway)</div><div class="stat" style="font-size:18px">${w.gateway.reachable ? tag("reachable", "ok") : tag("unreachable", "err")}</div><div class="mut">${esc(w.gateway.error || (w.gateway.phone_seen_s != null ? "phone seen " + w.gateway.phone_seen_s + "s ago" : ""))}</div></div>
    <div class="card"><div class="mut">Phone over USB (adb)</div><div class="stat" style="font-size:18px">${w.phone_adb.connected ? tag("connected", "ok") : tag("not connected", "warn")}</div><div class="mut">${esc(w.phone_adb.error || "needed for new chats and contacts")}</div></div>
    <div class="card"><div class="mut">Sent / drafted</div><div class="stat">${w.history.length}</div></div></div>
    <div class="grid g2" style="margin-top:14px"><div class="card"><h2>Compose</h2><input id="wc" placeholder="Contact name (reply) or full number 919876543210 (new chat)"><textarea id="wt" rows="4" style="margin-top:8px" placeholder="Message"></textarea>
    <div class="row" style="margin-top:8px"><select id="wr" style="width:200px"><option value="reply">Reply to existing chat</option><option value="new">Start new chat (adb)</option></select><button class="btn" onclick="waDraft()">Save draft</button><button class="btn pri" onclick="waSend()">Send (asks first)</button></div></div>
    <div class="card"><h2>Phone inbox <span class="tag obs">observed</span></h2><pre>${esc(w.inbox)}</pre></div></div>
    <div class="card" style="margin-top:14px"><h2>History</h2>${w.history.length ? `<table>${w.history.map(m => `<tr><td class="mut">${clock(m.ts)}</td><td>${esc(m.contact)}</td><td>${esc(m.text.slice(0, 90))}</td><td>${tag(m.status, m.status === "sent" ? "ok" : m.status === "failed" ? "err" : "")}</td><td class="mut">${esc(m.via)}</td></tr>`).join("")}</table>` : empty("No messages yet.")}</div>`;
};
window.waDraft = async () => { const r = await api("whatsapp/draft", { contact: $("#wc").value, text: $("#wt").value }); toast("Draft saved", "s"); V.whatsapp() };
window.waSend = async () => { toast("Waiting for your approval (top right)..."); const r = await api("whatsapp/send", { contact: $("#wc").value, text: $("#wt").value, route: $("#wr").value }); toast(r.ok ? "Sent: " + JSON.stringify(r.result.result) : r.error, r.ok ? "s" : "e"); if (cur === "whatsapp") V.whatsapp() };

V.notifications = async () => {
  const draw = async () => {
    const n = await api("notifications");
    $("#main").innerHTML = head("Notifications", "Repeated alerts are grouped. Errors can also go to your phone (Settings > Notifications).") + `<div class="row" style="margin-bottom:12px"><button class="btn" onclick="ackAll()">Mark all read</button><button class="btn" onclick="testN()">Send a test</button></div>` +
      (n.items.length ? `<div class="card"><table>${n.items.map(x => `<tr style="${x.acked ? "opacity:.55" : ""}"><td style="width:70px">${sevTag(x.severity)}</td><td><b>${esc(x.title)}</b>${x.count > 1 ? " " + tag("×" + x.count) : ""}<div class="mut">${esc(x.body)}</div></td><td class="mut" style="width:90px">${ago(x.last_ts)}</td><td style="width:60px">${x.acked ? "" : `<button class="btn sm" onclick="ack(${x.id})">Read</button>`}</td></tr>`).join("")}</table></div>` : empty("No notifications."));
  };
  await draw(); every(6000, draw);
};
window.ack = async id => { await api("notifications/ack", { id }); V.notifications() };
window.ackAll = async () => { await api("notifications/ack", { all: true }); V.notifications() };
window.testN = async () => { await api("notifications/test", {}); V.notifications() };

V.activity = async () => {
  $("#main").innerHTML = head("Activity History", "A searchable timeline of what you and Hukum did.") + `<div class="row" style="margin-bottom:12px"><input id="aq" class="grow" placeholder="Search"><select id="ak" style="width:160px"><option value="">All</option><option>command</option><option>focus</option><option>detection</option><option>app</option></select><button class="btn" onclick="loadAct()">Search</button></div><div id="actl"></div>`;
  $("#aq").addEventListener("keydown", e => { if (e.key === "Enter") loadAct() }); loadAct();
};
window.loadAct = async () => { const a = await api("activity?q=" + encodeURIComponent($("#aq").value) + "&kind=" + $("#ak").value); $("#actl").innerHTML = a.length ? `<div class="card timeline">${a.map(x => `<div><span class="mut">${clock(x.ts)}</span> ${tag(x.kind)} ${x.app ? `<b>${esc(x.app)}</b> ` : ""}${esc(x.text.slice(0, 160))}</div>`).join("")}</div>` : empty("Nothing matches.") };

V.memory = async () => {
  const m = await api("memory");
  $("#main").innerHTML = head("Memory", "What Hukum remembers about you. Secrets are never stored. Delete anything you don't want kept.") + `<div class="card"><div class="row"><select id="mk" style="width:140px"><option>fact</option><option>pref</option><option>decision</option><option>objective</option></select><input id="mt" class="grow" placeholder="Something to remember"><button class="btn pri" onclick="addMem()">Remember</button></div></div>
  <div class="card" style="margin-top:14px">${m.length ? `<table>${m.map(x => `<tr><td style="width:90px">${tag(x.kind, "info")}</td><td>${x.pinned ? "📌 " : ""}${esc(x.text)}</td><td class="mut" style="width:90px">${ago(x.ts)}</td><td class="row"><button class="btn sm" onclick="pinMem(${x.id},${x.pinned ? 0 : 1})">${x.pinned ? "Unpin" : "Pin"}</button><button class="btn sm danger" onclick="delMem(${x.id})">Forget</button></td></tr>`).join("")}</table>` : empty("Nothing remembered yet.")}</div>`;
  $("#mt").addEventListener("keydown", e => { if (e.key === "Enter") addMem() });
};
window.addMem = async () => { const t = $("#mt").value.trim(); if (!t) return; await api("memory", { text: t, kind: $("#mk").value }); V.memory() };
window.delMem = async id => { await api("memory/forget", { id }); V.memory() };
window.pinMem = async (id, on) => { await api("memory/pin", { id, on: !!on }); V.memory() };

V.automation = async () => {
  const w = await api("workflows");
  $("#main").innerHTML = head("Automation", "Workflows run through the same permission manager: they can never do more than you allow.") +
    `<div class="card"><h2>Templates</h2><div class="row">${w.templates.map((t, i) => `<button class="btn" onclick="useTpl(${i})">${esc(t.name)}</button>`).join("")}</div></div>
    <div class="card" style="margin-top:14px"><h2>Editor</h2><input id="wfn" placeholder="Workflow name"><textarea id="wfs" rows="9" class="mono" style="margin-top:8px" placeholder='{"trigger":{"type":"schedule","at":"09:00"},"steps":[{"tool":"briefing"}],"notify":true}'></textarea><div class="mut">Triggers: schedule, interval, event, app, manual · conditions: time_between, app_running, weekday · steps use any tool name from the list below · "retry": N</div><div class="row" style="margin-top:8px"><button class="btn pri" onclick="saveWf()">Save</button></div></div>
    <div class="card" style="margin-top:14px"><h2>Workflows</h2>${w.items.length ? `<table>${w.items.map(x => `<tr><td><b>${esc(x.name)}</b><div class="mut mono">${esc(JSON.stringify(x.spec.trigger))}</div></td><td>${x.enabled ? tag("on", "ok") : tag("paused", "warn")}</td><td class="mut">${x.last ? tag(x.last.status, x.last.status === "ok" ? "ok" : "err") + " " + ago(x.last.ts) : "never run"}</td><td class="row"><button class="btn sm" onclick="wfa(${x.id},'run')">Run now</button><button class="btn sm" onclick="wfa(${x.id},'${x.enabled ? "disable" : "enable"}')">${x.enabled ? "Pause" : "Resume"}</button><button class="btn sm danger" onclick="wfa(${x.id},'delete')">Delete</button></td></tr>`).join("")}</table>` : empty("No workflows yet - pick a template.")}</div>
    <div class="card" style="margin-top:14px"><h2>Recent runs</h2>${w.runs.length ? w.runs.map(r => `<div>${tag(r.status, r.status === "ok" ? "ok" : r.status === "skipped" ? "" : "err")} <b>${esc(r.name || "")}</b> <span class="mut">${ago(r.ts)}</span><pre>${esc(r.log)}</pre></div>`).join("") : empty("No runs yet.")}</div>`;
  window._tpl = w.templates;
};
window.useTpl = i => { $("#wfn").value = window._tpl[i].name; $("#wfs").value = JSON.stringify(window._tpl[i].spec, null, 2) };
window.saveWf = async () => { let spec; try { spec = JSON.parse($("#wfs").value) } catch (e) { return toast("That is not valid JSON: " + e.message, "e") } const r = await api("workflows", { name: $("#wfn").value.trim(), spec }); if (r.error) toast(r.error, "e"); else { toast("Saved", "s"); V.automation() } };
window.wfa = async (id, action) => { await api("workflows/action", { id, action }); if (action === "run") toast("Started", "s"); setTimeout(V.automation, 1500) };

V.integrations = async () => {
  const i = await api("integrations");
  $("#main").innerHTML = head("Integrations", "What Hukum is connected to, and a real test for each.") + `<div class="grid g2">${i.map(x => `<div class="card"><div class="row"><span class="dot ${x.ok ? "ok" : "err"}"></span><b>${esc(x.name)}</b><span class="sp"></span><button class="btn sm" onclick="testInt('${x.id}',this)">Test</button></div><div class="mut mono" style="margin-top:6px">${esc(x.detail)}</div><div id="it_${x.id}" class="mut"></div></div>`).join("")}</div>`;
};
window.testInt = async (id, b) => { b.disabled = true; $("#it_" + id).textContent = "testing…"; const r = await api("integrations/test", { id }); $("#it_" + id).textContent = JSON.stringify(r).slice(0, 220); b.disabled = false };

function spark(vals, key, color) {
  if (!vals.length) return ""; const W = 300, H = 46; const pts = vals.map((v, i) => `${(i / Math.max(1, vals.length - 1) * W).toFixed(1)},${(H - (Math.min(100, v[key] || 0) / 100) * (H - 4) - 2).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline fill="none" stroke="${color}" stroke-width="2" points="${pts}"/></svg>`;
}
V.system = async () => {
  const draw = async () => {
    const s = await api("system"); const n = s.now;
    $("#main").innerHTML = head("System", esc(s.summary)) + `<div class="grid g4">${meter(n.cpu, "CPU")}${meter(n.ram, "RAM")}${meter(n.gpu, "GPU")}${meter(n.drives && n.drives[0] ? n.drives[0].percent : 0, "Disk " + (n.drives && n.drives[0] ? n.drives[0].path : ""))}</div>
    <div class="grid g3" style="margin-top:14px"><div class="card"><div class="mut">CPU (15 min)</div>${spark(s.history, "cpu", "#36B9FF")}</div><div class="card"><div class="mut">RAM (15 min)</div>${spark(s.history, "ram", "#786BFF")}</div><div class="card"><div class="mut">Network</div><div>↓ ${(n.net_down / 1024).toFixed(0)} KB/s ↑ ${(n.net_up / 1024).toFixed(0)} KB/s</div><div>Internet ${s.internet ? tag("online", "ok") : tag("offline", "err")}</div></div></div>
    <div class="card" style="margin-top:14px"><h2>Findings</h2>${s.findings.map(f => `<div>• ${esc(f)}</div>`).join("")}</div>
    <div class="grid g2" style="margin-top:14px"><div class="card"><h2>Top by CPU</h2><table>${s.top_cpu.map(p => `<tr><td>${esc(p.name)}</td><td>${p.cpu}%</td><td class="mut">${p.mem_mb} MB</td><td><button class="btn sm danger" onclick="kill(${p.pid},'${esc(p.name)}')">End</button></td></tr>`).join("")}</table></div>
    <div class="card"><h2>Top by memory</h2><table>${s.top_mem.map(p => `<tr><td>${esc(p.name)}</td><td>${p.mem_mb} MB</td><td class="mut">${p.cpu}%</td><td><button class="btn sm danger" onclick="kill(${p.pid},'${esc(p.name)}')">End</button></td></tr>`).join("")}</table></div></div>
    <div class="card" style="margin-top:14px"><h2>Dev servers</h2>${s.servers.length ? s.servers.map(x => `<div>${tag(":" + x.ports.join(","), "ok")} ${esc(x.name)} ${esc(x.project || "")} <span class="mut">${x.mem_mb} MB</span></div>`).join("") : empty("None listening.")}</div>`;
  };
  await draw(); every(5000, draw);
};
window.kill = async (pid, name) => { if (!confirm(`End ${name} (pid ${pid})? You will be asked to approve.`)) return; const r = await api("system/kill", { pid }); toast(r.ok ? "Ended " + name : r.error, r.ok ? "s" : "e") };

V.security = async () => {
  const draw = async () => {
    const [a, au] = await Promise.all([api("approvals"), api("audit")]);
    $("#main").innerHTML = head("Security & Audit", "Every action is risk-rated and logged. Critical actions need the word CONFIRM.") +
      `<div class="card hot"><h2>Waiting for you</h2>${a.pending.length ? a.pending.map(p => approvalCard(p)).join("") : empty("Nothing waiting.")}</div>
      <div class="card" style="margin-top:14px"><h2>Audit log</h2><table><tr><th>When</th><th>Who</th><th>Action</th><th>Risk</th><th>Result</th><th>Detail</th></tr>${au.map(x => `<tr><td class="mut">${clock(x.ts)}</td><td>${esc(x.actor)}</td><td>${esc(x.action)}<div class="mut mono">${esc((x.target || "").slice(0, 80))}</div></td><td>${tag(x.risk, { high: "warn", critical: "err" }[x.risk] || "")}</td><td>${tag(x.decision, ["allowed", "approved", "ok"].includes(x.decision) ? "ok" : ["denied", "failed", "rejected", "stopped", "expired"].includes(x.decision) ? "err" : "")}</td><td class="mut">${esc((x.detail || x.result || "").slice(0, 90))}</td></tr>`).join("")}</table></div>`;
  };
  await draw(); every(4000, draw);
};
function approvalCard(p) {
  const a = p.action || {}; const crit = p.risk === "critical";
  return `<div class="card" style="background:var(--card2);margin-bottom:10px"><div class="row">${tag(p.risk, crit ? "err" : "warn")}<b>${esc(p.summary)}</b></div><div class="mut mono">${esc(a.action || "")} · ${ago(p.ts)} · from ${esc(p.source)}</div>${crit ? `<input id="cf${p.id}" placeholder="Type CONFIRM to allow" style="margin-top:8px">` : ""}<div class="row" style="margin-top:8px"><button class="btn pri" onclick="decide(${p.id},'approve')">Approve</button><button class="btn danger" onclick="decide(${p.id},'reject')">Reject</button></div></div>`;
}
window.decide = async (id, decision) => { const typed = $("#cf" + id)?.value || ""; const r = await api("approvals/decide", { id, decision, typed }); if (!r.ok) toast(r.error || "Could not apply", "e"); closeModal(); refreshAppr(); if (cur === "security") V.security() };

V.settings = async () => {
  const items = await api("settings"); const groups = [...new Set(items.map(i => i.group))];
  $("#main").innerHTML = head("Settings", "Every control here changes real behaviour immediately. Secrets go to Windows Credential Manager.") + groups.map(g => `<div class="card setgrp"><h2>${g}</h2>${items.filter(i => i.group === g).map(i => `<div class="setrow"><label>${esc(i.key)}<small>${esc(i.desc)}</small></label><div>${ctl(i)}<small class="mut" id="st_${i.key.replace(/\./g, "_")}"></small></div></div>`).join("")}</div>`).join("");
  document.querySelectorAll("[data-k]").forEach(el => el.addEventListener("change", () => saveSet(el)));
};
function ctl(i) {
  const k = `data-k="${i.key}"`;
  if (i.kind === "bool") return `<input type="checkbox" ${k} ${i.value ? "checked" : ""}>`;
  if (i.kind === "choice") return `<select ${k}>${i.choices.map(c => `<option ${c === i.value ? "selected" : ""} value="${esc(c)}">${esc(c || "(none)")}</option>`).join("")}</select>`;
  if (i.kind === "int" || i.kind === "float") return `<input type="number" ${k} value="${esc(i.value)}" min="${i.min ?? ""}" max="${i.max ?? ""}" step="${i.kind === "float" ? "0.05" : "1"}">`;
  if (i.kind === "secret") return `<input type="password" ${k} placeholder="${i.is_set ? "●●●●●●●● (set - type to replace, empty to clear)" : "not set"}" autocomplete="new-password">`;
  return `<input type="text" ${k} value="${esc(i.value)}">`;
}
async function saveSet(el) {
  const key = el.dataset.k; const val = el.type === "checkbox" ? el.checked : el.value; const st = $("#st_" + key.replace(/\./g, "_"));
  const r = await api("settings", { key, value: val });
  if (r.error) { st.style.color = "var(--err)"; st.textContent = r.error; toast(r.error, "e"); } else { st.style.color = "var(--ok)"; st.textContent = "saved"; S[key] = el.type === "checkbox" ? el.checked : (isNaN(+val) || val === "" ? val : +val); applyTheme(); if (key.startsWith("voice.")) startWake(); setTimeout(() => st.textContent = "", 2000); }
  if (el.type === "password") el.value = "";
}
function applyTheme() { const r = document.documentElement.style; if (S["ui.accent"]) r.setProperty("--accent", S["ui.accent"]); r.setProperty("--fs", (S["ui.font_size"] || 14) + "px"); document.body.className = "motion-" + (S["ui.motion"] || "normal"); }

// ---------------------------------------------------------------- global chrome: side panel, approvals modal, e-stop, events
async function refreshSide() {
  try {
    ov = await api("overview"); const o = ov;
    $("#pMon").innerHTML = `<span class="dot ${o.monitor.mode === "running" ? "ok" : o.monitor.mode === "paused" ? "warn" : ""}"></span><span>Monitoring ${o.monitor.mode}</span>`;
    $("#pAi").innerHTML = `<span class="dot ${o.ai.available ? "ok" : "warn"}"></span><span>${o.ai.available ? esc(o.ai.model) : "AI not set"}</span>`;
    $("#pGw").innerHTML = `<span class="dot ${o.gateway.enabled ? (o.gateway.linked ? "ok" : "err") : ""}"></span><span>Phone link ${o.gateway.enabled ? (o.gateway.linked ? "live" : "down") : "off"}</span>`;
    const n = o.approvals.length; $("#nAppr").textContent = n; $("#nAppr").style.display = n ? "" : "none";
    $("#bStop").classList.toggle("on", o.estop.on); $("#bStop").textContent = o.estop.on ? "STOPPED - RELEASE" : "EMERGENCY STOP";
    $("#orb").style.background = o.estop.on ? "var(--err)" : "var(--ok)";
    const s = o.system;
    $("#side").innerHTML = `<h3 style="margin-top:0">Intelligence</h3><div class="card" style="margin-bottom:12px"><div class="mut">Context ${tag("inferred", "inf")}</div><div>${o.context.app ? esc(o.context.activity) : "idle"}</div></div>
    <div class="card" style="margin-bottom:12px"><div class="mut">Machine</div><div class="row"><span>CPU ${Math.round(s.cpu)}%</span><span>RAM ${Math.round(s.ram)}%</span>${s.gpu != null ? `<span>GPU ${Math.round(s.gpu)}%</span>` : ""}</div></div>
    <h3>Alerts</h3>${o.notifications.recent.length ? o.notifications.recent.map(x => `<div class="card" style="margin-bottom:8px">${sevTag(x.severity)} <b>${esc(x.title)}</b><div class="mut">${esc(x.body.slice(0, 120))}</div></div>`).join("") : '<div class="mut">All clear.</div>'}
    <h3>Waiting for you</h3>${o.approvals.length ? o.approvals.map(p => `<div class="card" style="margin-bottom:8px">${tag(p.risk, "warn")} ${esc(p.summary.slice(0, 100))}</div>`).join("") : '<div class="mut">Nothing.</div>'}
    <h3>Agents</h3>${o.agents.slice(0, 4).map(j => `<div>#${j.id} ${esc(j.agent)} ${tag(j.status)}</div>`).join("") || '<div class="mut">Idle.</div>'}`;
    drawNav();
  } catch { }
}
async function refreshAppr() { const a = await api("approvals"); if (a.pending.length && !$(".modal")) showModal(a.pending[0]); if (!a.pending.length) closeModal(); }
function showModal(p) { const d = document.createElement("div"); d.className = "modal"; d.innerHTML = `<div class="card"><h2>Hukum needs your approval</h2>${approvalCard(p)}</div>`; document.body.appendChild(d); }
function closeModal() { document.querySelectorAll(".modal").forEach(m => m.remove()) }
window.estop = async () => { const on = !ov?.estop.on; if (on && !confirm("Stop everything now? Running agents are cancelled and pending approvals rejected.")) return; await api("estop", { on }); toast(on ? "Emergency stop ON" : "Released", on ? "e" : "s"); refreshSide() };
function connect() {
  const es = new EventSource("/api/events");
  es.addEventListener("notification", e => { const n = JSON.parse(e.data); if (n.raised) toast(n.title, n.severity === "error" ? "e" : n.severity === "warning" ? "w" : ""); refreshSide(); if (n.raised && S["notify.speak"]) speak(n.title) });
  es.addEventListener("approval", e => { const d = JSON.parse(e.data); if (d.status === "pending") refreshAppr(); else { closeModal(); refreshAppr() } refreshSide() });
  es.addEventListener("estop", () => refreshSide());
  es.addEventListener("chat_reply", e => {
    const d = JSON.parse(e.data); chatWait.pending = false;
    if (cur === "chat") { chatLog.push({ role: "assistant", text: d.reply, steps: d.steps, via: d.via }); drawChat(); }
    else if (cur === "overview" && $("#qout")) $("#qout").innerHTML = `<pre>${esc(d.reply)}</pre>`;
    speak(d.reply);
  });
  es.addEventListener("agent_job", () => { if (cur === "agents") V.agents() });
  es.onerror = () => { };
}
async function boot() {
  try { (await api("settings")).forEach(i => S[i.key] = i.value) } catch { }
  applyTheme(); drawNav(); await refreshSide(); setInterval(() => { if (!document.hidden) refreshSide() }, 6000);
  connect(); refreshAppr(); startWake();
  const v = location.hash.slice(1); go(V[v] ? v : "overview");
}
boot();
