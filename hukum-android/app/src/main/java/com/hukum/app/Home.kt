package com.hukum.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
private fun BigCard(title: String, sub: String, bg: Color, modifier: Modifier, big: Boolean = false, glyph: String, onClick: () -> Unit) {
    Column(modifier.clip(RoundedCornerShape(28.dp)).background(bg).clickable(onClick = onClick).padding(18.dp), verticalArrangement = Arrangement.SpaceBetween) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Box(Modifier.size(38.dp).clip(CircleShape).background(Color.Black.copy(alpha = 0.18f)), contentAlignment = Alignment.Center) { Text(glyph, fontSize = 18.sp) }
            Text("↗", color = C.onAccent, fontSize = 18.sp)
        }
        Column {
            Text(title, color = C.onAccent, fontSize = if (big) 30.sp else 16.sp, lineHeight = if (big) 32.sp else 18.sp)
            if (sub.isNotBlank()) Text(sub, color = C.onAccent.copy(alpha = 0.6f), fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
        }
    }
}

/** The landing screen: greeting, big tiles, a live status strip and a history of what Boss asked recently. */
@Composable
fun HomeScreen(desk: DeskVM, talk: () -> Unit, go: (String) -> Unit) {
    val h = desk.home
    val unread = h?.optJSONObject("notif")?.optJSONObject("counts")?.let { it.optInt("error") + it.optInt("warning") } ?: 0
    val pending = h?.arr("approvals")?.size ?: 0
    Page {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(42.dp).clip(CircleShape).background(C.card2).clickable { go("more") }, contentAlignment = Alignment.Center) { Text("☰", color = C.tx, fontSize = 18.sp) }
            Spacer(Modifier.weight(1f))
            Text("Hi, Boss 👋", color = C.mut, fontSize = 13.sp)
            Spacer(Modifier.weight(1f))
            Box(Modifier.size(42.dp).clip(CircleShape).background(C.card2).clickable { go("alerts") }, contentAlignment = Alignment.Center) { Text(if (unread > 0) "🔔$unread" else "🔔", color = C.tx, fontSize = 15.sp) }
        }
        Text("How may I help\nyou today?", color = C.tx, fontSize = 32.sp, lineHeight = 38.sp, modifier = Modifier.padding(top = 6.dp, bottom = 4.dp))
        Row(Modifier.fillMaxWidth().height(250.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            BigCard("Talk\nwith Hukum", if (HukumService.wakeActive) "say “Hukum” anytime" else "voice mode", C.accent, Modifier.weight(1f).fillMaxWidth().height(250.dp), big = true, glyph = "🎙", onClick = talk)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                BigCard("PC Control", h?.let { "CPU ${it.optDouble("cpu").toInt()}% · RAM ${it.optDouble("ram").toInt()}%" } ?: "connecting…", C.accent2, Modifier.fillMaxWidth().weight(1f), glyph = "🖥") { go("pc") }
                BigCard("AI Agents", h?.arr("agents")?.count { it.s("status") == "running" }?.let { "$it running" } ?: "", C.pink, Modifier.fillMaxWidth().weight(1f), glyph = "🤖") { go("agents") }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Tile("Tasks", "${h?.arr("tasks")?.size ?: 0} open", "✅", Modifier.weight(1f)) { go("tasks") }
            Tile("Approvals", if (pending > 0) "$pending waiting" else "all clear", "🛡", Modifier.weight(1f)) { go("more") }
        }
        if (desk.error != null) Panel { Text("⚠ ${desk.error}", color = C.warn, fontSize = 13.sp) }
        Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("History", color = C.tx, fontSize = 16.sp); Spacer(Modifier.weight(1f)); Text(if (desk.history.isEmpty()) "" else "tap to run again", color = C.mut, fontSize = 11.sp)
        }
        if (desk.history.isEmpty()) Mut("Commands you give Hukum on the PC will show up here.")
        val tones = listOf(C.accent, C.accent2, C.pink)
        desk.history.take(6).forEachIndexed { i, q ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(C.card).clickable { desk.ask(q); go("pc") }.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(34.dp).clip(CircleShape).background(tones[i % 3]), contentAlignment = Alignment.Center) { Text("↺", color = C.onAccent, fontSize = 14.sp) }
                Spacer(Modifier.size(12.dp))
                Text(q, color = C.tx, fontSize = 14.sp, maxLines = 1, modifier = Modifier.weight(1f))
            }
        }
        Spacer(Modifier.height(80.dp))
    }
}

@Composable
private fun Tile(title: String, sub: String, glyph: String, modifier: Modifier, onClick: () -> Unit) {
    Row(modifier.clip(RoundedCornerShape(24.dp)).background(C.card).clickable(onClick = onClick).padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(38.dp).clip(CircleShape).background(C.card2), contentAlignment = Alignment.Center) { Text(glyph, fontSize = 17.sp) }
        Spacer(Modifier.size(10.dp))
        Column { Text(title, color = C.tx, fontSize = 14.sp); Text(sub, color = C.mut, fontSize = 11.sp) }
    }
}
