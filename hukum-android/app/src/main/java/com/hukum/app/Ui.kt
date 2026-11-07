package com.hukum.app

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONArray
import org.json.JSONObject

object C {
    val bg = Color(0xFF080A0F); val panel = Color(0xFF0E121A); val card = Color(0xFF141A24); val card2 = Color(0xFF1B2431)
    val line = Color(0xFF232D3D); val accent = Color(0xFF36B9FF); val accent2 = Color(0xFF786BFF)
    val ok = Color(0xFF25D695); val warn = Color(0xFFFFB547); val err = Color(0xFFFF5263)
    val tx = Color(0xFFF4F7FC); val mut = Color(0xFF9BA9BC)
}

fun sevColor(s: String) = when (s) { "error", "failed", "critical" -> C.err; "warning", "high", "queued" -> C.warn; "done", "ok", "running", "info" -> C.ok; else -> C.mut }

/** Background with a faint cyan glow at the top, like a HUD. */
@Composable
fun HudBackground(content: @Composable () -> Unit) {
    Box(Modifier.fillMaxSize().background(C.bg)) {
        Box(Modifier.fillMaxWidth().height(320.dp).background(Brush.verticalGradient(listOf(C.accent.copy(alpha = 0.10f), Color.Transparent))))
        content()
    }
}

/** The Hukum core: rotating arcs and a breathing centre. level 0..1 makes it react (listening/speaking). */
@Composable
fun Orb(size: androidx.compose.ui.unit.Dp, active: Boolean, alert: Boolean = false, modifier: Modifier = Modifier) {
    val t = rememberInfiniteTransition(label = "orb")
    val spin by t.animateFloat(0f, 360f, infiniteRepeatable(tween(if (active) 6000 else 16000, easing = LinearEasing)), label = "spin")
    val spin2 by t.animateFloat(360f, 0f, infiniteRepeatable(tween(if (active) 9000 else 24000, easing = LinearEasing)), label = "spin2")
    val pulse by t.animateFloat(0.85f, 1f, infiniteRepeatable(tween(if (active) 700 else 2200), RepeatMode.Reverse), label = "pulse")
    val main = if (alert) C.err else if (active) C.ok else C.accent
    Canvas(modifier.height(size).fillMaxWidth()) {
        val c = Offset(this.size.width / 2, this.size.height / 2)
        val r = this.size.height / 2
        drawCircle(Brush.radialGradient(listOf(main.copy(alpha = 0.55f * pulse), main.copy(alpha = 0.10f), Color.Transparent), c, r * 0.95f), r * 0.95f, c)
        drawCircle(main.copy(alpha = 0.9f), r * 0.20f * pulse, c)
        drawCircle(Color.White.copy(alpha = 0.85f), r * 0.07f, c)
        val st = Stroke(width = r * 0.045f, cap = StrokeCap.Round)
        rotate(spin, c) { drawArc(main, 0f, 100f, false, c - Offset(r * 0.62f, r * 0.62f), Size(r * 1.24f, r * 1.24f), style = st); drawArc(main.copy(alpha = 0.4f), 180f, 60f, false, c - Offset(r * 0.62f, r * 0.62f), Size(r * 1.24f, r * 1.24f), style = st) }
        rotate(spin2, c) { drawArc(C.accent2, 40f, 70f, false, c - Offset(r * 0.8f, r * 0.8f), Size(r * 1.6f, r * 1.6f), style = st); drawArc(C.accent2.copy(alpha = 0.35f), 200f, 110f, false, c - Offset(r * 0.8f, r * 0.8f), Size(r * 1.6f, r * 1.6f), style = Stroke(width = r * 0.02f)) }
        drawCircle(main.copy(alpha = 0.25f), r * 0.98f, c, style = Stroke(width = 1.5f))
    }
}

@Composable
fun Panel(modifier: Modifier = Modifier, hot: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(C.card)
        .border(1.dp, if (hot) C.accent.copy(alpha = 0.5f) else C.line, RoundedCornerShape(16.dp)).padding(14.dp), content = content)
}

@Composable fun Title(t: String, modifier: Modifier = Modifier) = Text(t.uppercase(), color = C.mut, fontSize = 11.sp, letterSpacing = 1.4.sp, modifier = modifier.padding(bottom = 6.dp))
@Composable fun Mut(t: String, modifier: Modifier = Modifier, size: Int = 13) = Text(t, color = C.mut, fontSize = size.sp, modifier = modifier)
@Composable fun Tx(t: String, modifier: Modifier = Modifier, size: Int = 15, bold: Boolean = false) =
    Text(t, color = C.tx, fontSize = size.sp, fontWeight = if (bold) androidx.compose.ui.text.font.FontWeight.SemiBold else null, modifier = modifier)

@Composable
fun Chip(t: String, color: Color = C.mut) {
    Text(t, color = color, fontSize = 11.sp, modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(color.copy(alpha = 0.16f)).padding(horizontal = 7.dp, vertical = 2.dp))
}

@Composable
fun Meter(label: String, value: Double?, modifier: Modifier = Modifier) {
    val v = (value ?: 0.0).coerceIn(0.0, 100.0)
    val col = if (v > 90) C.err else if (v > 75) C.warn else C.accent
    Panel(modifier) {
        Mut(label)
        Text("${v.toInt()}%", color = C.tx, fontSize = 24.sp)
        Box(Modifier.fillMaxWidth().height(5.dp).clip(RoundedCornerShape(3.dp)).background(C.card2)) {
            Box(Modifier.fillMaxWidth((v / 100).toFloat()).height(5.dp).background(Brush.horizontalGradient(listOf(col, C.accent2))))
        }
    }
}

@Composable
fun Row2(a: @Composable (Modifier) -> Unit, b: @Composable (Modifier) -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) { a(Modifier.weight(1f)); b(Modifier.weight(1f)) }
}

@Composable
fun Btn(t: String, modifier: Modifier = Modifier, danger: Boolean = false, primary: Boolean = false, enabled: Boolean = true, onClick: () -> Unit) {
    val bg = when { !enabled -> C.card2.copy(alpha = 0.5f); primary -> C.accent; danger -> C.err.copy(alpha = 0.15f); else -> C.card2 }
    val fg = when { primary -> Color(0xFF04101A); danger -> C.err; else -> C.tx }
    Text(t, color = if (enabled) fg else C.mut, fontSize = 13.sp, modifier = modifier.clip(RoundedCornerShape(10.dp)).background(bg)
        .border(1.dp, if (danger) C.err.copy(alpha = 0.4f) else C.line, RoundedCornerShape(10.dp))
        .then(if (enabled) Modifier.clickable(onClick = onClick) else Modifier).padding(horizontal = 12.dp, vertical = 8.dp))
}

// ---- JSON helpers
fun JSONArray?.list(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONObject.s(k: String, d: String = ""): String = if (isNull(k)) d else optString(k, d)
fun JSONObject.arr(k: String): List<JSONObject> = optJSONArray(k).list()
fun JSONArray?.strings(): List<String> = if (this == null) emptyList() else (0 until length()).map { optString(it) }

fun ago(ts: Double): String {
    if (ts <= 0) return "never"
    val s = (System.currentTimeMillis() / 1000.0 - ts).coerceAtLeast(0.0)
    return when { s < 60 -> "${s.toInt()}s ago"; s < 3600 -> "${(s / 60).toInt()}m ago"; s < 86400 -> "${(s / 3600).toInt()}h ago"; else -> "${(s / 86400).toInt()}d ago" }
}
