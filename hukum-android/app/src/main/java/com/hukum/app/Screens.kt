package com.hukum.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject

@Composable
fun Page(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { content() }
}

@Composable
fun H(t: String, sub: String = "") {
    Column { Text(t, color = C.tx, fontSize = 22.sp); if (sub.isNotBlank()) Mut(sub) }
}

/** Loads data (and optionally refreshes it every `every` ms) and shows loading / error states. */
@Composable
fun <T> Load(vm: DeskVM, every: Long = 0, fetch: suspend () -> T, content: @Composable (T) -> Unit) {
    var data by remember { mutableStateOf<T?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(vm.tick) {
        while (true) {
            try { data = fetch(); err = null } catch (e: Exception) { err = e.message ?: "failed" }
            if (every <= 0) break
            delay(every)
        }
    }
    val d = data
    when {
        d != null -> content(d)
        err != null -> Panel { Text("⚠ $err", color = C.warn); Spacer(Modifier.height(8.dp)); Btn("Retry") { vm.tick++ } }
        else -> Mut("Loading from your PC…")
    }
}

@Composable
fun Confirm(title: String, text: String, yes: String = "Do it", danger: Boolean = false, onYes: () -> Unit, onNo: () -> Unit) {
    AlertDialog(onDismissRequest = onNo, containerColor = C.panel, titleContentColor = C.tx, textContentColor = C.mut,
        title = { Text(title) }, text = { Text(text) },
        confirmButton = { TextButton(onClick = { onYes(); onNo() }) { Text(yes, color = if (danger) C.err else C.accent) } },
        dismissButton = { TextButton(onClick = onNo) { Text("Cancel", color = C.mut) } })
}

@Composable
fun Field(value: String, onChange: (String) -> Unit, hint: String, modifier: Modifier = Modifier, single: Boolean = true) {
    OutlinedTextField(value, onChange, modifier.fillMaxWidth(), placeholder = { Text(hint, color = C.mut) }, singleLine = single)
}

// ================================================================ PC (home / command center)
@Composable
fun PcScreen(vm: DeskVM, go: (String) -> Unit) {
    val h = vm.home
    var cmd by remember { mutableStateOf("") }
    Page {
        Panel(hot = true) {
            Blob(210.dp, energy = if (vm.thinking) 0.8f else 0.2f)
            Text(if (h != null) h.s("pc", "PC") else "PC", color = C.tx, fontSize = 18.sp, modifier = Modifier.align(Alignment.CenterHorizontally))
            Mut(when {
                vm.error != null -> vm.error!!
                h == null -> "Connecting to your PC…"
                else -> "Monitoring ${h.s("monitor")} · AI ${if (h.optJSONObject("ai")?.optBoolean("available") == true) h.optJSONObject("ai")!!.s("model") else "not set"}"
            }, Modifier.align(Alignment.CenterHorizontally))
        }
        if (h != null) {
            val ctx = h.optJSONObject("context")
            if (ctx != null && ctx.has("app") && !ctx.isNull("app")) Panel {
                Row(verticalAlignment = Alignment.CenterVertically) { Title("Boss is now"); Spacer(Modifier.padding(4.dp)); Chip("inferred", C.accent2) }
                Tx(ctx.s("activity")); Mut("${ctx.s("app")} · ${ctx.s("title").take(60)}")
            }
            Row2({ Meter("CPU", h.optDouble("cpu"), it) }, { Meter("RAM", h.optDouble("ram"), it) })
            Row2({ Meter("GPU", if (h.isNull("gpu")) null else h.optDouble("gpu"), it) }, { m ->
                val b = h.optJSONObject("battery")
                Panel(m) { Mut("Battery"); Text(if (b != null) "${b.optInt("percent")}%" else "-", color = C.tx, fontSize = 24.sp); Mut(if (b?.optBoolean("charging") == true) "charging" else "on battery") }
            })
            Panel {
                Title("Command Hukum on your PC")
                Field(cmd, { cmd = it }, "open vscode · system status · ask codex to …")
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Btn("Send", primary = true, enabled = !vm.thinking) { vm.ask(cmd); cmd = "" }
                    Btn("Briefing") { vm.ask("briefing") }
                    Btn("System") { vm.ask("system status") }
                }
                if (vm.thinking) Mut("Working…", Modifier.padding(top = 8.dp))
                vm.lastReply?.let { Text(it, color = C.tx, fontSize = 14.sp, modifier = Modifier.padding(top = 10.dp)) }
            }
            val mon = h.s("monitor")
            Panel {
                Title("Quick actions")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Btn(if (mon == "running") "Pause monitor" else "Start monitor") { vm.act("/api/monitor/control", JSONObject().put("mode", if (mon == "running") "pause" else if (mon == "paused") "resume" else "start"), "Monitoring updated") }
                    Btn("VS Code") { vm.ask("open vscode") }
                    Btn("Chrome") { vm.ask("open chrome") }
                }
            }
            val obs = h.arr("observations")
            Panel {
                Title("Noticed on screen")
                if (obs.isEmpty()) Mut("Nothing notable. Start monitoring to let Hukum watch your approved apps.")
                obs.forEach { o ->
                    Row(verticalAlignment = Alignment.Top, modifier = Modifier.padding(bottom = 8.dp)) {
                        Chip(o.s("severity"), sevColor(o.s("severity"))); Spacer(Modifier.padding(4.dp))
                        Column { Tx(o.s("title"), size = 14); Mut("Observed: ${o.s("observed").take(90)}", size = 12); Mut("Inferred: ${o.s("inferred")}", size = 12) }
                    }
                }
            }
            val ag = h.arr("agents")
            if (ag.isNotEmpty()) Panel(Modifier) {
                Title("Coding agents"); ag.forEach { j -> Row(Modifier.padding(bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) { Chip(j.s("status"), sevColor(j.s("status"))); Spacer(Modifier.padding(4.dp)); Tx("#${j.optInt("id")} ${j.s("agent")} – ${j.s("prompt").take(40)}", size = 13) } }
                Btn("Open agents") { go("agents") }
            }
        }
    }
}

