package com.hukum.app

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Taps WhatsApp's Send button, but only for a short window right after Hukum itself opened a chat with Boss's message
 * filled in. It reads nothing else and does nothing otherwise. Boss turns it on once in Android's accessibility settings.
 */
class HukumAccess : AccessibilityService() {
    override fun onAccessibilityEvent(e: AccessibilityEvent?) {
        val pkg = e?.packageName?.toString() ?: return
        if (!pkg.startsWith("com.whatsapp") || System.currentTimeMillis() > until) return
        val root = rootInActiveWindow ?: return
        val btn = root.findAccessibilityNodeInfosByViewId("$pkg:id/send").firstOrNull() ?: byDescription(root)
        if (btn != null && btn.isEnabled) {
            var n: AccessibilityNodeInfo? = btn
            while (n != null && !n.isClickable) n = n.parent
            if (n?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true) until = 0L
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
        fun expectSend() { until = System.currentTimeMillis() + 25_000 }
        fun enabled(ctx: Context): Boolean {
            val v = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
            return v.contains(ctx.packageName + "/" + HukumAccess::class.java.name)
        }
    }
}
