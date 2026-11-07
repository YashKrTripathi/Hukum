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
                vmStop = { vm.stop() }
                VoiceOrbScreen(vm, first = cmd, showFirst = cmd != null, autoStart = true, autoClose = true) { vm.stop(); finish() }
            }
        }
    }

    /** Leaving the orb (Home, screen off, another app) ends it, so the wake listener is never left paused. */
    override fun onStop() {
        WakeWord.paused = false
        if (!isChangingConfigurations) { try { vmStop() } catch (e: Exception) {}; finish() }
        super.onStop()
    }

    private var vmStop: () -> Unit = {}

    override fun onDestroy() {
        WakeWord.paused = false
        super.onDestroy()
    }
}
