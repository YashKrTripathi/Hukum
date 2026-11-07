package com.hukum.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED && Prefs.configured(context)) {
            try { HukumService.start(context) } catch (e: Exception) {}
        }
    }
}
