package com.hukum.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.telecom.Call
import android.telecom.CallScreeningService
import android.telecom.TelecomManager
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * While Boss has set a call mode (sleeping/busy/driving): silence the ring, pick up, play the greeting
 * through the speakerphone so the caller hears it, hang up, and remember who called.
 * Android does not let apps talk into or record a normal phone call, so the greeting is played out loud
 * and picked up by the mic. The caller's own words are not recorded.
 */
class HukumScreeningService : CallScreeningService() {
    override fun onScreenCall(details: Call.Details) {
        val mode = CallAssistant.mode(this)
        if (details.callDirection != Call.Details.DIRECTION_INCOMING || mode == "normal") {
            respondToCall(details, CallResponse.Builder().build())
            return
        }
        val number = details.handle?.schemeSpecificPart ?: ""
        val name = CallAssistant.contactName(this, number) ?: ""
        // silent reject: no ring, no speaker. The caller gets an SMS instead; Boss gets a summary on unlock.
        respondToCall(details, CallResponse.Builder().setDisallowCall(true).setRejectCall(true)
            .setSkipNotification(true).build())
        val sms = CallAssistant.textBack(this, number)
        CallAssistant.addCall(this, CallAssistant.Call(number, name, System.currentTimeMillis(), sms))
    }
}

/** Plays the greeting into the call (speakerphone, call-volume stream). */
object CallVoice {
    private const val FALLBACK = "नमस्ते, मैं हुकुम बोल रहा हूँ, बॉस का असिस्टेंट। बॉस अभी उपलब्ध नहीं हैं। वो आपको कॉल बैक करेंगे। धन्यवाद।"

    @Suppress("DEPRECATION")
    fun play(ctx: Context): Boolean {
        val am = ctx.getSystemService(AudioManager::class.java)
        try {
            am.isSpeakerphoneOn = true
            am.isMicrophoneMute = false
            am.setStreamVolume(AudioManager.STREAM_MUSIC, am.getStreamMaxVolume(AudioManager.STREAM_MUSIC), 0)
            am.setStreamVolume(AudioManager.STREAM_VOICE_CALL, (am.getStreamMaxVolume(AudioManager.STREAM_VOICE_CALL) * 0.7).toInt(), 0)
            val f = CallAssistant.greetingFile(ctx)
            return if (f.exists() && f.length() > 1000) playFile(f.absolutePath) else speak(ctx, CallAssistant.greetingText(ctx).ifBlank { FALLBACK })
        } finally {
            am.isSpeakerphoneOn = false
        }
    }

    private fun playFile(path: String): Boolean {
        val latch = CountDownLatch(1)
        val p = MediaPlayer()
        return try {
            p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            p.setDataSource(path)
            p.setOnCompletionListener { latch.countDown() }
            p.setOnErrorListener { _, _, _ -> latch.countDown(); true }
            p.prepare()
            p.start()
            latch.await(30, TimeUnit.SECONDS)
            true
        } catch (e: Exception) { false } finally { try { p.release() } catch (e: Exception) {} }
    }

    private fun speak(ctx: Context, text: String): Boolean {
        val latch = CountDownLatch(1)
        var ok = false
        var tts: TextToSpeech? = null
        tts = TextToSpeech(ctx.applicationContext) { status ->
            val t = tts
            if (status == TextToSpeech.SUCCESS && t != null) {
                t.language = Locale("hi", "IN")
                t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) { ok = true }
                    override fun onDone(utteranceId: String?) { latch.countDown() }
                    @Deprecated("Deprecated in Java")
                    override fun onError(utteranceId: String?) { latch.countDown() }
                })
                val b = Bundle().apply { putInt(TextToSpeech.Engine.KEY_PARAM_STREAM, AudioManager.STREAM_VOICE_CALL) }
                t.speak(text, TextToSpeech.QUEUE_FLUSH, b, "greeting")
            } else latch.countDown()
        }
        latch.await(30, TimeUnit.SECONDS)
        try { tts?.shutdown() } catch (e: Exception) {}
        return ok
    }
}
