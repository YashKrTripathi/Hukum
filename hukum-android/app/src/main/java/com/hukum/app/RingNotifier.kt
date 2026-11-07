package com.hukum.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator

/** Makes the phone ring like an incoming call: full-screen call screen + ringtone on the alarm stream. */
object RingNotifier {
    private const val CH = "hukum_calls"
    private const val NOTIF_ID = 2
    private var player: MediaPlayer? = null
    private val handler = Handler(Looper.getMainLooper())
    private var autoStop: Runnable? = null

    fun ring(ctx: Context, reason: String) {
        val app = ctx.applicationContext
        val nm = app.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH, "Hukum calls", NotificationManager.IMPORTANCE_HIGH).apply {
            setSound(null, null)            // we play the ringtone ourselves (alarm stream)
            enableVibration(false)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        })
        val call = Intent(app, CallActivity::class.java)
            .putExtra("reason", reason)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pi = PendingIntent.getActivity(app, 0, call, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = Notification.Builder(app, CH)
            .setSmallIcon(android.R.drawable.sym_call_incoming)
            .setContentTitle("Hukum is calling")
            .setContentText(reason)
            .setCategory(Notification.CATEGORY_CALL)
            .setOngoing(true)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .setFullScreenIntent(pi, true)
            .build()
        nm.notify(NOTIF_ID, n)
        startSound(app)
    }

    private fun startSound(ctx: Context) {
        stopSound(ctx)
        try {
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            player = MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)      // rings even in silent/vibrate mode
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                setDataSource(ctx, uri)
                isLooping = true
                prepare()
                start()
            }
        } catch (e: Exception) { /* no ringtone available: vibration still happens */ }
        val v = ctx.getSystemService(Vibrator::class.java)
        v?.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 800, 600), 0))
        autoStop = Runnable { stop(ctx) }.also { handler.postDelayed(it, 45_000) }
    }

    private fun stopSound(ctx: Context) {
        autoStop?.let { handler.removeCallbacks(it) }
        try { player?.stop(); player?.release() } catch (e: Exception) {}
        player = null
        ctx.getSystemService(Vibrator::class.java)?.cancel()
    }

    fun stop(ctx: Context) {
        stopSound(ctx)
        ctx.getSystemService(NotificationManager::class.java).cancel(NOTIF_ID)
    }
}
