package com.hukum.app

import android.Manifest
import android.app.Application
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class Msg(val mine: Boolean, val text: String)

class ConvVM(app: Application) : AndroidViewModel(app) {
    private val api = Api(app)
    val voice = Voice(app, api)
    val messages = mutableStateListOf<Msg>()
    var status by mutableStateOf("Tap the orb to talk")
    var active by mutableStateOf(false)
    var lang by mutableStateOf(Prefs.lang(app))
    private var job: Job? = null

    fun toggleLang() {
        lang = if (lang == "hi-IN") "en-IN" else "hi-IN"
        Prefs.setLang(getApplication(), lang)
    }

    /** `first` = hidden opening message (e.g. __open__ or __ring__:reason) so Hukum speaks first. */
    fun start(first: String? = null, showFirst: Boolean = false) {
        if (job?.isActive == true) return
        active = true
        // One question, one answer, then stop. Only Hukum's own openings (ring / open) carry on as a conversation.
        val oneShot = first?.startsWith("__") != true
        job = viewModelScope.launch {
            try {
                if (first != null) turn(first, show = showFirst)
                var silent = 0; var acc = ""
                val overMode = Prefs.overMode(getApplication())
                while (active && !(oneShot && first != null)) {
                    status = "listening…"
                    val heard = voice.listen(lang) { status = "🎙 " + (acc + " " + it.replace(Voice.OVER, "")).trim() }
                    if (voice.lastError != null) { messages.add(Msg(false, "⚠️ ${voice.lastError}")); break }
                    if (heard.isNullOrBlank()) {
                        // silence: a command collected so far is complete
                        if (acc.isNotBlank()) { val q = acc; acc = ""; turn(q, show = true); if (oneShot) break; continue }
                        if (++silent >= (if (oneShot) 2 else 4)) break else continue
                    }
                    val over = Voice.OVER.containsMatchIn(heard)
                    acc = (acc + " " + heard.replace(Voice.OVER, "")).trim()
                    // "over" ends the command at once; without over-mode the first pause ends it as well
                    if (over || !overMode) {
                        val q = acc; acc = ""
                        if (q.isNotBlank()) turn(q, show = true)
                        if (oneShot || over) { if (oneShot) break }
                    }
                }
            } catch (e: Exception) {
                if (e !is kotlinx.coroutines.CancellationException) messages.add(Msg(false, "⚠️ ${e.message}"))
            } finally {
                active = false
                status = "Tap the orb to talk"
            }
        }
    }

    /** Asks the Hukum Desktop command center. Returns its answer, or null when the PC is unreachable or had no plan for it. */
    private suspend fun pcChat(text: String): String? = withContext(Dispatchers.IO) {
        try {
            val id = org.json.JSONObject(api.desktop("POST", "/api/m/chat", org.json.JSONObject().put("text", text))).optString("id")
            repeat(75) {
                kotlinx.coroutines.delay(800)
                val r = org.json.JSONObject(api.desktop("GET", "/api/m/chat_result?id=$id"))
                if (r.optBoolean("done")) return@withContext if (r.optString("via") in listOf("none", "error")) null else r.optString("reply")
            }
            null
        } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) { null }
    }

    private suspend fun turn(text: String, show: Boolean) {
        if (show) messages.add(Msg(true, text))
        status = "thinking…"
        // Phone-side requests (call, flashlight, alarm, volume, apps ...) are done right here, not on the PC.
        val local = try { PhoneActions.handle(getApplication(), text) } catch (e: Exception) { "Phone action failed: ${e.message}" }
        if (local == PhoneActions.AGENT) {
            val app = getApplication<Application>()
            val answer = if (!HukumAccess.enabled(app)) "To use apps for you, turn on Hukum in Accessibility: More > Voice & wake word > Open Accessibility settings."
            else try { status = "working…"; PhoneAgent.run(app, api, text) { status = "working: $it" } }
            catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) { "I could not finish that: ${e.message}" }
            messages.add(Msg(false, answer)); status = "speaking… (tap to interrupt)"
            val sj1 = viewModelScope.launch { voice.speak(answer) }
            speakJob = sj1; sj1.join(); return
        }
        if (local != null) {
            messages.add(Msg(false, local))
            status = "speaking… (tap to interrupt)"
            val sj0 = viewModelScope.launch { voice.speak(local) }
            speakJob = sj0
            sj0.join()
            return
        }
        // PC first: its command center can open/read/drive apps (e.g. read Claude's reply). Hukum's own openings ("__...") and
        // anything the PC does not understand go to the general chat brain.
        val pc = if (text.startsWith("__")) null else pcChat(text)
        val r = try {
            if (pc != null) Api.Reply(pc, pc.replace(Regex("[*_`#]"), "").take(350))
            else withContext(Dispatchers.IO) { api.chat(text) }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            messages.add(Msg(false, "⚠️ ${e.message}"))
            active = false
            return
        }
        messages.add(Msg(false, r.text))
        val app = getApplication<Application>()
        r.actions.forEach { try { CallAssistant.apply(app, it, foreground = true) } catch (e: Exception) {} }
        if (r.actions.any { it.optString("type") == "call_mode" && it.optString("mode") != "normal" } && !CallAssistant.hasPerms(app))
            messages.add(Msg(false, "⚠️ I need call permissions to answer for you: open ⚙ → 5. Call assistant"))
        status = "speaking… (tap to interrupt)"
        val sj = viewModelScope.launch { voice.speak(r.speech) }
        speakJob = sj
        sj.join()
    }

    private var speakJob: Job? = null

    /** Barge-in: cut Hukum off mid-sentence and go straight back to listening. */
    fun interrupt() { speakJob?.cancel() }

    fun stop() {
        active = false
        job?.cancel()
        voice.stop()
    }

    fun type(text: String) {
        if (job?.isActive == true) stop()
        job = viewModelScope.launch {
            try { turn(text, true) } finally { status = "Tap the orb to talk" }
        }
    }

    override fun onCleared() {
        voice.shutdown()
    }
}