// ================================================================ Agents
@Composable
fun AgentsScreen(vm: DeskVM) {
    var agent by remember { mutableStateOf("antigravity") }
    var project by remember { mutableStateOf("") }
    var prompt by remember { mutableStateOf("") }
    var ro by remember { mutableStateOf(false) }
    var verify by remember { mutableStateOf("") }
    var open by remember { mutableStateOf<Int?>(null) }
    var confirm by remember { mutableStateOf(false) }
    Page {
        H("AI Agents", "Hand coding work to Codex, Antigravity or Claude on your PC")
        Load(vm, 4000, { Pair(vm.obj("/api/agents"), vm.obj("/api/projects")) }) { (a, p) ->
            val drivers = a.optJSONObject("drivers") ?: JSONObject()
            val names = drivers.keys().asSequence().toList()
            val projects = p.arr("projects").map { it.s("name") }
            if (project.isBlank() && projects.isNotEmpty()) project = projects.first()
            Panel {
                Title("New job")
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    names.forEach { n -> val ok = drivers.getJSONObject(n).optBoolean("available"); Btn(n + if (ok) "" else " ✖", primary = agent == n, enabled = ok) { agent = n } }
                }
                Spacer(Modifier.height(8.dp))
                Mut("Project: $project")
                projects.chunked(3).forEach { row -> Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(vertical = 3.dp)) { row.forEach { n -> Btn(n, primary = project == n) { project = n } } } }
                Field(prompt, { prompt = it }, "What should the agent do?", single = false)
                Field(verify, { verify = it }, "Optional check command (must pass)")
                Row(verticalAlignment = Alignment.CenterVertically) { Switch(ro, { ro = it }); Mut("  read-only (no edits)") }
                Spacer(Modifier.height(6.dp))
                Btn("Run on PC", primary = true, enabled = prompt.isNotBlank() && project.isNotBlank()) { confirm = true }
            }
            if (confirm) Confirm("Start $agent?", "Project: $project\n${if (ro) "Read-only" else "It may edit files"}\n\n$prompt", "Run", onYes = {
                vm.act("/api/agents/run", JSONObject().put("agent", agent).put("project", project).put("prompt", prompt).put("readonly", ro).put("verify", verify), "Job queued"); prompt = ""
            }, onNo = { confirm = false })
            val jobs = a.arr("jobs")
            Panel {
                Title("Jobs")
                if (jobs.isEmpty()) Mut("No jobs yet.")
                jobs.forEach { j ->
                    val id = j.optInt("id")
                    Column(Modifier.padding(bottom = 10.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Chip(j.s("status"), sevColor(j.s("status"))); Spacer(Modifier.padding(4.dp)); Tx("#$id ${j.s("agent")}", size = 14)
                            if (j.s("verify_result").isNotBlank()) { Spacer(Modifier.padding(3.dp)); Chip(j.s("verify_result").lines().first(), if (j.s("verify_result").startsWith("PASS")) C.ok else C.err) }
                        }
                        Mut(j.s("prompt").take(120)); Mut("${j.optJSONArray("files")?.length() ?: 0} file(s) changed · ${ago(j.optDouble("updated"))}", size = 12)
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 4.dp)) {
                            Btn(if (open == id) "Hide" else "Output") { open = if (open == id) null else id }
                            if (j.s("status") in listOf("queued", "running")) Btn("Cancel", danger = true) { vm.act("/api/agents/cancel", JSONObject().put("id", id), "Cancelled") }
                        }
                        if (open == id) Load(vm, 3000, { vm.obj("/api/agents/job?id=$id") }) { full -> Text(full.s("output").takeLast(1800).ifBlank { "(nothing yet)" }, color = C.mut, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp)) }
                    }
                }
            }
        }
    }
}

