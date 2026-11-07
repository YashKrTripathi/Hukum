package com.hukum.app

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Switch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

/** Settings for the "Hukum" wake word (always-on listener that opens the orb, even on the lock screen). */
@Composable
fun VoicePage() {
    val ctx = LocalContext.current
    var on by remember { mutableStateOf(Prefs.wake(ctx)) }
    var note by remember { mutableStateOf("") }
    fun open(i: Intent) { try { ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } catch (e: Exception) { note = "Open this in the phone settings: ${e.message}" } }
    fun apply(v: Boolean) {
        on = v; Prefs.setWake(ctx, v)
        try { HukumService.start(ctx, mic = v) } catch (e: Exception) { note = "Could not start the listener: ${e.message}" }
        if (v) note = "Listening for Hukum. If it stops after a while, set battery to Unrestricted for Hukum."
    }
    val perm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) apply(true) else { on = false; note = "Microphone permission is needed for the wake word" }
    }
    Page {
        H("Voice & wake word", "Say Hukum and the orb appears, even on the lock screen")
        Panel(hot = on) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(on, { v ->
                    if (v && ctx.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED)
                        perm.launch(android.Manifest.permission.RECORD_AUDIO) else apply(v)
                })
                Spacer(Modifier.size(10.dp)); Tx("Always listen for Hukum")
            }
            Spacer(Modifier.height(8.dp))
            Row { Chip(if (HukumService.wakeActive) "listening now" else if (on) "armed - open Hukum once to start" else "off", if (HukumService.wakeActive) C.ok else C.mut) }
            if (note.isNotBlank()) Mut(note, Modifier.padding(top = 8.dp))
        }
        Panel {
            Title("How it works")
            Mut("• A small always-on listener uses the phone's speech recogniser (offline when the language pack is installed).")
            Mut("• Say Hukum, or Hukum open VS Code on my PC: the orb opens over the lock screen and the display turns on.")
            Mut("• It cannot unlock the phone; everything it does goes through Hukum on your PC.")
            Mut("• After a reboot or if Android restarts the app, open Hukum once to start listening again.")
            Mut("• While you are using the phone, some versions show a banner instead of the full screen.")
            Mut("• Needs: microphone, notifications, full-screen notifications, battery set to Unrestricted.")
        }
        Panel {
            Title("Allow these on the phone")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Btn("Battery") { open(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + ctx.packageName))) }
                if (android.os.Build.VERSION.SDK_INT >= 34) Btn("Full-screen") { open(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:" + ctx.packageName))) }
                Btn("Notifications") { open(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)) }
            }
        }
    }
}