class MainActivity : ComponentActivity() {
    private var pendingRing by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pendingRing = intent.getStringExtra("ring_reason")
        val old = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            try { getSharedPreferences("hukum", MODE_PRIVATE).edit().putString("crash", e.stackTraceToString().take(900)).commit() } catch (x: Exception) {}
            old?.uncaughtException(t, e)
        }
        Prefs.migrateWakeOff(this)
        if (Prefs.configured(this)) try { HukumService.start(this, mic = Prefs.wake(this)) } catch (e: Exception) {}
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = C.accent, background = C.bg, surface = C.panel, onSurface = C.tx,
                onBackground = C.tx, secondary = C.accent2, outline = C.line, surfaceVariant = C.card, onSurfaceVariant = C.mut)) {
                Shell(pendingRing) { pendingRing = null }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        pendingRing = intent.getStringExtra("ring_reason")
    }
}

@Composable
fun Screen(ringReason: String?, consumeRing: () -> Unit, showSetup: Boolean, setShowSetup: (Boolean) -> Unit) {
    val ctx = LocalContext.current
    val vm: ConvVM = viewModel()
    val listState = rememberLazyListState()

    val micPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) vm.start() else vm.messages.add(Msg(false, "⚠️ Microphone permission is needed to talk"))
    }
    val notifPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}

    fun hasMic() = ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33) notifPerm.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
    LaunchedEffect(ringReason) {
        if (ringReason != null && Prefs.configured(ctx)) {
            consumeRing()
            if (hasMic()) vm.start("__ring__:$ringReason") else micPerm.launch(Manifest.permission.RECORD_AUDIO)
        }
    }
    LaunchedEffect(vm.messages.size) {
        if (vm.messages.isNotEmpty()) listState.animateScrollToItem(vm.messages.size - 1)
    }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween) {
            Text("Talk to Hukum", color = C.tx, fontSize = 20.sp)
            Row {
                TextButton(onClick = { vm.toggleLang() }) { Text(if (vm.lang == "hi-IN") "हिं / Hinglish" else "English") }
                TextButton(onClick = { setShowSetup(true) }) { Text("⚙") }
            }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth().padding(vertical = 8.dp), state = listState,
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(vm.messages) { m ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = if (m.mine) Arrangement.End else Arrangement.Start) {
                    Box(Modifier.widthIn(max = 320.dp).clip(RoundedCornerShape(16.dp))
                        .background(if (m.mine) Color(0xFF1B3550) else C.card).padding(12.dp)) {
                        Text(m.text, color = C.tx, fontSize = 16.sp)
                    }
                }
            }
        }
        Text(vm.status, color = C.mut, modifier = Modifier.fillMaxWidth().padding(4.dp),
            fontSize = 14.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        Box(Modifier.fillMaxWidth().height(150.dp).clickable {
            when {
                vm.active && vm.status.startsWith("speaking") -> vm.interrupt()
                vm.active -> vm.stop()
                !Prefs.configured(ctx) -> setShowSetup(true)
                hasMic() -> vm.start()
                else -> micPerm.launch(Manifest.permission.RECORD_AUDIO)
            }
        }, contentAlignment = Alignment.Center) {
            Orb(150.dp, active = vm.active)
            Text(if (vm.active) "■" else "🎙", fontSize = 30.sp, color = Color.White)
        }
        Spacer(Modifier.height(8.dp))
        TypeBar { vm.type(it) }
    }

    if (showSetup) SetupDialog(vm) { setShowSetup(false) }
}

