package com.hukum.app

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * Does a multi-step job on the phone ("open Play Store and install Instagram", "open YouTube and search T-Series"):
 * look at the screen, ask the gateway's AI for the next action, do it with the accessibility service, repeat.
 * Hard limits: 20 steps; stops for passwords / OTP / fingerprint; never taps payment buttons.
 */
object PhoneAgent {
    private val PAYMENT = Regex("(?i)\\b(buy|pay|payment|purchase|order|checkout|donate|send money|transfer|add to cart|delete account|factory reset|erase all)\\b|खरीद|भुगतान")
    private const val MAX_STEPS = 20

    suspend fun run(ctx: Context, api: Api, goal: String, progress: (String) -> Unit): String = withContext(Dispatchers.Default) { loop(ctx, api, goal, progress) }

    private suspend fun loop(ctx: Context, api: Api, goal: String, progress: (String) -> Unit): String {
        val acc = HukumAccess.instance ?: return "Hukum phone control is not running. Turn it on in More > Voice & wake word > Accessibility settings."
        val history = ArrayList<String>()
        val filled = HashSet<String>()
        var same = 0; var lastScreen = ""
        for (step in 1..MAX_STEPS) {
            delay(if (step == 1) 500 else 1100)
            val snap = acc.snapshot()
            if (snap.hasPassword) {
                val appName = try { ctx.packageManager.getApplicationLabel(ctx.packageManager.getApplicationInfo(snap.pkg, 0)).toString() } catch (e: Exception) { snap.pkg }
                if (snap.pkg in filled) return "The password box is still showing. Please check it yourself, then ask me to continue."
                val label = Vault.find(ctx, appName, snap.pkg, goal)
                    ?: return "$appName is asking for a password and none is saved for it. Add one in More > Passwords, or enter it yourself."
                progress("Confirm with your fingerprint to use the saved $label password")
                if (!Auth.user(ctx, "Hukum wants to fill your $label password", "Confirm it is you. The password is typed straight into the app and is never shown or sent anywhere.")) return "Not confirmed, so I did not fill the password."
                val ok = Vault.get(ctx, label)?.let { acc.fillPassword(it) } ?: false
                if (!ok) return "I could not fill the password. Please enter it yourself."
                filled.add(snap.pkg)
                history.add("filled the saved $label password (hidden)")
                continue
            }
            same = if (snap.text == lastScreen) same + 1 else 0
            lastScreen = snap.text
            if (same >= 4) return "The screen is not changing, so I stopped. Tell me what to try."
            val r = try { withContext(Dispatchers.IO) { api.phoneStep(goal, snap.text, history) } } catch (e: Exception) { return "I could not reach my brain: ${e.message}" }
            val action = r.optString("action"); val idx = r.optInt("index", -1); val txt = r.optString("text"); val say = r.optString("say")
            if (say.isNotBlank()) progress(say)
            var ok = true
            when (action) {
                "done" -> return say.ifBlank { "Done." }
                "fail" -> return say.ifBlank { "I could not do that." }
                "wait_user" -> return say.ifBlank { "I need you to do something on the screen, then ask me to continue." }
                "click" -> {
                    val label = snap.labels.getOrNull(idx).orEmpty()
                    if (PAYMENT.containsMatchIn(label)) return "I stopped before tapping \"$label\" because it looks like a payment. Please do that yourself."
                    ok = acc.click(idx)
                }
                "type" -> {
                    if (PAYMENT.containsMatchIn(txt) || Regex("^[0-9 ]{4,}$").matches(txt.trim())) return "I will not type that (looks like a PIN, OTP or card number). Please enter it yourself."
                    ok = acc.type(idx, txt)
                }
                "enter" -> ok = acc.enter()
                "scroll_down" -> ok = acc.scroll(true)
                "scroll_up" -> ok = acc.scroll(false)
                "back" -> ok = acc.back()
                "home" -> ok = acc.home()
                "open_app" -> ok = PhoneActions.openApp(ctx, txt)
                "wait" -> delay(1200)
                else -> return "I got an action I do not understand ($action)."
            }
            history.add(("$action ${if (idx >= 0) "[$idx]" else ""} ${txt.take(40)}").trim() + if (ok) "" else " (FAILED)")
        }
        return "That took more than $MAX_STEPS steps, so I stopped. Tell me what to do next."
    }
}