// ================================================================ Tasks
@Composable
fun TasksScreen(vm: DeskVM) {
    var title by remember { mutableStateOf("") }
    var due by remember { mutableStateOf("") }
    Page {
        H("Tasks", "Shared with the PC dashboard")
        Panel {
            Field(title, { title = it }, "New task")
            Field(due, { due = it }, "Due date YYYY-MM-DD (optional)")
            Spacer(Modifier.height(6.dp))
            Btn("Add", primary = true, enabled = title.isNotBlank()) {
                vm.act("/api/tasks", JSONObject().put("title", title).put("due", due.trim()), "Task added"); title = ""; due = ""
            }
        }
        Load(vm, 8000, { vm.arr("/api/tasks") }) { tasks ->
            listOf("doing" to "In progress", "todo" to "To do", "done" to "Done").forEach { (st, label) ->
                val items = tasks.list().filter { it.s("status") == st }
                if (items.isNotEmpty()) Panel {
                    Title("$label · ${items.size}")
                    items.forEach { t ->
                        Column(Modifier.padding(bottom = 10.dp)) {
                            Tx(t.s("title"))
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                if (t.s("due").isNotBlank()) Chip(t.s("due"), if (t.optBoolean("overdue")) C.err else C.mut)
                                Chip("P${t.optInt("priority")}"); if (t.optBoolean("blocked")) Chip("blocked", C.warn)
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 4.dp)) {
                                val id = t.optInt("id")
                                if (st == "todo") Btn("Start") { vm.act("/api/tasks/update", JSONObject().put("id", id).put("status", "doing"), "Started") }
                                if (st == "doing") Btn("Done") { vm.act("/api/tasks/update", JSONObject().put("id", id).put("status", "done"), "Done") }
                                if (st != "todo") Btn("To do") { vm.act("/api/tasks/update", JSONObject().put("id", id).put("status", "todo"), "Moved") }
                                Btn("Delete", danger = true) { vm.act("/api/tasks/delete", JSONObject().put("id", id), "Deleted") }
                            }
                        }
                    }
                }
            }
            if (tasks.length() == 0) Mut("No tasks yet.")
        }
    }
}

// ================================================================ Alerts
@Composable
fun AlertsScreen(vm: DeskVM) {
    Page {
        H("Alerts", "What Hukum noticed on your PC")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Btn("Mark all read") { vm.act("/api/notifications/ack", JSONObject().put("all", true), "All read") }
            Btn("Send test") { vm.act("/api/notifications/test", JSONObject(), "Test sent") }
        }
        Load(vm, 6000, { vm.obj("/api/notifications") }) { n ->
            val items = n.arr("items")
            if (items.isEmpty()) Panel { Mut("No notifications.") }
            items.forEach { x ->
                Panel {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Chip(x.s("severity"), sevColor(x.s("severity"))); Spacer(Modifier.padding(4.dp)); Tx(x.s("title"), size = 14, bold = x.optInt("acked") == 0)
                        if (x.optInt("count") > 1) { Spacer(Modifier.padding(3.dp)); Chip("×${x.optInt("count")}") }
                    }
                    Mut(x.s("body").take(220), size = 12); Mut(ago(x.optDouble("last_ts")), size = 11)
                    if (x.optInt("acked") == 0) Btn("Read", Modifier.padding(top = 6.dp)) { vm.act("/api/notifications/ack", JSONObject().put("id", x.optInt("id")), "Read") }
                }
            }
        }
    }
}