@Composable
fun TypeBar(onSend: (String) -> Unit) {
    var t by remember { mutableStateOf("") }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(t, { t = it }, Modifier.weight(1f), placeholder = { Text("…or type here") }, singleLine = true)
        TextButton(onClick = { if (t.isNotBlank()) { onSend(t.trim()); t = "" } }) { Text("Send") }
    }
}

@Composable
fun SetupDialog(vm: ConvVM, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var link by remember { mutableStateOf(Prefs.server(ctx)) }
    var key by remember { mutableStateOf(Prefs.key(ctx)) }
    var serverVoice by remember { mutableStateOf(Prefs.serverVoice(ctx)) }
    var result by remember { mutableStateOf("") }

    fun open(i: Intent) { try { ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } catch (e: Exception) { result = "Couldn't open that screen" } }
    fun screener(): Boolean = try {
        val rm = ctx.getSystemService(android.app.role.RoleManager::class.java)
        rm.isRoleHeld(android.app.role.RoleManager.ROLE_CALL_SCREENING)
    } catch (e: Exception) { false }
    val roleLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        result = if (CallAssistant.hasPerms(ctx) && screener()) "✅ Call assistant ready" else "Call assistant still needs setup"
    }
    val permsLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        val rm = ctx.getSystemService(android.app.role.RoleManager::class.java)
        if (rm.isRoleAvailable(android.app.role.RoleManager.ROLE_CALL_SCREENING) && !screener())
            roleLauncher.launch(rm.createRequestRoleIntent(android.app.role.RoleManager.ROLE_CALL_SCREENING))
        else result = if (CallAssistant.hasPerms(ctx)) "✅ Call assistant ready" else "Some call permissions were denied"
    }
    fun save() {
        val (server, k) = Prefs.parseLink(link)
        Prefs.save(ctx, server, k ?: key)
        link = server; key = k ?: key
    }

    AlertDialog(
        onDismissRequest = onClose,
        confirmButton = { TextButton(onClick = { save(); if (Prefs.configured(ctx)) HukumService.start(ctx, mic = true); onClose() }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Close") } },
        title = { Text("Connect to your Hukum server") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Paste the link the bot gives you (/talk). It contains the address and the key.", fontSize = 13.sp)
                OutlinedTextField(link, { link = it }, label = { Text("Server link") }, singleLine = true)
                OutlinedTextField(key, { key = it }, label = { Text("Key") }, singleLine = true)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Switch(serverVoice, { serverVoice = it; Prefs.setServerVoice(ctx, it) })
                    Text("  Natural server voice", fontSize = 14.sp)
                }
                OutlinedButton(onClick = {
                    save(); result = "Testing…"
                    scope.launch { result = if (withContext(Dispatchers.IO) { Api(ctx).ping() }) "✅ Connected" else "❌ Can't reach server or wrong key" }
                }) { Text("Test connection") }
                if (result.isNotBlank()) Text(result, fontSize = 14.sp)
                Text("Permissions Hukum needs to act like Jarvis:", fontSize = 13.sp)
                OutlinedButton(onClick = { open(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)) }) { Text("1. Usage access (see distracting apps)") }
                OutlinedButton(onClick = {
                    if (Build.VERSION.SDK_INT >= 34) open(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:${ctx.packageName}")))
                    else result = "Not needed on this Android version"
                }) { Text("2. Allow full-screen call screen") }
                OutlinedButton(onClick = {
                    open(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${ctx.packageName}")))
                }) { Text("3. Battery: don't restrict Hukum") }
                OutlinedButton(onClick = {
                    open(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName))
                }) { Text("4. Notification settings") }
                OutlinedButton(onClick = { permsLauncher.launch(CallAssistant.permissionList()) }) {
                    Text("5. Call assistant (reject + SMS while busy)")
                }
                OutlinedButton(onClick = {
                    open(NotifListener.settingsIntent())
                    result = "Turn ON 'Hukum message reader' (it reads WhatsApp/Discord/SMS notifications)"
                }) { Text(if (NotifListener.enabled(ctx)) "6. Message reader ✅ on" else "6. Message reader (WhatsApp/Discord/SMS)") }
            }
        }
    )
}
