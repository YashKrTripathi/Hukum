package com.hukum.app

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.lifecycle.viewmodel.compose.viewModel

/** The orb that appears after "Hukum" is heard: shown over the lock screen, wakes the display, talks, then closes itself. */
class OrbActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        WakeWord.paused = true
        WakeWord.clear(this)
        val cmd = intent.getStringExtra("cmd")?.replace(Voice.OVER, "")?.trim()?.takeIf { it.isNotBlank() }
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = C.accent, background = C.bg, surface = C.panel, onSurface = C.tx, onBackground = C.tx)) {
                val vm: ConvVM = viewModel()
                VoiceOrbScreen(vm, first = cmd, showFirst = cmd != null, autoStart = true, autoClose = true) { vm.stop(); finish() }
            }
        }
    }

    override fun onDestroy() {
        WakeWord.paused = false
        super.onDestroy()
    }
}