// ================================================================ More: menu + sub pages
@Composable
fun MoreScreen(vm: DeskVM, onConnection: () -> Unit) {
    var sub by remember { mutableStateOf<String?>(null) }
    if (sub == null) {
        Page {
            H("More", "Everything on your PC")
            MenuList(listOf("apps" to "📱  Applications", "projects" to "📁  Projects", "system" to "📊  System & processes", "monitor" to "👁  Live monitor", "whatsapp" to "💬  WhatsApp",
                "voice" to "🎙  Voice & wake word", "alerts" to "🔔  Alerts", "memory" to "🧠  Memory", "automation" to "⚙  Automation", "security" to "🛡  Approvals & audit", "connection" to "🔗  Connection & permissions")) { if (it == "connection") onConnection() else sub = it }
        }
    } else {
        Column(Modifier.fillMaxSize()) {
            Btn("‹ Back", Modifier.padding(start = 16.dp, top = 8.dp)) { sub = null }
            when (sub) {
                "apps" -> AppsPage(vm); "projects" -> ProjectsPage(vm); "system" -> SystemPage(vm); "monitor" -> MonitorPage(vm)
                "whatsapp" -> WhatsPage(vm); "voice" -> VoicePage(); "alerts" -> AlertsScreen(vm); "memory" -> MemoryPage(vm); "automation" -> AutomationPage(vm); "security" -> SecurityPage(vm)
            }
        }
    }
}

@Composable
fun MenuList(items: List<Pair<String, String>>, onPick: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items.forEach { (k, l) -> Btn(l, Modifier.fillMaxWidth()) { onPick(k) } }
    }
}

@Composable
fun AppsPage(vm: DeskVM) {
    var close by remember { mutableStateOf<String?>(null) }
    Page {
        H("Applications")
        Load(vm, 6000, { vm.arr("/api/apps") }) { apps ->
            apps.list().forEach { a ->
                Panel {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Tx(a.s("name"), bold = true); Spacer(Modifier.padding(4.dp)); Chip(if (a.optBoolean("running")) (if (a.optBoolean("foreground")) "in front" else "running") else "closed", if (a.optBoolean("running")) C.ok else C.mut)
                    }
                    if (a.s("active_window").isNotBlank()) Mut(a.s("active_window").take(60), size = 12)
                    if (a.optBoolean("running")) Mut("CPU ${a.optDouble("cpu")}% · ${a.optInt("mem_mb")} MB", size = 12)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 6.dp)) {
                        Btn(if (a.optBoolean("running")) "New window" else "Launch") { vm.act("/api/apps/action", JSONObject().put("action", "launch").put("name", a.s("id")), "Launched ${a.s("name")}") }
                        if (a.optBoolean("running")) { Btn("Focus") { vm.act("/api/apps/action", JSONObject().put("action", "focus").put("name", a.s("id")), "Focused") }; Btn("Close", danger = true) { close = a.s("id") } }
                    }
                }
            }
        }
    }
    close?.let { Confirm("Close $it?", "Hukum asks the app to close. It may ask you to save at the PC.", "Close", true, { vm.act("/api/apps/action", JSONObject().put("action", "close").put("name", it), "Close requested") }, { close = null }) }
}

@Composable
fun ProjectsPage(vm: DeskVM) {
    Page {
        H("Projects")
        Load(vm, 0, { vm.obj("/api/projects") }) { p ->
            val servers = p.arr("servers")
            if (servers.isNotEmpty()) Panel { Title("Running servers"); servers.forEach { Tx(":${it.optJSONArray("ports").strings().joinToString(",")}  ${it.s("name")}  ${it.s("project")}", size = 13) } }
            p.arr("projects").forEach { x ->
                val g = x.optJSONObject("git")
                Panel {
                    Row(verticalAlignment = Alignment.CenterVertically) { Tx(x.s("name"), bold = true); Spacer(Modifier.padding(4.dp)); if (g != null) Chip(if (g.optInt("dirty") > 0) "${g.optInt("dirty")} changed" else "clean", if (g.optInt("dirty") > 0) C.warn else C.ok) }
                    Mut((x.optJSONArray("languages").strings() + x.optJSONArray("frameworks").strings()).joinToString(" · "), size = 12)
                    if (g != null) Mut("branch ${g.s("branch")}", size = 12)
                }
            }
            Btn("Rescan") { vm.act("/api/projects/scan", JSONObject(), "Rescanned") }
        }
    }
}

