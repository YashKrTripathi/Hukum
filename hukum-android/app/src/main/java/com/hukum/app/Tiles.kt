package com.hukum.app

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/** Quick Settings tile: tap to open the Hukum orb (no wake word needed). */
class OrbTile : TileService() {
    override fun onStartListening() { qsTile?.apply { state = Tile.STATE_INACTIVE; label = "Hukum"; updateTile() } }

    override fun onClick() {
        val i = Intent(this, OrbActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        if (Build.VERSION.SDK_INT >= 34) startActivityAndCollapse(PendingIntent.getActivity(this, 71, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        else @Suppress("DEPRECATION") startActivityAndCollapse(i)
    }
}

/** Quick Settings tile: switch the always-listening "Hukum" microphone on or off in one tap. Lit = microphone is on. */
class MicTile : TileService() {
    private fun refresh() {
        val t = qsTile ?: return
        val on = Prefs.wake(this) && HukumService.wakeActive
        t.state = if (on) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        t.label = if (on) "Hukum mic ON" else "Hukum mic off"
        t.updateTile()
    }

    override fun onStartListening() = refresh()

    override fun onClick() {
        val on = !(Prefs.wake(this) && HukumService.wakeActive)
        Prefs.setWake(this, on)
        try { HukumService.start(this, mic = on) } catch (e: Exception) { WakeWord.state = "could not start: ${e.message}" }
        refresh()
    }
}
