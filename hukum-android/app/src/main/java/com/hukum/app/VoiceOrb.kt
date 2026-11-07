package com.hukum.app

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.animateFloatAsState
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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

/**
 * Full-screen voice mode: the glass orb, what Hukum is hearing / saying, a big mic button. Used inside the app and by
 * OrbActivity (the screen that appears over the lock screen after the wake word).
 */
@Composable
fun VoiceOrbScreen(vm: ConvVM, first: String? = null, showFirst: Boolean = false, autoStart: Boolean = false, autoClose: Boolean = false, onClose: () -> Unit) {
    val ctx = LocalContext.current
    var typing by remember { mutableStateOf(false) }
    var wasActive by remember { mutableStateOf(false) }
    fun hasMic() = ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    val micPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) vm.start(first, showFirst) else vm.messages.add(Msg(false, "Microphone permission is needed to talk"))
    }
    LaunchedEffect(Unit) {
        if (autoStart && Prefs.configured(ctx)) { if (hasMic()) vm.start(first, showFirst) else micPerm.launch(Manifest.permission.RECORD_AUDIO) }
    }
    LaunchedEffect(vm.active) {
        if (vm.active) wasActive = true
        else if (wasActive && autoClose) { delay(3500); if (!vm.active) onClose() }
    }

    val st = vm.status
    // The orb follows the real microphone loudness while you speak, and pulses while Hukum answers.
    var live0 by remember { mutableStateOf(0.12f) }
    LaunchedEffect(Unit) {
        var t = 0f; var sm = 0f
        while (true) {
            delay(45); t += 0.045f
            val s = vm.status
            val target = when {
                s.startsWith("speaking") -> 0.55f + 0.35f * Math.abs(Math.sin(t * 3.2)).toFloat()
                s.startsWith("🎙") || s.startsWith("listening") -> { sm += (vm.voice.level - sm) * 0.45f; 0.15f + 0.85f * sm }
                s.startsWith("thinking") -> 0.35f + 0.1f * Math.sin(t * 2.0).toFloat()
                else -> { sm = 0f; 0.12f }
            }
            live0 += (target - live0) * 0.35f
        }
    }
    val energy = live0
    val live = if (st.startsWith("🎙")) st.removePrefix("🎙").trim() else ""
    val lastHukum = vm.messages.lastOrNull { !it.mine }?.text
    val lastMine = vm.messages.lastOrNull { it.mine }?.text

    Box(Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color.Black)) {
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 22.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height(14.dp))
            Text("Hukum", color = C.onAccent, fontSize = 13.sp, modifier = Modifier.clip(RoundedCornerShape(50)).background(C.accent).padding(horizontal = 18.dp, vertical = 6.dp))
            Text(if (vm.active) "● listening" else "● online", color = C.mut, fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp))
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) { Blob(330.dp, energy) }
            // what is being said: the live words are bright, the last answer is dimmer above them
            Column(Modifier.fillMaxWidth().height(150.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                val main = when { live.isNotBlank() -> live; st.startsWith("thinking") -> (lastMine ?: ""); else -> lastHukum ?: lastMine ?: "Tap the mic, or just say “Hukum”" }
                Text(main.take(220), color = C.tx, fontSize = 20.sp, textAlign = TextAlign.Center, maxLines = 5)
                Text(when { st.startsWith("🎙") -> ""; else -> st }, color = C.mut, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp))
            }
            if (typing) {
                var t by remember { mutableStateOf("") }
                Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(t, { t = it }, Modifier.weight(1f), placeholder = { Text("Type to Hukum", color = C.mut) }, singleLine = true)
                    Text("Send", color = C.accent, modifier = Modifier.clickable { if (t.isNotBlank()) { vm.type(t.trim()); t = ""; typing = false } }.padding(12.dp))
                }
            }
            Row(Modifier.fillMaxWidth().padding(bottom = 22.dp, top = 6.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(52.dp).clip(CircleShape).background(C.accent2.copy(alpha = 0.85f)).clickable { typing = !typing }, contentAlignment = Alignment.Center) { Text("⌨", fontSize = 20.sp, color = C.onAccent) }
                Box(Modifier.size(92.dp).clip(CircleShape).border(2.dp, C.accent.copy(alpha = 0.35f), CircleShape).padding(8.dp).clip(CircleShape).background(C.accent)
                    .clickable {
                        when {
                            vm.active && vm.status.startsWith("speaking") -> vm.interrupt()
                            vm.active -> vm.stop()
                            !Prefs.configured(ctx) -> vm.messages.add(Msg(false, "Connect first: More > Connection"))
                            hasMic() -> vm.start()
                            else -> micPerm.launch(Manifest.permission.RECORD_AUDIO)
                        }
                    }, contentAlignment = Alignment.Center) { Text(if (vm.active) "■" else "🎙", fontSize = 32.sp, color = C.onAccent) }
                Box(Modifier.size(52.dp).clip(CircleShape).background(C.card2).clickable { vm.stop(); onClose() }, contentAlignment = Alignment.Center) { Text("✕", fontSize = 18.sp, color = C.tx) }
            }
        }
    }
}