@Composable
fun SystemPage(vm: DeskVM) {
    var kill by remember { mutableStateOf<JSONObject?>(null) }
    Page {
        H("System")
        Load(vm, 5000, { vm.obj("/api/system") }) { s ->
            Mut(s.s("summary"), size = 13)
            val n = s.optJSONObject("now")
            if (n != null) { Row2({ Meter("CPU", n.optDouble("cpu"), it) }, { Meter("RAM", n.optDouble("ram"), it) }) }
            Panel { Title("Findings"); s.optJSONArray("findings").strings().forEach { Tx("• $it", size = 13) } }
            Panel { Title("Top by CPU"); s.arr("top_cpu").forEach { p -> Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 4.dp)) { Tx("${p.s("name")}  ${p.optDouble("cpu")}%  ${p.optInt("mem_mb")}MB", Modifier.weight(1f), 13); Btn("End", danger = true) { kill = p } } } }
            Panel { Title("Top by memory"); s.arr("top_mem").forEach { p -> Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 4.dp)) { Tx("${p.s("name")}  ${p.optInt("mem_mb")}MB", Modifier.weight(1f), 13); Btn("End", danger = true) { kill = p } } } }
        }
    }
    kill?.let { Confirm("End ${it.s("name")}?", "Process ${it.optInt("pid")} will be terminated. Unsaved work in it is lost.", "End process", true, { vm.act("/api/system/kill", JSONObject().put("pid", it.optInt("pid")), "Ended ${it.s("name")}") }, { kill = null }) }
}

@Composable
fun MonitorPage(vm: DeskVM) {
    Page {
        H("Live monitor", "Only apps you approved on the PC; passwords and private windows are never read")
        Load(vm, 5000, { vm.obj("/api/monitor") }) { m ->
            val st = m.optJSONObject("status") ?: JSONObject()
            Panel(hot = true) {
                Row(verticalAlignment = Alignment.CenterVertically) { Chip(st.s("mode"), if (st.s("mode") == "running") C.ok else C.warn); Spacer(Modifier.padding(4.dp)); Mut("${st.optInt("passes")} passes · every ${st.optInt("interval_s")}s") }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 8.dp)) {
                    val mode = st.s("mode")
                    Btn(if (mode == "paused") "Resume" else "Start", primary = true, enabled = mode != "running") { vm.act("/api/monitor/control", JSONObject().put("mode", if (mode == "paused") "resume" else "start"), "Monitoring on") }
                    Btn("Pause", enabled = mode == "running") { vm.act("/api/monitor/control", JSONObject().put("mode", "pause"), "Paused") }
                    Btn("Stop", danger = true, enabled = mode != "stopped") { vm.act("/api/monitor/control", JSONObject().put("mode", "stop"), "Stopped") }
                    Btn("Look now") { vm.act("/api/monitor/control", JSONObject().put("mode", "tick"), "Looked") }
                }
            }
            val rec = m.arr("recent")
            Panel {
                Title("Detections")
                if (rec.isEmpty()) Mut("None yet.")
                rec.forEach { o -> Column(Modifier.padding(bottom = 8.dp)) { Row { Chip(o.s("severity"), sevColor(o.s("severity"))); Spacer(Modifier.padding(4.dp)); Tx(o.s("title"), size = 14) }; Mut("Observed: ${o.s("observed").take(100)}", size = 12); Mut("Inferred: ${o.s("inferred")}", size = 12) } }
            }
        }
    }
}

