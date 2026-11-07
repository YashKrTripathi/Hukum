package com.hukum.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
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
    var tab by remember { mutableStateOf(if (ringReason != null || !Prefs.configured(ctx)) "voice" else "pc") }
    var showSetup by remember { mutableStateOf(!Prefs.configured(ctx)) }
    var confirmStop by remember { mutableStateOf(false) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle

    // Poll the PC only while the app is on screen.
    LaunchedEffect(Unit) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) { desk.refreshHome(); delay(5000) }
        }
    }
    LaunchedEffect(desk.toast) { if (desk.toast != null) { delay(3200); desk.toast = null } }

    val h = desk.home
    val stopped = h?.optJSONObject("estop")?.optBoolean("on") == true
    val pending = h?.arr("approvals") ?: emptyList()
    val unread = h?.optJSONObject("notif")?.optJSONObject("counts")?.let { it.optInt("error") + it.optInt("warning") } ?: 0

    HudBackground {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            // top bar
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(9.dp).clip(CircleShape).background(if (desk.error != null) C.err else if (h == null) C.warn else C.ok))
                Spacer(Modifier.size(8.dp))
                Text("HUKUM", color = C.accent, fontSize = 18.sp, letterSpacing = 3.sp)
                Spacer(Modifier.weight(1f))
                Text(if (stopped) "STOPPED · RELEASE" else "EMERGENCY STOP", color = Color_white(), fontSize = 12.sp,
                    modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(if (stopped) C.warn.copy(alpha = 0.9f) else C.err)
                        .clickable { if (stopped) desk.estop(false) else confirmStop = true }.padding(horizontal = 12.dp, vertical = 8.dp))
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (tab) {
                    "voice" -> Screen(ringReason, consumeRing, showSetup) { showSetup = it }
                    "pc" -> PcScreen(desk) { tab = it }
                    "agents" -> AgentsScreen(desk)
                    "tasks" -> TasksScreen(desk)
                    "alerts" -> AlertsScreen(desk)
                    else -> MoreScreen(desk) { showSetup = true; tab = "voice" }
                }
                desk.toast?.let {
                    Text(it, color = C.tx, fontSize = 14.sp, modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 12.dp).clip(RoundedCornerShape(12.dp))
                        .background(C.card2).padding(horizontal = 16.dp, vertical = 10.dp))
                }
            }
            NavigationBar(containerColor = C.panel, modifier = Modifier.navigationBarsPadding()) {
                listOf("voice" to ("🎙" to "Hukum"), "pc" to ("🖥" to "PC"), "agents" to ("🤖" to "Agents"), "tasks" to ("✅" to "Tasks"),
                    "alerts" to ("🔔" to "Alerts"), "more" to ("☰" to "More")).forEach { (k, v) ->
                    NavigationBarItem(selected = tab == k, onClick = { tab = k },
                        icon = { Text(if (k == "alerts" && unread > 0) "${v.first}$unread" else v.first, fontSize = 18.sp) },
                        label = { Text(v.second, fontSize = 10.sp) },
                        colors = NavigationBarItemDefaults.colors(selectedTextColor = C.accent, unselectedTextColor = C.mut, indicatorColor = C.card2))
                }
            }
        }
    }

    // Anything waiting for Boss's approval shows up on every tab.
    pending.firstOrNull()?.let { p ->
        val critical = p.s("risk") == "critical"
        AlertDialog(onDismissRequest = {}, containerColor = C.panel, titleContentColor = C.tx, textContentColor = C.tx,
            title = { Text("Hukum needs your approval") },
            text = { Column { Chip(p.s("risk"), sevColor(p.s("risk"))); Spacer(Modifier.size(8.dp)); Text(p.s("summary")); if (critical) Mut("Critical: approve this at the PC.", Modifier.padding(top = 8.dp)) } },
            confirmButton = { if (!critical) TextButton(onClick = { desk.decide(p.optInt("id"), true) }) { Text("Approve", color = C.ok) } },
            dismissButton = { TextButton(onClick = { desk.decide(p.optInt("id"), false) }) { Text("Reject", color = C.err) } })
    }
    if (confirmStop) Confirm("Emergency stop?", "Everything on the PC pauses: agents are cancelled, monitoring stops, pending approvals are rejected.", "STOP", true,
        { desk.estop(true) }, { confirmStop = false })
}

private fun Color_white() = androidx.compose.ui.graphics.Color.White
