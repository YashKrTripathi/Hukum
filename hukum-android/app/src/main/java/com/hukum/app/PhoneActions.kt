package com.hukum.app

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.os.BatteryManager
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.provider.MediaStore
import android.provider.Settings

/**
 * Things Boss asks for that belong to THIS phone (call, flashlight, alarm, volume, apps ...). They are done locally and
 * never sent to the PC. Anything that mentions the PC, or that is not recognised, returns null and goes to the PC as before.
 */
object PhoneActions {
    private val PC = Regex("(?i)\\b(pc|laptop|computer|desktop|windows)\\b|कंप्यूटर|लैपटॉप|पीसी")
    private val PHONE = Regex("(?i)\\b(phone|mobile|my phone|this phone)\\b|फोन पर|फोन में|फ़ोन|मोबाइल")

    private fun launch(ctx: Context, i: Intent): Boolean = try { ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true } catch (e: Exception) { false }
    private fun has(ctx: Context, p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    fun handle(ctx: Context, raw: String): String? {
        val t = raw.trim()
        val l = t.lowercase()
        if (l.isBlank() || l.startsWith("__")) return null
        if (PC.containsMatchIn(l)) return null
        val phone = PHONE.containsMatchIn(l)

        // flashlight
        if (Regex("flash ?light|torch|टॉर्च|फ्लैशलाइट").containsMatchIn(l)) {
            val off = Regex("\\boff\\b|बंद|band|turn off").containsMatchIn(l)
            return try {
                val cm = ctx.getSystemService(Context.CAMERA_SERVICE) as CameraManager
                val id = cm.cameraIdList.first()
                cm.setTorchMode(id, !off); if (off) "Flashlight off." else "Flashlight on."
            } catch (e: Exception) { "I could not use the flashlight: ${e.message}" }
        }
        // battery
        if (Regex("battery|बैटरी").containsMatchIn(l)) {
            val bm = ctx.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
            return "Phone battery is ${bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)} percent."
        }
        // volume
        if (Regex("volume|आवाज़|आवाज|वॉल्यूम|\\bmute\\b|silent").containsMatchIn(l)) {
            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val up = Regex("up|increase|more|full|बढ़ा|बढ़ाओ|ज्यादा|zyada").containsMatchIn(l)
            val down = Regex("down|decrease|less|lower|कम|घटा").containsMatchIn(l)
            val mute = Regex("mute|silent|off|बंद").containsMatchIn(l)
            return when {
                mute && !up -> { am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, AudioManager.FLAG_SHOW_UI); "Muted." }
                up -> { repeat(3) { am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, if (it == 2) AudioManager.FLAG_SHOW_UI else 0) }; "Volume up." }
                down -> { repeat(3) { am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, if (it == 2) AudioManager.FLAG_SHOW_UI else 0) }; "Volume down." }
                else -> null
            }
        }
        // timer / alarm
        Regex("(?i)timer.*?(\\d+)\\s*(second|sec|minute|min|hour|सेकंड|मिनट|घंटे|घंटा)|(\\d+)\\s*(second|sec|minute|min|hour|सेकंड|मिनट|घंटे|घंटा).*?timer").find(l)?.let { m ->
            val n = (m.groups[1]?.value ?: m.groups[3]?.value)!!.toInt()
            val u = (m.groups[2]?.value ?: m.groups[4]?.value)!!
            val secs = if (u.startsWith("sec") || u == "सेकंड") n else if (u.startsWith("min") || u == "मिनट") n * 60 else n * 3600
            return if (launch(ctx, Intent(AlarmClock.ACTION_SET_TIMER).putExtra(AlarmClock.EXTRA_LENGTH, secs).putExtra(AlarmClock.EXTRA_SKIP_UI, true))) "Timer set for $n $u." else "I could not set the timer."
        }
        if (Regex("alarm|अलार्म").containsMatchIn(l)) {
            val m = Regex("(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm|बजे)?").find(l)
            if (m != null) {
                var h = m.groupValues[1].toInt(); val min = m.groupValues[2].ifBlank { "0" }.toInt()
                val ap = m.groupValues[3]
                if (ap == "pm" && h < 12) h += 12
                if (ap == "am" && h == 12) h = 0
                if (h in 0..23 && min in 0..59)
                    return if (launch(ctx, Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, h).putExtra(AlarmClock.EXTRA_MINUTES, min).putExtra(AlarmClock.EXTRA_SKIP_UI, true)))
                        "Alarm set for %02d:%02d.".format(h, min) else "I could not set the alarm."
            }
            return if (launch(ctx, Intent(AlarmClock.ACTION_SHOW_ALARMS))) "Here are your alarms." else null
        }
        // settings panels
        if (Regex("wi-?fi|वाईफाई|वाई-फाई").containsMatchIn(l)) return if (launch(ctx, Intent(Settings.ACTION_WIFI_SETTINGS))) "Opening Wi-Fi settings." else null
        if (Regex("bluetooth|ब्लूटूथ").containsMatchIn(l)) return if (launch(ctx, Intent(Settings.ACTION_BLUETOOTH_SETTINGS))) "Opening Bluetooth settings." else null
        // camera
        if (Regex("camera|selfie|कैमरा|सेल्फी").containsMatchIn(l)) return if (launch(ctx, Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA))) "Opening the camera." else null
        // navigation
        Regex("(?:navigate to|directions to|take me to|route to|रास्ता|नेविगेट)\\s*(.+)").find(l)?.let { m ->
            val q = m.groupValues[1].trim()
            if (q.isNotBlank()) return if (launch(ctx, Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=" + Uri.encode(q))))) "Navigating to $q." else "I could not open maps."
        }
        // call
        Regex("(?:\\bcall\\b|\\bphone\\b to|dial|कॉल|फोन लगा|फ़ोन लगा)\\s*(?:to\\s+)?(.+)").find(l)?.let { m ->
            var who = m.groupValues[1].trim().removeSuffix("please").removeSuffix("kar do").removeSuffix("करो").removeSuffix("लगाओ").trim()
            if (who.isNotBlank() && !Regex("my phone|the pc").containsMatchIn(who)) return call(ctx, who)
        }
        // sms: opens the composer with the text filled in (never sends by itself)
        Regex("(?:\\bsms\\b|\\bmessage\\b|\\btext\\b|मैसेज)\\s*(?:to\\s+)?(.+?)\\s*(?:saying|that|:|कि|कहो)\\s*(.+)").find(l)?.let { m ->
            val who = m.groupValues[1].trim(); val body = m.groupValues[2].trim()
            if (!Regex("whatsapp|व्हाट्सएप").containsMatchIn(l)) {
                val num = number(ctx, who) ?: return "I could not find $who in your contacts."
                return if (launch(ctx, Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:$num")).putExtra("sms_body", body))) "Message to $who is ready: tap send." else "I could not open messages."
            }
        }
        // the rest only when Boss says "phone"
        if (phone) {
            Regex("(?:open|launch|start|खोलो|खोल|चालू)\\s+(.+?)(?:\\s+(?:on|in|पर|में).*)?$").find(l)?.let { m ->
                val name = m.groupValues[1].replace(Regex("(my )?(phone|mobile)"), "").trim()
                val pkg = findApp(ctx, name)
                if (pkg != null) { val i = ctx.packageManager.getLaunchIntentForPackage(pkg.first); if (i != null && launch(ctx, i)) return "Opening ${pkg.second} on your phone." }
                return "I could not find an app called $name on your phone."
            }
            Regex("(?:play|चलाओ|बजाओ)\\s+(.+?)(?:\\s+(?:on|in|पर|में).*)?$").find(l)?.let { m ->
                val q = m.groupValues[1].replace(Regex("(my )?(phone|mobile)"), "").trim()
                val i = Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH).putExtra(android.app.SearchManager.QUERY, q)
                return if (launch(ctx, i)) "Playing $q." else "I could not start playback."
            }
            Regex("(?:search|google|सर्च)\\s+(?:for\\s+)?(.+?)(?:\\s+(?:on|in|पर|में).*)?$").find(l)?.let { m ->
                val q = m.groupValues[1].replace(Regex("(my )?(phone|mobile)"), "").trim()
                return if (launch(ctx, Intent(Intent.ACTION_WEB_SEARCH).putExtra(android.app.SearchManager.QUERY, q))) "Searching for $q." else null
            }
        }
        return null
    }

    private fun findApp(ctx: Context, name: String): Pair<String, String>? {
        val n = name.lowercase().trim()
        if (n.isBlank()) return null
        val pm = ctx.packageManager
        val apps = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { it.activityInfo.packageName to it.loadLabel(pm).toString() }
        return apps.firstOrNull { it.second.lowercase() == n } ?: apps.firstOrNull { it.second.lowercase().contains(n) } ?: apps.firstOrNull { n.contains(it.second.lowercase()) && it.second.length > 2 }
    }

    private fun number(ctx: Context, who: String): String? {
        val digits = who.filter { it.isDigit() || it == '+' }
        if (digits.length >= 6 && digits.length >= who.replace(" ", "").length - 2) return digits
        if (!has(ctx, android.Manifest.permission.READ_CONTACTS)) return null
        ctx.contentResolver.query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI, arrayOf(ContactsContract.CommonDataKinds.Phone.NUMBER),
            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " LIKE ?", arrayOf("%$who%"), null)?.use { c -> if (c.moveToFirst()) return c.getString(0) }
        return null
    }

    private fun call(ctx: Context, who: String): String {
        val num = number(ctx, who)
        if (num == null) {
            // no permission or no match: let the phone's own contact search/dialer handle it
            launch(ctx, Intent(Intent.ACTION_DIAL))
            return if (has(ctx, android.Manifest.permission.READ_CONTACTS)) "I could not find $who in your contacts." else "Allow contacts for Hukum (More > Voice) so I can call $who. I opened the dialer."
        }
        val uri = Uri.parse("tel:" + Uri.encode(num))
        return if (has(ctx, android.Manifest.permission.CALL_PHONE) && launch(ctx, Intent(Intent.ACTION_CALL, uri))) "Calling $who."
        else if (launch(ctx, Intent(Intent.ACTION_DIAL, uri))) "Dialling $who: tap call." else "I could not start the call."
    }
}
