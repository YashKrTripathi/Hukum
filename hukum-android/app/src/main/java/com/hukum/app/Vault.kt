package com.hukum.app

import android.content.Context
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlin.coroutines.resume

/**
 * Passwords Boss chooses to save for Hukum. Encrypted with a key that lives in the Android Keystore (it cannot be exported),
 * kept only on this phone: never sent to the gateway, the PC, an AI model, the history or the logs.
 * A saved password is only ever typed into an app after Boss confirms with fingerprint / screen lock (see [Auth]).
 */
object Vault {
    private const val ALIAS = "hukum_vault_key"
    private fun sp(c: Context) = c.getSharedPreferences("hukum_vault", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        g.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
        return g.generateKey()
    }

    fun put(c: Context, label: String, secret: String) {
        val ci = Cipher.getInstance("AES/GCM/NoPadding")
        ci.init(Cipher.ENCRYPT_MODE, key())
        val blob = ci.iv + ci.doFinal(secret.toByteArray(Charsets.UTF_8))
        sp(c).edit().putString(label.trim(), Base64.encodeToString(blob, Base64.NO_WRAP)).apply()
    }

    fun get(c: Context, label: String): String? {
        val v = sp(c).getString(label, null) ?: return null
        return try {
            val b = Base64.decode(v, Base64.NO_WRAP)
            val ci = Cipher.getInstance("AES/GCM/NoPadding")
            ci.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, b.copyOfRange(0, 12)))
            String(ci.doFinal(b, 12, b.size - 12), Charsets.UTF_8)
        } catch (e: Exception) { null }
    }

    fun labels(c: Context): List<String> = sp(c).all.keys.sortedBy { it.lowercase() }
    fun delete(c: Context, label: String) { sp(c).edit().remove(label).apply() }

    /** The saved label that matches any of the hints (an app name, words from the request). */
    fun find(c: Context, vararg hints: String): String? {
        val hs = hints.map { it.lowercase() }.filter { it.isNotBlank() }
        return labels(c).firstOrNull { l -> val ll = l.lowercase(); hs.any { h -> h.contains(ll) || (h.length >= 3 && ll.contains(h)) } }
    }
}

/** Asks Boss to confirm with fingerprint / face / screen lock, in the system's own dialog (it cannot be answered by Hukum). */
object Auth {
    suspend fun user(ctx: Context, title: String, text: String): Boolean = withContext(Dispatchers.Main) {
        if (Build.VERSION.SDK_INT < 28) return@withContext false
        suspendCancellableCoroutine { cont ->
            val exec = ctx.mainExecutor
            val b = BiometricPrompt.Builder(ctx).setTitle(title).setDescription(text)
            if (Build.VERSION.SDK_INT >= 30) b.setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL)
            else b.setNegativeButton("Cancel", exec) { _, _ -> }
            val sig = CancellationSignal()
            cont.invokeOnCancellation { sig.cancel() }
            try {
                b.build().authenticate(sig, exec, object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) { if (cont.isActive) cont.resume(true) }
                    override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) { if (cont.isActive) cont.resume(false) }
                })
            } catch (e: Exception) { if (cont.isActive) cont.resume(false) }
        }
    }
}
