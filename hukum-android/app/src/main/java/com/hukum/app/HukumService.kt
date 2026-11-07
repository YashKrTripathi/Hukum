package com.hukum.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Always-on guard: waits for ring events from the server and reports phone usage. */
class HukumService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("hukum_guard", "Hukum is on guard", NotificationManager.IMPORTANCE_MIN))
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, "hukum_guard")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Hukum is on guard")
            .setContentText("Waiting for your study calls")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        if (!started) {
            started = true
            val api = Api(this)
            scope.launch { listenForRings(api) }
            scope.launch { reportUsage(api) }
            androidx.core.content.ContextCompat.registerReceiver(this, unlockReceiver,
                android.content.IntentFilter(Intent.ACTION_USER_PRESENT), androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)
        }
        return START_STICKY
    }

    private val unlockReceiver = object : android.content.BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) { scope.launch { onUnlock() } }
    }

    /** Boss unlocked the phone after a call mode: tell him, out loud, who called while he was away. */
    private suspend fun onUnlock() {
        if (CallAssistant.mode(this) == "normal" || !Prefs.configured(this)) return
        if (System.currentTimeMillis() - CallAssistant.since(this) < 10 * 60_000) return   // not woken up yet
        val calls = CallAssistant.takeCalls(this)
        CallAssistant.setMode(this, "normal", "")
        val fmt = java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault())
        val arr = org.json.JSONArray()
        calls.forEach {
            arr.put(org.json.JSONObject().put("who", it.name.ifBlank { it.number.ifBlank { "unknown number" } })
                .put("number", it.number).put("time", fmt.format(java.util.Date(it.time))).put("answered_by_hukum", it.answered))
        }
        try {
            val api = Api(this)
            val r = api.chat("__wake__:$arr")
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel("hukum_info", "Hukum messages", NotificationManager.IMPORTANCE_HIGH))
            nm.notify(5, Notification.Builder(this, "hukum_info").setSmallIcon(android.R.drawable.sym_call_missed)
                .setContentTitle("Hukum").setContentText(r.text).setStyle(Notification.BigTextStyle().bigText(r.text))
                .setContentIntent(PendingIntent.getActivity(this, 6, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
                .setAutoCancel(true).build())
            Voice(this, api).speak(r.speech)
        } catch (e: Exception) { /* server unreachable: calls stay logged in the notification-less state */ }
    }

    private suspend fun onNudge(api: Api, o: org.json.JSONObject) {
        val text = o.optString("text")
        if (text.isBlank()) return
        CallAssistant.info(this, "Hukum", text)
        val pm = getSystemService(android.os.PowerManager::class.java)
        if (pm.isInteractive) try { Voice(this, api).speak(o.optString("speech", text)) } catch (x: Exception) {}
    }

    private suspend fun listenForRings(api: Api) {
        var last = -1
        while (scope.isActive) {
            if (!Prefs.configured(this)) { delay(10_000); continue }
            try {
                val (newLast, events) = api.events(last)
                last = newLast
                for (e in events) when (e.type) {
                    "ring" -> RingNotifier.ring(this, e.text.ifBlank { "Study time" })
                    // a reminder from the brain (unanswered message, missed call...)
                    "nudge" -> try { onNudge(api, org.json.JSONObject(e.text)) } catch (x: Exception) {}
                    // a command from the brain (e.g. answer calls while sleeping, call someone back)
                    "action" -> try { CallAssistant.apply(this, org.json.JSONObject(e.text), foreground = false) } catch (x: Exception) {}
                }
            } catch (e: Exception) {
                delay(5_000)       // server unreachable: retry
            }
        }
    }

    private suspend fun reportUsage(api: Api) {
        while (scope.isActive) {
            if (Prefs.configured(this)) {
                try { UsageWatcher.sample(this)?.let { api.phoneState(it.state, it.app) } } catch (e: Exception) {}
            }
            delay(60_000)
        }
    }

    override fun onDestroy() {
        try { unregisterReceiver(unlockReceiver) } catch (e: Exception) {}
        started = false
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        @Volatile private var started = false
        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, HukumService::class.java))
        }
    }
}
