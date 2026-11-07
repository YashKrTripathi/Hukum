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
                vmRef = vm
                VoiceOrbScreen(vm, first = cmd, showFirst = cmd != null, autoStart = true, autoClose = true) { vm.stop(); finish() }
            }
        }
    }

    private var vmRef: ConvVM? = null

    /**
     * Leaving the orb (Home, screen off, another app opened by a command) ends it so the wake listener is never left paused.
     * If Hukum is still answering, let the answer finish first; if it is listening, stop the microphone right away.
     */
    override fun onStop() {
        WakeWord.paused = false
        if (!isChangingConfigurations) {
            val h = android.os.Handler(android.os.Looper.getMainLooper())
            fun check(n: Int) {
                if (isFinishing || isDestroyed) return
                val v = vmRef
                val busy = v != null && (v.status.startsWith("speaking") || v.status.startsWith("thinking"))
                if (!busy || n > 60) { try { v?.stop() } catch (e: Exception) {}; finish() } else h.postDelayed({ check(n + 1) }, 500)
            }
            val v = vmRef
            if (v != null && (v.status.startsWith("listening") || v.status.startsWith("🎙"))) v.stop()      // mic off at once
            check(0)
        }
        super.onStop()
    }

    override fun onDestroy() {
        WakeWord.paused = false
        super.onDestroy()
    }
}