@Composable
fun WhatsPage(vm: DeskVM) {
    var contact by remember { mutableStateOf("") }
    var text by remember { mutableStateOf("") }
    var newChat by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    Page {
        H("WhatsApp", "Sent through your phone. You always see the exact message first.")
        Panel {
            Title("Compose")
            Field(contact, { contact = it }, "Contact name (reply) or full number 919876543210")
            Field(text, { text = it }, "Message", single = false)
            Row(verticalAlignment = Alignment.CenterVertically) { Switch(newChat, { newChat = it }); Mut("  start a new chat (needs USB/adb on the PC)") }
            Spacer(Modifier.height(6.dp))
            Btn("Review & send", primary = true, enabled = contact.isNotBlank() && text.isNotBlank()) { confirm = true }
        }
        Load(vm, 0, { vm.obj("/api/whatsapp") }) { w ->
            Panel { Title("Phone inbox"); Text(w.s("inbox").take(1500), color = C.mut, fontSize = 12.sp) }
            Panel { Title("History"); w.arr("history").take(12).forEach { Mut("${it.s("contact")}: ${it.s("text").take(60)}  [${it.s("status")}]", size = 12) } }
        }
    }
    if (confirm) Confirm("Send this message?", "To: $contact\n\n\"$text\"", "Send", onYes = {
        vm.act("/api/whatsapp/send", JSONObject().put("contact", contact).put("text", text).put("route", if (newChat) "new" else "reply"), "Sent"); text = ""
    }, onNo = { confirm = false })
}

@Composable
fun MemoryPage(vm: DeskVM) {
    var t by remember { mutableStateOf("") }
    Page {
        H("Memory", "What Hukum remembers about you")
        Panel { Field(t, { t = it }, "Something to remember"); Spacer(Modifier.height(6.dp)); Btn("Remember", primary = true, enabled = t.isNotBlank()) { vm.act("/api/memory", JSONObject().put("text", t), "Remembered"); t = "" } }
        Load(vm, 0, { vm.arr("/api/memory") }) { m ->
            if (m.length() == 0) Mut("Nothing remembered yet.")
            m.list().forEach { x -> Panel { Row(verticalAlignment = Alignment.CenterVertically) { Chip(x.s("kind"), C.accent); Spacer(Modifier.padding(4.dp)); Tx(x.s("text"), Modifier.weight(1f), 14); Btn("Forget", danger = true) { vm.act("/api/memory/forget", JSONObject().put("id", x.optInt("id")), "Forgotten") } } } }
        }
    }
}

@Composable
fun AutomationPage(vm: DeskVM) {
    Page {
        H("Automation", "Workflows run through the same permission rules")
        Load(vm, 0, { vm.obj("/api/workflows") }) { w ->
            val items = w.arr("items")
            if (items.isEmpty()) Mut("No workflows yet - create them on the PC dashboard (templates available).")
            items.forEach { x ->
                val id = x.optInt("id")
                Panel {
                    Row(verticalAlignment = Alignment.CenterVertically) { Tx(x.s("name"), bold = true); Spacer(Modifier.padding(4.dp)); Chip(if (x.optInt("enabled") == 1) "on" else "paused", if (x.optInt("enabled") == 1) C.ok else C.warn) }
                    Mut(x.optJSONObject("spec")?.optJSONObject("trigger")?.toString() ?: "", size = 11)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 6.dp)) {
                        Btn("Run now") { vm.act("/api/workflows/action", JSONObject().put("id", id).put("action", "run"), "Started") }
                        Btn(if (x.optInt("enabled") == 1) "Pause" else "Resume") { vm.act("/api/workflows/action", JSONObject().put("id", id).put("action", if (x.optInt("enabled") == 1) "disable" else "enable"), "Updated") }
                    }
                }
            }
        }
    }
}

@Composable
fun SecurityPage(vm: DeskVM) {
    Page {
        H("Approvals & audit", "Critical actions can only be approved at the PC")
        Load(vm, 4000, { Pair(vm.obj("/api/approvals"), vm.arr("/api/audit")) }) { (a, audit) ->
            val pend = a.arr("pending")
            Panel(hot = true) {
                Title("Waiting for you")
                if (pend.isEmpty()) Mut("Nothing waiting.")
                pend.forEach { p ->
                    Column(Modifier.padding(bottom = 8.dp)) {
                        Row { Chip(p.s("risk"), sevColor(p.s("risk"))); Spacer(Modifier.padding(4.dp)); Tx(p.s("summary"), size = 14) }
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 4.dp)) {
                            if (p.s("risk") != "critical") Btn("Approve", primary = true) { vm.decide(p.optInt("id"), true) }
                            Btn("Reject", danger = true) { vm.decide(p.optInt("id"), false) }
                        }
                    }
                }
            }
            Panel {
                Title("Audit log")
                audit.list().take(30).forEach { x -> Mut("${x.s("actor")} · ${x.s("action")} · ${x.s("risk")} · ${x.s("decision")}", size = 12) }
            }
        }
    }
}
