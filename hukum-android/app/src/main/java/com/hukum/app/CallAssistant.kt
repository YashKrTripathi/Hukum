package com.hukum.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.ContactsContract
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Phone abilities the brain can use: answer calls while Boss is unavailable, log callers, call back. */
object CallAssistant {
    data class Call(val number: String, val name: String, val time: Long, val answered: Boolean)

    private fun sp(c: Context) = c.getSharedPreferences("callassistant", Context.MODE_PRIVATE)

    fun mode(c: Context): String = sp(c).getString("mode", "normal") ?: "normal"
    fun since(c: Context): Long = sp(c).getLong("since", 0)
    fun greetingText(c: Context): String = sp(c).getString("greeting", "") ?: ""
    fun greetingFile(c: Context) = File(c.filesDir, "greeting.mp3")

    private val perms = listOf(
        Manifest.permission.ANSWER_PHONE_CALLS, Manifest.permission.READ_PHONE_STATE,
        Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_CONTACTS, Manifest.permission.CALL_PHONE,
        Manifest.permission.SEND_SMS
    )
    fun permissionList(): Array<String> = perms.toTypedArray()
    fun hasPerms(c: Context) = perms.all { c.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }

    fun setMode(c: Context, mode: String, greeting: String) {
        sp(c).edit().putString("mode", mode).putString("greeting", greeting)
            .putLong("since", System.currentTimeMillis()).apply()
    }

    @Synchronized
    fun addCall(c: Context, call: Call) {
        val arr = JSONArray(sp(c).getString("calls", "[]"))
        arr.put(JSONObject().put("number", call.number).put("name", call.name)
            .put("time", call.time).put("answered", call.answered))
        sp(c).edit().putString("calls", arr.toString()).apply()
    }

    @Synchronized
    fun takeCalls(c: Context): List<Call> {
        val arr = JSONArray(sp(c).getString("calls", "[]"))
        sp(c).edit().putString("calls", "[]").apply()
        return (0 until arr.length()).map {
            val o = arr.getJSONObject(it)
            Call(o.getString("number"), o.optString("name"), o.getLong("time"), o.optBoolean("answered"))
        }
    }

    /** Texts the caller once per hour that Boss is unavailable. Returns true if an SMS was sent. */
    @Suppress("DEPRECATION")
    fun textBack(c: Context, number: String): Boolean {
        if (number.length < 5 || c.checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) return false
        val last = sp(c).getLong("sms_$number", 0)
        if (System.currentTimeMillis() - last < 60 * 60_000) return false
        val text = greetingText(c).ifBlank { "Hello, this is Hukum, Boss's assistant. Boss is unavailable right now and will call you back." }
        return try {
            val sm = if (android.os.Build.VERSION.SDK_INT >= 31) c.getSystemService(android.telephony.SmsManager::class.java)
                     else android.telephony.SmsManager.getDefault()
            sm.sendMultipartTextMessage(number, null, sm.divideMessage(text), null, null)
            sp(c).edit().putLong("sms_$number", System.currentTimeMillis()).apply()
            true
        } catch (e: Exception) { false }
    }

    fun contactName(c: Context, number: String): String? {
        if (number.isBlank() || c.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) return null
        return try {
            val uri = Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(number))
            c.contentResolver.query(uri, arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME), null, null, null)?.use {
                if (it.moveToFirst()) it.getString(0) else null
            }
        } catch (e: Exception) { null }
    }

    /** Applies a command sent by the brain. foreground=false means the app has no screen open. */
    fun apply(c: Context, a: JSONObject, foreground: Boolean) {
        when (a.optString("type")) {
            "call_mode" -> setMode(c, a.optString("mode", "normal"), a.optString("greeting", ""))
            "dial" -> dial(c, a.optString("target"), foreground)
            "reply" -> if (!NotifReplier.reply(c, a.optString("nkey"), a.optString("app"), a.optString("sender"), a.optString("text")))
                info(c, "Couldn't reply to ${a.optString("sender")}", "Their chat notification is gone. Open the chat to reply.")
        }
    }

    fun info(c: Context, title: String, text: String) {
        val nm = c.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("hukum_info", "Hukum messages", NotificationManager.IMPORTANCE_HIGH))
        nm.notify((System.currentTimeMillis() % 100000).toInt() + 100, android.app.Notification.Builder(c, "hukum_info")
            .setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title).setContentText(text)
            .setStyle(android.app.Notification.BigTextStyle().bigText(text)).setAutoCancel(true).build())
    }

    private fun numberFor(c: Context, target: String): String? {
        if (Regex("^[+0-9 ()-]{5,}$").matches(target.trim())) return target.filter { it.isDigit() || it == '+' }
        if (c.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) return null
        return try {
            c.contentResolver.query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                arrayOf(ContactsContract.CommonDataKinds.Phone.NUMBER),
                "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?", arrayOf("%${target.trim()}%"),
                "${ContactsContract.CommonDataKinds.Phone.TIMES_CONTACTED} DESC"
            )?.use { if (it.moveToFirst()) it.getString(0) else null }
        } catch (e: Exception) { null }
    }

    private fun dial(c: Context, target: String, foreground: Boolean) {
        val number = numberFor(c, target) ?: return
        val uri = Uri.parse("tel:" + Uri.encode(number))
        val canCall = c.checkSelfPermission(Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED
        val intent = Intent(if (canCall) Intent.ACTION_CALL else Intent.ACTION_DIAL, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (foreground) { c.startActivity(intent); return }
        // no screen open: Android blocks background call launches, so offer a tap-to-call notification
        val nm = c.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("hukum_info", "Hukum messages", NotificationManager.IMPORTANCE_HIGH))
        val pi = PendingIntent.getActivity(c, 3, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(4, android.app.Notification.Builder(c, "hukum_info").setSmallIcon(android.R.drawable.sym_action_call)
            .setContentTitle("Call $target").setContentText("Tap to call").setContentIntent(pi).setAutoCancel(true).build())
    }
}
