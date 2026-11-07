package com.hukum.app

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Taps WhatsApp's Send button, but only for about 90 seconds (so there is time to unlock the phone or the app with a fingerprint/PIN) right after Hukum itself opened a chat with Boss's message
 * filled in. It reads nothing else and does nothing otherwise. Boss turns it on once in Android's accessibility settings.
 */
class HukumAccess : AccessibilityService() {
    override fun onAccessibilityEvent(e: AccessibilityEvent?) {
        val pkg = e?.packageName?.toString() ?: return
        if (!pkg.startsWith("com.whatsapp") || System.currentTimeMillis() > until) return
        val root = rootInActiveWindow ?: return
        // WhatsApp sometimes drops the pre-filled text (app lock, fingerprint screen): type it into the message box ourselves
        val want = text
        if (!want.isNullOrBlank()) {
            val entry = root.findAccessibilityNodeInfosByViewId("$pkg:id/entry").firstOrNull()
            if (entry != null && entry.isEditable) {
                val cur = if (entry.isShowingHintText) "" else entry.text?.toString().orEmpty()
                if (cur.isBlank()) {
                    entry.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, android.os.Bundle().apply {
                        putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, want) })
                    return          // the Send button appears once there is text; the next event taps it
                }
            }
        }
        val btn = root.findAccessibilityNodeInfosByViewId("$pkg:id/send").firstOrNull() ?: byDescription(root)
        if (btn != null && btn.isEnabled) {
            var n: AccessibilityNodeInfo? = btn
            while (n != null && !n.isClickable) n = n.parent
            if (n?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true) {
                until = 0L; text = null
                android.os.Handler(android.os.Looper.getMainLooper()).post { android.widget.Toast.makeText(applicationContext, "Hukum: message sent", android.widget.Toast.LENGTH_SHORT).show() }
            }
        }
    }

    private fun byDescription(n: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val d = n.contentDescription?.toString()?.trim()?.lowercase()
        if (d == "send" || d == "भेजें" || d == "भेजो") return n
        for (i in 0 until n.childCount) n.getChild(i)?.let { c -> byDescription(c)?.let { return it } }
        return null
    }

    override fun onInterrupt() {}

    companion object {
        @Volatile private var until = 0L
        @Volatile private var text: String? = null
        fun expectSend(message: String? = null) { text = message; until = System.currentTimeMillis() + 90_000 }
        fun enabled(ctx: Context): Boolean {
            val v = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
            return v.contains(ctx.packageName + "/" + HukumAccess::class.java.name)
        }
    }
}
