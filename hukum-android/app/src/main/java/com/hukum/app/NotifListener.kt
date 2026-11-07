package com.hukum.app

import android.app.Notification
import android.app.RemoteInput
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * Hukum's eyes on your messages: reads WhatsApp / Discord / SMS notifications (never the chats themselves),
 * sends them to the brain, and remembers each notification's Reply action so Hukum can answer when you approve.
 */
class NotifListener : NotificationListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val app = APPS[sbn.packageName] ?: return
        if (!Prefs.configured(this)) return
        val n = sbn.notification
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        if (n.flags and Notification.FLAG_ONGOING_EVENT != 0) return
        val ex = n.extras
        val title = ex.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim().orEmpty()
        var text = ex.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim().orEmpty()
        var sender = title
        val isGroup = ex.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION)

        // newest message of a messaging-style notification
        try {
            val msgs = ex.getParcelableArray(Notification.EXTRA_MESSAGES)
            if (msgs != null && msgs.isNotEmpty()) {
                val last = Notification.MessagingStyle.Message.getMessagesFromBundleArray(msgs).lastOrNull()
                if (last != null) {
                    text = last.text?.toString()?.trim().orEmpty().ifBlank { text }
                    val who = last.senderPerson?.name?.toString()
                    if (!who.isNullOrBlank() && isGroup) sender = "$who ($title)"
                }
            }
        } catch (e: Exception) { /* fall back to title/text */ }
        if (text.isBlank() || title.isBlank()) return
        if (sender.equals("You", true) || title.equals("You", true)) return
        if (NOISE.any { it.containsMatchIn(text) } || NOISE.any { it.containsMatchIn(title) }) return

        val key = sbn.key
        val sig = "$key|$text"
        synchronized(seen) {
            if (seen[sig]?.let { System.currentTimeMillis() - it < 120_000 } == true) return
            seen[sig] = System.currentTimeMillis()
            if (seen.size > 300) seen.keys.take(100).forEach { seen.remove(it) }
        }

        val reply = n.actions?.firstOrNull { a -> a.remoteInputs?.isNotEmpty() == true }
        if (reply != null) NotifReplier.remember(key, app, sender, reply)

        val type = if (app == "whatsapp" && Regex("(?i)missed (voice|video) call").containsMatchIn(text)) "call" else app
        val o = JSONObject().put("app", type).put("sender", sender).put("chat", title)
            .put("text", redact(text)).put("ts", sbn.postTime).put("key", key).put("can_reply", reply != null)
        send(o)
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification, rankingMap: RankingMap, reason: Int) {
        if (APPS[sbn.packageName] == null || !Prefs.configured(this)) return
        // swiped away by the user (2 = cancel, 3 = cancel all) stays unread; opened/cleared by the app = read
        val r = if (reason == REASON_CANCEL || reason == REASON_CANCEL_ALL) "swiped" else "read"
        send(JSONObject().put("removed", sbn.key).put("reason", r))
    }

    private fun send(o: JSONObject) {
        scope.launch {
            val api = Api(this@NotifListener)
            val q = Outbox.take(this@NotifListener)
            q.put(o)
            try {
                api.inbox(q)
            } catch (e: Exception) {      // server unreachable: keep everything for the next message
                for (i in 0 until q.length()) Outbox.put(this@NotifListener, q.getJSONObject(i))
            }
        }
    }

    companion object {
        val APPS = mapOf(
            "com.whatsapp" to "whatsapp", "com.whatsapp.w4b" to "whatsapp_business",
            "com.discord" to "discord",
            "com.google.android.apps.messaging" to "sms", "com.samsung.android.messaging" to "sms",
            "com.android.mms" to "sms", "com.android.messaging" to "sms"
        )
        private val NOISE = listOf(
            Regex("(?i)^\\d+ new messages?$"), Regex("(?i)checking for new messages"),
            Regex("(?i)backup in progress"), Regex("(?i)whatsapp web"), Regex("(?i)^\\d+ messages? from \\d+ chats?$")
        )
        private val seen = LinkedHashMap<String, Long>()
        private val SENSITIVE = Regex("(?i)\\b(otp|one[- ]time|verification|passcode|password|cvv|pin)\\b")

        /** Never ship codes/PINs to the server. */
        fun redact(t: String) = if (SENSITIVE.containsMatchIn(t)) t.replace(Regex("\\d{4,8}"), "••••") else t

        fun enabled(c: Context): Boolean =
            androidx.core.app.NotificationManagerCompat.getEnabledListenerPackages(c).contains(c.packageName)

        fun settingsIntent() = Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        fun rebind(c: Context) {
            try { requestRebind(ComponentName(c, NotifListener::class.java)) } catch (e: Exception) {}
        }
    }
}

/** Remembers the Reply action of recent chat notifications so Hukum can answer through them. */
object NotifReplier {
    private class P(val action: Notification.Action, val app: String, val who: String)
    private val byKey = LinkedHashMap<String, P>()

    @Synchronized
    fun remember(key: String, app: String, who: String, action: Notification.Action) {
        byKey.remove(key)
        byKey[key] = P(action, app, who)
        if (byKey.size > 60) byKey.keys.take(20).forEach { byKey.remove(it) }
    }

    @Synchronized
    fun reply(ctx: Context, nkey: String, app: String, sender: String, text: String): Boolean {
        val p = byKey[nkey]
            ?: byKey.values.lastOrNull { it.app == app && it.who.contains(sender, true) }
            ?: return false
        val inputs = p.action.remoteInputs ?: return false
        return try {
            val intent = Intent()
            val b = Bundle()
            inputs.forEach { b.putCharSequence(it.resultKey, text) }
            RemoteInput.addResultsToIntent(inputs, intent, b)
            p.action.actionIntent.send(ctx, 0, intent)
            true
        } catch (e: Exception) { false }
    }
}

/** Messages that could not be sent while the server was unreachable. */
object Outbox {
    private fun sp(c: Context) = c.getSharedPreferences("outbox", Context.MODE_PRIVATE)

    @Synchronized
    fun put(c: Context, o: JSONObject) {
        val a = JSONArray(sp(c).getString("q", "[]"))
        a.put(o)
        val keep = JSONArray()
        for (i in maxOf(0, a.length() - 200) until a.length()) keep.put(a.get(i))
        sp(c).edit().putString("q", keep.toString()).apply()
    }

    /** Takes the whole queue (to be sent together with the new message). */
    @Synchronized
    fun take(c: Context): JSONArray {
        val a = JSONArray(sp(c).getString("q", "[]"))
        sp(c).edit().putString("q", "[]").apply()
        return a
    }
}
