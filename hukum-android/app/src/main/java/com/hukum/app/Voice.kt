package com.hukum.app

import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale
import kotlin.coroutines.resume

/** Ears (speech recognition) and mouth (server neural voice, falling back to the phone's own TTS). */
class Voice(private val ctx: Context, private val api: Api) {
    var lastError: String? = null
    /** Live microphone loudness 0..1 (drives the orb). */
    @Volatile var level = 0f
    private var rec: SpeechRecognizer? = null
    private var player: MediaPlayer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false

    init {
        tts = TextToSpeech(ctx.applicationContext) { ttsReady = it == TextToSpeech.SUCCESS }
    }

    /** Listens for one utterance. Returns null on silence/error (see lastError for fatal ones). */
    suspend fun listen(lang: String, onPartial: (String) -> Unit): String? = withContext(Dispatchers.Main) {
        lastError = null
        if (!SpeechRecognizer.isRecognitionAvailable(ctx)) {
            lastError = "No speech recognition service on this phone (install Google app)"
            return@withContext null
        }
        suspendCancellableCoroutine { cont ->
            val r = SpeechRecognizer.createSpeechRecognizer(ctx)
            rec = r
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1600L)
            }
            var done = false
            fun finish(v: String?) {
                if (done) return
                done = true
                r.destroy()
                if (cont.isActive) cont.resume(v)
            }
            r.setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle?) {
                    finish(results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull())
                }
                override fun onPartialResults(partial: Bundle?) {
                    partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let(onPartial)
                }
                override fun onError(error: Int) {
                    if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS) lastError = "Microphone permission needed"
                    if (error == SpeechRecognizer.ERROR_NETWORK || error == SpeechRecognizer.ERROR_NETWORK_TIMEOUT)
                        lastError = "Speech recognition needs internet"
                    finish(null)
                }
                override fun onReadyForSpeech(params: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) { level = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f) }
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
            cont.invokeOnCancellation { try { r.destroy() } catch (e: Exception) {} }
            r.startListening(intent)
        }
    }

    suspend fun speak(text: String) {
        if (text.isBlank()) return
        if (Prefs.serverVoice(ctx)) {
            try {
                val bytes = withContext(Dispatchers.IO) { api.tts(text) }
                playMp3(bytes)
                return
            } catch (e: Exception) { /* fall back to the phone's voice */ }
        }
        speakLocal(text)
    }

    private suspend fun playMp3(bytes: ByteArray) = withContext(Dispatchers.Main) {
        val f = File(ctx.cacheDir, "hukum_voice.mp3").also { it.writeBytes(bytes) }
        suspendCancellableCoroutine<Unit> { cont ->
            val p = MediaPlayer()
            player = p
            p.setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            p.setDataSource(f.absolutePath)
            p.setOnCompletionListener { p.release(); if (cont.isActive) cont.resume(Unit) }
            p.setOnErrorListener { _, _, _ -> p.release(); if (cont.isActive) cont.resume(Unit); true }
            cont.invokeOnCancellation { try { p.stop(); p.release() } catch (e: Exception) {} }
            p.setOnPreparedListener { it.start() }
            p.prepareAsync()
        }
    }

    private suspend fun speakLocal(text: String) = withContext(Dispatchers.Main) {
        val t = tts ?: return@withContext
        if (!ttsReady) return@withContext
        val deva = text.any { it in 'ऀ'..'ॿ' }
        t.language = if (deva) Locale("hi", "IN") else Locale("en", "IN")
        suspendCancellableCoroutine<Unit> { cont ->
            t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) {}
                override fun onDone(utteranceId: String?) { if (cont.isActive) cont.resume(Unit) }
                @Deprecated("Deprecated in Java")
                override fun onError(utteranceId: String?) { if (cont.isActive) cont.resume(Unit) }
            })
            cont.invokeOnCancellation { t.stop() }
            t.speak(text, TextToSpeech.QUEUE_FLUSH, null, "hukum")
        }
    }

    fun stop() {
        try { rec?.destroy() } catch (e: Exception) {}
        try { player?.stop(); player?.release() } catch (e: Exception) {}
        tts?.stop()
    }

    fun shutdown() {
        stop()
        tts?.shutdown()
    }
}
