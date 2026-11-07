package com.hukum.app

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.PowerManager
import android.os.Process

/** Sees which app you are in (needs "Usage access") so Hukum can catch doomscrolling on the phone. */
object UsageWatcher {
    data class State(val state: String, val app: String)

    private val distract = listOf(
        "com.google.android.youtube", "com.instagram.android", "com.facebook.katana", "com.snapchat.android",
        "com.netflix.mediaclient", "in.startv.hotstar", "com.twitter.android", "com.reddit.frontpage",
        "com.zhiliaoapp.musically", "com.amazon.avod.thirdpartyclient", "tv.twitch.android.app",
        "com.spotify.music", "com.discord", "in.mohalla.video", "com.jio.media.ondemand", "com.sonyliv"
    )
    private val study = listOf(
        "com.udemy.android", "com.leetcode", "org.geeksforgeeks", "com.adobe.reader",
        "com.google.android.apps.classroom", "com.google.android.apps.docs", "com.termux", "org.coursera"
    )

    fun hasAccess(ctx: Context): Boolean {
        val ops = ctx.getSystemService(AppOpsManager::class.java)
        return ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName) ==
            AppOpsManager.MODE_ALLOWED
    }

    /** Returns null when there is nothing useful to say (screen off, no permission, no recent activity). */
    fun sample(ctx: Context): State? {
        if (!hasAccess(ctx)) return null
        if (!ctx.getSystemService(PowerManager::class.java).isInteractive) return null
        val usm = ctx.getSystemService(UsageStatsManager::class.java)
        val end = System.currentTimeMillis()
        val events = usm.queryEvents(end - 10 * 60_000, end)
        val e = UsageEvents.Event()
        var pkg: String? = null
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            if (e.eventType == UsageEvents.Event.ACTIVITY_RESUMED) pkg = e.packageName
        }
        pkg ?: return null
        return State(classify(ctx, pkg), pkg)
    }

    private fun classify(ctx: Context, pkg: String): String {
        if (study.any { pkg.startsWith(it) }) return "study"
        if (distract.any { pkg.startsWith(it) }) return "distract"
        return try {
            if (ctx.packageManager.getApplicationInfo(pkg, 0).category == ApplicationInfo.CATEGORY_GAME) "distract" else "other"
        } catch (e: Exception) { "other" }
    }
}
