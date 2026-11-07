package com.hukum.app

import android.content.Context
import android.net.Uri

object Prefs {
    private fun sp(c: Context) = c.getSharedPreferences("hukum", Context.MODE_PRIVATE)

    fun server(c: Context): String = sp(c).getString("server", "") ?: ""
    fun key(c: Context): String = sp(c).getString("key", "") ?: ""
    fun lang(c: Context): String = sp(c).getString("lang", "hi-IN") ?: "hi-IN"
    fun serverVoice(c: Context): Boolean = sp(c).getBoolean("server_voice", true)

    fun wake(c: Context): Boolean = sp(c).getBoolean("wake", false)
    fun setWake(c: Context, on: Boolean) = sp(c).edit().putBoolean("wake", on).apply()
    fun history(c: Context): List<String> = (sp(c).getString("history", "") ?: "").split("\n").filter { it.isNotBlank() }
    fun setHistory(c: Context, items: List<String>) = sp(c).edit().putString("history", items.take(20).joinToString("\n")).apply()

    fun save(c: Context, server: String, key: String) {
        sp(c).edit().putString("server", server.trim().trimEnd('/')).putString("key", key.trim()).apply()
    }

    fun setLang(c: Context, lang: String) = sp(c).edit().putString("lang", lang).apply()
    fun setServerVoice(c: Context, on: Boolean) = sp(c).edit().putBoolean("server_voice", on).apply()

    /** Accepts a pasted link like https://host/?k=KEY&talk=1 or just https://host. Returns (server, key?). */
    fun parseLink(raw: String): Pair<String, String?> {
        val s = raw.trim()
        val u = Uri.parse(s)
        val base = if (u.scheme != null && u.authority != null) "${u.scheme}://${u.authority}" else s.trimEnd('/')
        return base to u.getQueryParameter("k")
    }

    fun configured(c: Context) = server(c).isNotBlank() && key(c).isNotBlank()
}
