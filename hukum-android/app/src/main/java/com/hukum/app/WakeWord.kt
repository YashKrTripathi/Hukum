package com.hukum.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/**
 * Listens (inside the foreground service) for the word "Hukum". Uses the phone's own speech recogniser in a restart
 * loop, preferring offline recognition. When the word is heard it opens the orb screen, over the lock screen if needed.
 * Pauses while the orb itself is using the microphone.
 */
class WakeWord(private val ctx: Context) {
    private val handler = Handler(Looper.getMainLooper())
    private var rec: SpeechRecognizer? = null
    @Volatile private var running = false

    fun start() { if (running) return; running = true; handler.post { loop() } }
    fun stop() { running = false; handler.post { destroy() } }

    private fun destroy() { try { rec?.cancel(); rec?.destroy() } catch (e: Exception) {}; rec = null }

    private fun again(ms: Long) { if (running) handler.postDelayed({ loop() }, ms) }

    private fun loop() {
        if (!running) return
        if (paused) { again(1200); return }
        if (ctx.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) { again(10_000); return }
        if (!SpeechRecognizer.isRecognitionAvailable(ctx)) { again(30_000); return }
        destroy()
        val r = SpeechRecognizer.createSpeechRecognizer(ctx)
        rec = r
        var fired = false
        fun check(list: List<String>?) {
            if (fired || list == null) return
            for (t in list) {
                val m = PATTERN.find(t) ?: continue
                fired = true
                val cmd = t.substring(m.range.last + 1).trim(' ', ',', '.', '!', '?')
                destroy()
                trigger(ctx, cmd)
                again(8_000)               // the orb takes the microphone; resume once it is gone
                return
            }
        }
        r.setRecognitionListener(object : RecognitionListener {
            override fun onPartialResults(b: Bundle?) { check(b?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)) }
            override fun onResults(b: Bundle?) { check(b?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)); if (!fired) again(250) }
            override fun onError(error: Int) {
                // no speech / no match are normal while idle: just listen again
                again(when (error) { SpeechRecognizer.ERROR_RECOGNIZER_BUSY, SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> 6_000L; SpeechRecognizer.ERROR_SPEECH_TIMEOUT, SpeechRecognizer.ERROR_NO_MATCH -> 200L; else -> 2_500L })
            }
            override fun onReadyForSpeech(p: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(v: Float) {}
            override fun onBufferReceived(b: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(t: Int, p: Bundle?) {}
        })
        r.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Prefs.lang(ctx))
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        })
    }

    companion object {
        /** Set by OrbActivity while it owns the microphone. */
        @Volatile var paused = false
        private val PATTERN = Regex("(?i)\\b(hukum|hukam|hookum|hukm|hukkum|hokum)\\b|हुकुम|हुकम")
        private const val CH = "hukum_wake"
        private const val ID = 7

        /**
         * Open the orb. A full-screen-intent notification is the one way Android lets a background app put an activity
         * on a locked or sleeping screen; when the phone is unlocked and in use it appears as a heads-up banner instead
         * (and we also try to start the activity directly, which works when the app is allowed to).
         */
        fun trigger(ctx: Context, cmd: String) {
            val app = ctx.applicationContext
            val i = Intent(app, OrbActivity::class.java).putExtra("cmd", cmd).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            val pi = PendingIntent.getActivity(app, 70, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val nm = app.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(CH, "Hukum wake word", NotificationManager.IMPORTANCE_HIGH).apply {
                setSound(null, null); enableVibration(false); lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            })
            nm.notify(ID, Notification.Builder(app, CH).setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("Hukum")
                .setContentText("Listening…").setCategory(Notification.CATEGORY_CALL).setAutoCancel(true).setTimeoutAfter(15_000)
                .setContentIntent(pi).setFullScreenIntent(pi, true).build())
            try { app.startActivity(i) } catch (e: Exception) { /* blocked from the background: the notification does the job */ }
        }

        fun clear(ctx: Context) { ctx.getSystemService(NotificationManager::class.java).cancel(ID) }
    }
}
