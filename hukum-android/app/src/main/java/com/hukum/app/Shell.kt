package com.hukum.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.delay

@Composable
fun Shell(ringReason: String?, consumeRing: () -> Unit) {
    val ctx = LocalContext.current
    val desk: DeskVM = viewModel()
    val conv: ConvVM = viewModel()
    var tab by remember { mutableStateOf("home") }
    var voice by remember { mutableStateOf(ringReason != null) }
    var showSetup by remember { mutableStateOf(!Prefs.configured(ctx)) }
    var confirmStop by remember { mutableStateOf(false) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle

    // Poll the PC only while the app is on screen.
    LaunchedEffect(Unit) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) { desk.refreshHome(); delay(5000) }
        }
    }
    // Ask once for what the wake word needs, then (re)start the listener from the foreground.
    val perms = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestMultiplePermissions()) {
        if (Prefs.configured(ctx) && Prefs.wake(ctx)) try { HukumService.start(ctx, mic = true) } catch (e: Exception) {}
    }
    LaunchedEffect(Unit) {
        val need = listOf(android.Manifest.permission.RECORD_AUDIO, android.Manifest.permission.POST_NOTIFICATIONS,
            android.Manifest.permission.READ_CONTACTS, android.Manifest.permission.CALL_PHONE)
            .filter { ctx.checkSelfPermission(it) != android.content.pm.PackageManager.PERMISSION_GRANTED }
        if (need.isNotEmpty() && Prefs.configured(ctx) && Prefs.wake(ctx)) perms.launch(need.toTypedArray())
    }
    LaunchedEffect(desk.toast) { if (desk.toast != null) { delay(3200); desk.toast = null } }
    LaunchedEffect(ringReason) { if (ringReason != null) voice = true }

    val h = desk.home
    val stopped = h?.optJSONObject("estop")?.optBoolean("on") == true
    val pending = h?.arr("approvals") ?: emptyList()

    HudBackground {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(9.dp).clip(CircleShape).background(if (desk.error != null) C.err else if (h == null) C.warn else C.accent))
                Spacer(Modifier.size(8.dp))
                Text("HUKUM", color = C.tx, fontSize = 15.sp, letterSpacing = 4.sp)
                Spacer(Modifier.weight(1f))
                Text(if (stopped) "RELEASE STOP" else "STOP", color = Color.White, fontSize = 11.sp, letterSpacing = 1.sp,
                    modifier = Modifier.clip(RoundedCornerShape(50)).background(if (stopped) C.warn else C.err.copy(alpha = 0.9f))
                        .clickable { if (stopped) desk.estop(false) else confirmStop = true }.padding(horizontal = 14.dp, vertical = 7.dp))
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (tab) {
                    "home" -> HomeScreen(desk, talk = { voice = true }) { tab = it }
                    "pc" -> PcScreen(desk) { tab = it }
                    "agents" -> AgentsScreen(desk)
                    "tasks" -> TasksScreen(desk)
                    "alerts" -> AlertsScreen(desk)
                    else -> MoreScreen(desk) { showSetup = true }
                }
                desk.toast?.let {
                    Text(it, color = C.tx, fontSize = 14.sp, modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 96.dp).clip(RoundedCornerShape(50))
                        .background(C.card2).padding(horizontal = 18.dp, vertical = 10.dp))
                }
                // floating pill navigation
                Row(Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 14.dp).clip(RoundedCornerShape(50)).background(Color(0xFF121212))
                    .border(1.dp, C.line, RoundedCornerShape(50)).padding(6.dp), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    listOf("home" to "⌂", "pc" to "🖥", "agents" to "🤖", "tasks" to "✓", "more" to "☰").forEach { (k, g) ->
                        val sel = tab == k || (k == "more" && tab == "alerts")
                        Box(Modifier.clip(RoundedCornerShape(50)).background(if (sel) C.accent else Color.Transparent).clickable { tab = k }
                            .padding(horizontal = 18.dp, vertical = 10.dp), contentAlignment = Alignment.Center) {
                            Text(g, fontSize = 18.sp, color = if (sel) C.onAccent else C.mut)
                        }
                    }
                }
            }
        }
    }

    if (voice) VoiceOrbScreen(conv, first = ringReason?.let { "__ring__:$it" }, autoStart = ringReason != null) { voice = false; consumeRing() }
    if (showSetup) SetupDialog(conv) { showSetup = false }

    // Anything waiting for Boss's approval shows up on every tab.
    pending.firstOrNull()?.let { p ->
        val critical = p.s("risk") == "critical"
        AlertDialog(onDismissRequest = {}, containerColor = C.panel, titleContentColor = C.tx, textContentColor = C.tx,
            title = { Text("Hukum needs your approval") },
            text = { Column { Chip(p.s("risk"), sevColor(p.s("risk"))); Spacer(Modifier.size(8.dp)); Text(p.s("summary")); if (critical) Mut("Critical: approve this at the PC.", Modifier.padding(top = 8.dp)) } },
            confirmButton = { if (!critical) TextButton(onClick = { desk.decide(p.optInt("id"), true) }) { Text("Approve", color = C.accent) } },
            dismissButton = { TextButton(onClick = { desk.decide(p.optInt("id"), false) }) { Text("Reject", color = C.err) } })
    }
    if (confirmStop) Confirm("Emergency stop?", "Everything on the PC pauses: agents are cancelled, monitoring stops, pending approvals are rejected.", "STOP", true,
        { desk.estop(true) }, { confirmStop = false })
}
