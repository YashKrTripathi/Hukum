package com.hukum.app

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Hukum's hands on the phone.
 *  1. WhatsApp sender: types Boss's message into a chat Hukum just opened and taps Send (for ~90 s after Hukum opens it).
 *  2. Phone control: while Boss has given Hukum a task ("open Play Store and install Instagram"), PhoneAgent reads the
 *     screen as a numbered list and taps / types / scrolls here. Nothing is read or done when no task is running.
 * Boss turns it on once in Android's accessibility settings.
 */
class HukumAccess : AccessibilityService() {
    override fun onServiceConnected() { instance = this }

    override fun onUnbind(intent: Intent?): Boolean { if (instance === this) instance = null; return super.onUnbind(intent) }

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

    // ------------------------------------------------------------------ phone control (used by PhoneAgent)
    class Snapshot(val pkg: String, val text: String, val labels: List<String>, val hasPassword: Boolean)

    private var nodes: List<AccessibilityNodeInfo> = emptyList()

    /** The visible screen as a numbered list the model can read: [3] button "Install". */
    fun snapshot(): Snapshot {
        val root = rootInActiveWindow ?: return Snapshot("", "(screen not readable)", emptyList(), false)
        val list = ArrayList<AccessibilityNodeInfo>(); val lines = ArrayList<String>(); val labels = ArrayList<String>()
        var pw = false
        fun walk(n: AccessibilityNodeInfo?) {
            if (n == null || list.size >= 90) return
            if (!n.isVisibleToUser) return
            if (n.isPassword) pw = true
            val t = n.text?.toString()?.trim().orEmpty()
            val d = n.contentDescription?.toString()?.trim().orEmpty()
            val label = (if (t.isNotBlank()) t else d).replace("\n", " ").take(70)
            val kind = when {
                n.isEditable -> "input"
                n.isCheckable -> "switch"
                n.isClickable -> "button"
                n.isScrollable -> "list"
                else -> "text"
            }
            val interesting = label.isNotBlank() || n.isEditable || n.isClickable || n.isCheckable
            if (interesting && !(kind == "text" && label.isBlank())) {
                val i = list.size
                list.add(n); labels.add(label)
                var line = "[$i] $kind \"$label\""
                if (n.isEditable && n.isShowingHintText) line += " (empty)"
                if (n.isCheckable) line += if (n.isChecked) " on" else " off"
                lines.add(line)
            }
            for (c in 0 until n.childCount) walk(n.getChild(c))
        }
        walk(root)
        nodes = list
        return Snapshot(root.packageName?.toString().orEmpty(), "app: ${root.packageName}\n" + lines.joinToString("\n"), labels, pw)
    }

    private fun tap(r: Rect): Boolean {
        val p = Path().apply { moveTo(r.exactCenterX(), r.exactCenterY()) }
        return dispatchGesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(p, 0, 60)).build(), null, null)
    }

    fun click(i: Int): Boolean {
        val node = nodes.getOrNull(i) ?: return false
        var n: AccessibilityNodeInfo? = node
        while (n != null && !n.isClickable) n = n.parent
        if (n != null && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true
        val r = Rect(); node.getBoundsInScreen(r)
        return !r.isEmpty && tap(r)
    }

    fun type(i: Int, value: String): Boolean {
        val node = nodes.getOrNull(i) ?: return false
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, android.os.Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value) })
    }

    /** Press the keyboard's search / enter key in the focused text box. */
    fun enter(): Boolean {
        val f = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: return false
        return f.performAction(android.R.id.accessibilityActionImeEnter)
    }

    fun scroll(forward: Boolean): Boolean {
        fun find(n: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
            if (n == null) return null
            if (n.isScrollable) return n
            for (c in 0 until n.childCount) find(n.getChild(c))?.let { return it }
            return null
        }
        val s = find(rootInActiveWindow) ?: return false
        return s.performAction(if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
    }

    fun back() = performGlobalAction(GLOBAL_ACTION_BACK)
    fun home() = performGlobalAction(GLOBAL_ACTION_HOME)

    companion object {
        @Volatile var instance: HukumAccess? = null
        @Volatile private var until = 0L
        @Volatile private var text: String? = null
        fun expectSend(message: String? = null) { text = message; until = System.currentTimeMillis() + 90_000 }
        fun enabled(ctx: Context): Boolean {
            val v = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
            return v.contains(ctx.packageName + "/" + HukumAccess::class.java.name)
        }
    }
}
