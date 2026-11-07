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
 * Things Boss asks for that belong to THIS phone (call, WhatsApp, flashlight, alarm, volume, apps ...). They are done
 * locally and never sent to the PC. Anything that mentions the PC, or that is not recognised, returns null and goes to
 * the PC as before. Understands English, Hinglish and Hindi word order ("Rahul ko call karo", "WhatsApp kholo").
 */
object PhoneActions {
    private val PC = Regex("(?i)\\b(pc|laptop|computer|desktop|windows)\\b|कंप्यूटर|लैपटॉप|पीसी")
    private val PHONE = Regex("(?i)\\b(phone|mobile|my phone|this phone)\\b|फोन पर|फोन में|फ़ोन|मोबाइल")
    private val WA = Regex("(?i)whats ?app|व्हाट्सएप|व्हाट्सऐप|वॉट्सऐप|वाट्सएप|व्हाट्स ऐप|व्हाट्स एप|वॉट्सएप")
    private val FILLER = Regex("(?i)\\b(whats ?app|open|and|message|msg|text|send|to|ko|par|pe|on|in|my|phone|mobile|bhejo|bhej|do|kar|karo|kardo|bolo|kaho|please|a|the|call|dial|ki|that|saying)\\b|व्हाट्सएप|व्हाट्सऐप|वॉट्सऐप|वाट्सएप|मैसेज|संदेश|को|पर|पे|में|भेजो|भेज|दो|कर|करो|बोलो|कहो|फोन|फ़ोन|कॉल|लगाओ|मिलाओ|मोबाइल")

    /** Returned by handle() when the request is a multi-step job for PhoneAgent. */
    const val AGENT = "@@agent"
    private val INSTALL = Regex("(?i)\\b(install|uninstall|download)\\b|इंस्टॉल|इन्स्टॉल|डाउनलोड|अनइंस्टॉल")
    private val ACT_AFTER_APP = Regex("(?i)\\b(search|find|play|watch|type|go to|scroll|subscribe|like|follow|post|share|book|order|login|log in|sign in|turn on|turn off|enable|disable|set|change|update)\\b|सर्च|ढूंढ|खोज|चलाओ|बजाओ|देखो|चालू करो|बंद करो")

    private val ACTION_ANY = Regex("(?i)\\b(search|google|youtube|play|watch|go to|open|scroll|tap|click|press|subscribe|unsubscribe|follow|unfollow|like|share|post|book|order|turn on|turn off|switch on|switch off|enable|disable|toggle|set|change|update|uninstall|install|download|login|log in|sign in|sign out|log out|clear|delete|find|show me|take a)\\b|सर्च|ढूंढ|खोज|चलाओ|बजाओ|देखो|चालू करो|बंद करो|खोलो|दिखाओ")

    fun openApp(ctx: Context, name: String): Boolean {
        val app = findApp(ctx, name) ?: return false
        val i = ctx.packageManager.getLaunchIntentForPackage(app.first) ?: return false
        return launch(ctx, i)
    }

    private fun launch(ctx: Context, i: Intent): Boolean = try { ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true } catch (e: Exception) { false }
    private fun has(ctx: Context, p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    /** Speech often writes English words in Devanagari ("ओपन एंड सैंड"): turn the common ones back into English first. */
    private val LOAN = mapOf("ओपन" to "open", "एंड" to "and", "एन्ड" to "and", "सैंड" to "send", "सेंड" to "send", "सेन्ड" to "send", "सैन्ड" to "send",
        "मैसेज" to "message", "टेक्स्ट" to "text", "हाय" to "hi", "हाई" to "hi", "हैलो" to "hello", "हेलो" to "hello", "व्हाट्सएप" to "whatsapp", "व्हाट्सऐप" to "whatsapp")
    private fun normalize(s: String): String = s.split(" ").joinToString(" ") { LOAN[it] ?: it }

    fun handle(ctx: Context, raw: String): String? {
        val t = normalize(raw.trim())
        val l = t.lowercase()
        if (l.isBlank() || l.startsWith("__")) return null
        // passwords are answered here and never forwarded to the PC, the gateway or an AI model
        if (Regex("pass ?word|passcode|पासवर्ड|पासकोड").containsMatchIn(l)) {
            val names = Vault.labels(ctx)
            val wantsRead = Regex("\\b(tell|say|read|show|what is|what's|bata|bol|batao)\\b|बता|बोल|दिखा").containsMatchIn(l) && !Regex("\\b(do i|have|saved|any|which|list|kaun|konsa)\\b|कौन|कौनसे").containsMatchIn(l)
            val asked = names.filter { n -> l.contains(n.lowercase()) }
            return when {
                Regex("\\b(save|store|add|remember|set|yaad|save kar)\\b|सेव|याद").containsMatchIn(l) ->
                    "I never take passwords by voice. Open More, then Passwords, and type it there. It stays encrypted on this phone."
                wantsRead -> "I will not read a password aloud or show it. It is only typed into an app after you confirm with your fingerprint."
                asked.isNotEmpty() -> "Yes, a ${asked.joinToString(" and ")} password is saved on this phone."
                names.isEmpty() -> "No passwords are saved yet. Add one in More, then Passwords."
                else -> "Saved passwords: ${names.joinToString(", ")}."
            }
        }
        if (PC.containsMatchIn(l)) return null
        val phone = PHONE.containsMatchIn(l)

        // flashlight
        if (Regex("flash ?light|torch|टॉर्च|फ्लैशलाइट").containsMatchIn(l)) {
            val off = Regex("\\boff\\b|बंद|band|turn off").containsMatchIn(l)
            return try {
                val cm = ctx.getSystemService(Context.CAMERA_SERVICE) as CameraManager
                cm.setTorchMode(cm.cameraIdList.first(), !off); if (off) "Flashlight off." else "Flashlight on."
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

        // WhatsApp: open the app, or open a chat with the message filled in (and tap Send if Hukum's accessibility is on)
        if (WA.containsMatchIn(l)) return whatsapp(ctx, t)
        // "send papa hi", "papa ko hi bhejo": sending a message with no app named means WhatsApp (say "sms" for a text message)
        if (!Regex("(?i)\\bsms\\b|e-?mail|mail").containsMatchIn(l) && Regex("(?i)(?:^|\\s)(?:send|bhejo|bhej do|भेजो|भेज दो)(?:\\s|$)").containsMatchIn(l)) return whatsapp(ctx, t)

        // call: "call Rahul", "Rahul ko call karo", "Rahul को फोन लगाओ"
        val callWord = Regex("(?i)\\bcall\\b|\\bdial\\b|कॉल|फोन लगा|फ़ोन लगा|फोन कर|फ़ोन कर|फोन मिला|phone laga|phone kar|phone mila")
        if (callWord.containsMatchIn(l) && !Regex("missed|मिस्ड|history|log").containsMatchIn(l)) {
            val who = clean(Regex("(?i)^(.+?)\\s+(?:को|ko)(?=\\s|$)").find(l)?.groupValues?.get(1) ?: l.replace(callWord, " "))
            if (who.isNotBlank()) return call(ctx, who)
        }
        // sms: opens the composer with the text filled in (never sends by itself)
        Regex("(?:\\bsms\\b|\\bmessage\\b|\\btext\\b|मैसेज)\\s*(?:to\\s+)?(.+?)\\s*(?:saying|that|:|कि|कहो)\\s*(.+)").find(l)?.let { m ->
            val who = clean(m.groupValues[1]); val body = m.groupValues[2].trim()
            val c = contact(ctx, who) ?: return "I could not find $who in your contacts."
            return if (launch(ctx, Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:${c.second}")).putExtra("sms_body", body))) "Message to ${c.first} is ready: tap send." else "I could not open messages."
        }

        if (INSTALL.containsMatchIn(l)) return AGENT
        // opening an app: phone-first apps need no "phone"; anything else needs it (otherwise it is a PC app)
        val open = Regex("(?i)^(?:please\\s+)?(?:open|launch|start)\\s+(.+)$").find(l)?.groupValues?.get(1)
            ?: Regex("(?i)^(.+?)\\s+(?:खोलो|खोल दो|खोल|चालू कर|kholo|khol do|khol|open kar|open karo|chalu kar|chalu karo)(?=\\s|$)").find(l)?.groupValues?.get(1)
        if (open != null) {
            val name = open.replace(Regex("(?i)\\b(on|in|my|the|phone|mobile|app)\\b|पर|में|मेरे|फोन|मोबाइल"), " ").trim()
            val app = findApp(ctx, name)
            val extra = if (app != null) name.lowercase().replace(app.second.lowercase(), " ").trim() else ""
            if (app != null && extra.length >= 3 && (ACT_AFTER_APP.containsMatchIn(extra) || Regex("(?i)^(and|then|aur|फिर|और)(?=\\s|$)").containsMatchIn(extra))) return AGENT
            if (app != null && (phone || PHONE_FIRST.any { app.second.lowercase().contains(it) })) {
                val i = ctx.packageManager.getLaunchIntentForPackage(app.first)
                if (i != null && launch(ctx, i)) return "Opening ${app.second}."
            }
            if (phone) return "I could not find an app called $name on your phone."
        }
        if (phone) {
            Regex("(?:play|चलाओ|बजाओ)\\s+(.+?)(?:\\s+(?:on|in|पर|में).*)?$").find(l)?.let { m ->
                val q = m.groupValues[1].replace(Regex("(my )?(phone|mobile)"), "").trim()
                return if (launch(ctx, Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH).putExtra(android.app.SearchManager.QUERY, q))) "Playing $q." else "I could not start playback."
            }
            Regex("(?:search|google|सर्च)\\s+(?:for\\s+)?(.+?)(?:\\s+(?:on|in|पर|में).*)?$").find(l)?.let { m ->
                val q = m.groupValues[1].replace(Regex("(my )?(phone|mobile)"), "").trim()
                return if (launch(ctx, Intent(Intent.ACTION_WEB_SEARCH).putExtra(android.app.SearchManager.QUERY, q))) "Searching for $q." else null
            }
        }
        // anything else that is an action for the phone (not a question, not about the PC): let the phone agent work it out
        val question = Regex("(?i)^(what|why|how|who|when|where|kya|kyun|kaise|kaun|kab|kahan|क्या|क्यों|कैसे|कौन|कब|कहाँ)(?=\\s|$)").containsMatchIn(l) || l.contains("?")
        if (!question && ACTION_ANY.containsMatchIn(l)) return AGENT
        return null
    }

    private val PHONE_FIRST = listOf("whatsapp", "instagram", "snapchat", "telegram", "phonepe", "paytm", "google pay", "gpay", "camera", "gallery", "photos",
        "contacts", "messages", "phone", "dialer", "settings", "maps", "play store", "clock", "calculator", "truecaller", "facebook", "messenger", "youtube", "spotify")

    private fun clean(s: String) = s.replace(FILLER, " ").replace(Regex("[,.!?]"), " ").replace(Regex("\\s+"), " ").trim()

    // ---------------------------------------------------------------- WhatsApp
    private fun waPackage(ctx: Context): String? =
        listOf("com.whatsapp", "com.whatsapp.w4b").firstOrNull { try { ctx.packageManager.getPackageInfo(it, 0); true } catch (e: Exception) { false } }

    private fun whatsapp(ctx: Context, raw: String): String {
        val pkg = waPackage(ctx) ?: return "WhatsApp is not installed on this phone."
        val l = raw.trim()
        // split "who ... <separator> body"
        val sep = Regex("(?i)\\s(?:ki|कि|saying|that|ke liye|:)\\s*|\\s(?:कहो|बोलो|kaho|bolo)\\s+|:\\s*").find(l)
        val left = if (sep != null) l.substring(0, sep.range.first) else l
        var body = if (sep != null) l.substring(sep.range.last + 1).trim() else ""
        var who = clean(left.replace(Regex("(?i)\\b(open|launch|start|kholo|khol)\\b|खोलो|खोल|चालू"), " "))
        var c: Pair<String, String>? = null
        // "send papa hi": no separator, so find the longest start of the words that is a contact; the rest is the message
        if (who.isNotBlank() && body.isBlank() && who.contains(" ")) {
            val toks = who.split(" ").filter { it.isNotBlank() }
            for (k in toks.size downTo 1) {
                // a word with no consonant sound ("hi", "ok") is never part of a name: it starts the message
                if (toks.take(k).any { skeleton(it).isEmpty() }) continue
                val hit = contact(ctx, toks.take(k).joinToString(" ")) ?: continue
                c = hit; body = toks.drop(k).joinToString(" "); who = toks.take(k).joinToString(" "); break
            }
        }
        body = when (body.lowercase()) { "hai", "है", "hi", "hii", "हैं" -> "Hi"; "hello", "hallo" -> "Hello"; else -> body }
        if (who.isBlank()) {
            val i = ctx.packageManager.getLaunchIntentForPackage(pkg)
            return if (i != null && launch(ctx, i)) "Opening WhatsApp." else "I could not open WhatsApp."
        }
        if (c == null) { val m = contactMatches(ctx, who); ambiguous(m)?.let { return it }; c = m.firstOrNull() }
        val (name, num) = c ?: run {
            if (!has(ctx, android.Manifest.permission.READ_CONTACTS)) return "Allow Contacts for Hukum (Settings > Apps > Hukum > Permissions), then ask again."
            return "I could not find \"$who\" in your contacts."
        }
        val url = "https://wa.me/${waNumber(num)}" + if (body.isNotBlank()) "?text=" + Uri.encode(body) else ""
        if (body.isNotBlank()) {
            try { (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager).setPrimaryClip(android.content.ClipData.newPlainText("Hukum message", body)) } catch (e: Exception) {}
            if (HukumAccess.enabled(ctx)) HukumAccess.expectSend(body)
        }
        val ok = launch(ctx, Intent(Intent.ACTION_VIEW, Uri.parse(url)).setPackage(pkg))
        return when {
            !ok -> "I could not open WhatsApp."
            body.isBlank() -> "Opened WhatsApp chat with $name. What should I send? Say: WhatsApp $name ki, then your message."
            HukumAccess.enabled(ctx) -> "Sending to $name. If the phone or WhatsApp asks for your fingerprint or PIN, unlock it and I will finish sending."
            else -> "Chat with $name is open. I copied your message: paste it and send, or turn on Hukum accessibility in More > Voice so I can type and send it."
        }
    }

    private fun waNumber(n: String): String {
        val d = n.filter { it.isDigit() }
        return when {
            n.trim().startsWith("+") -> d
            d.length == 10 -> "91$d"
            d.length == 11 && d.startsWith("0") -> "91" + d.substring(1)
            else -> d
        }
    }

    // ---------------------------------------------------------------- contacts (matches Devanagari speech to Latin contact names)
    private val DEV = mapOf(
        'अ' to "a", 'आ' to "a", 'इ' to "i", 'ई' to "i", 'उ' to "u", 'ऊ' to "u", 'ऋ' to "ri", 'ए' to "e", 'ऐ' to "ai", 'ओ' to "o", 'औ' to "au",
        'ा' to "a", 'ि' to "i", 'ी' to "i", 'ु' to "u", 'ू' to "u", 'ृ' to "ri", 'े' to "e", 'ै' to "ai", 'ो' to "o", 'ौ' to "au", 'ॉ' to "o", 'ॅ' to "e",
        'क' to "k", 'ख' to "kh", 'ग' to "g", 'घ' to "gh", 'ङ' to "n", 'च' to "ch", 'छ' to "ch", 'ज' to "j", 'झ' to "jh", 'ञ' to "n",
        'ट' to "t", 'ठ' to "th", 'ड' to "d", 'ढ' to "dh", 'ण' to "n", 'त' to "t", 'थ' to "th", 'द' to "d", 'ध' to "dh", 'न' to "n",
        'प' to "p", 'फ' to "f", 'ब' to "b", 'भ' to "bh", 'म' to "m", 'य' to "y", 'र' to "r", 'ल' to "l", 'व' to "v", 'श' to "sh", 'ष' to "sh", 'स' to "s", 'ह' to "h",
        'ं' to "n", 'ँ' to "n", 'ः' to "h", '्' to "", '़' to "")

    /** Rough sound-alike key: Devanagari or Latin text -> consonant skeleton, so "ऋषि" and "Rishi" both give "rs". */
    private fun skeleton(word: String): String {
        val sb = StringBuilder()
        for (ch in word.lowercase()) sb.append(DEV[ch] ?: if (ch in 'a'..'z') ch.toString() else "")
        var t = sb.toString()
        for ((a, b) in listOf("sh" to "s", "ch" to "c", "ph" to "f", "kh" to "k", "gh" to "g", "th" to "t", "dh" to "d", "bh" to "b", "jh" to "j", "z" to "j", "q" to "k", "x" to "ks", "w" to "v"))
            t = t.replace(a, b)
        t = t.replace(Regex("[aeiouyhv]"), "")
        return t.replace(Regex("(.)\\1+"), "$1")
    }

    /** Words people save family contacts under: "mummy", "mom", "मम्मी", "माँ" are the same person. */
    private val NICK = listOf(
        listOf("mummy", "mommy", "mom", "mama", "maa", "mother", "mata", "मम्मी", "मॉम", "मां", "माँ", "माता", "मम्मा"),
        listOf("papa", "pappa", "dad", "daddy", "father", "pita", "pitaji", "पापा", "डैड", "पिता", "पिताजी", "पप्पा"),
        listOf("bhai", "bhaiya", "brother", "bro", "भाई", "भैया"),
        listOf("didi", "behen", "bahen", "sister", "sis", "दीदी", "बहन"),
        listOf("dadi", "grandma", "दादी"), listOf("dada", "grandpa", "दादा"), listOf("nani", "नानी"), listOf("nana", "नाना"),
        listOf("wife", "biwi", "patni", "पत्नी", "बीवी"), listOf("husband", "pati", "पति"))

    private fun nickGroup(word: String): List<String> = NICK.firstOrNull { g -> g.any { it.equals(word, true) } } ?: listOf(word)

    private class Row(val name: String, val number: String)
    @Volatile private var rowsCache: Pair<Long, List<Row>>? = null

    private fun contactRows(ctx: Context): List<Row> {
        val now = System.currentTimeMillis()
        rowsCache?.let { if (now - it.first < 120_000) return it.second }
        val out = ArrayList<Row>()
        if (has(ctx, android.Manifest.permission.READ_CONTACTS)) {
            try {
                ctx.contentResolver.query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                    arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER), null, null, null)?.use { c ->
                    while (c.moveToNext()) out.add(Row(c.getString(0) ?: "", c.getString(1) ?: ""))
                }
            } catch (e: Exception) { /* no contacts: callers say so */ }
        }
        rowsCache = now to out
        return out
    }

    /** Names handed to the speech recogniser so it listens for them (stops "Rishi" being heard as "Harsh"). Cached; call off the main thread first. */
    fun contactNames(ctx: Context): ArrayList<String> {
        val names = LinkedHashSet<String>()
        contactRows(ctx).forEach { if (it.name.isNotBlank()) names.add(it.name) }
        return ArrayList(names.take(200))
    }

    /** Of the recogniser's alternative transcripts, pick the one that mentions a real contact (or a family word). */
    fun pickBest(ctx: Context, alts: List<String>): String {
        if (alts.size < 2) return alts.firstOrNull().orEmpty()
        val rows = contactRows(ctx)
        val known = HashSet<String>()
        rows.forEach { r -> r.name.lowercase().split(" ", "-", "_").filter { it.isNotBlank() }.forEach { known.add(it) } }
        NICK.flatten().forEach { known.add(it.lowercase()) }
        fun score(t: String) = t.lowercase().split(" ").count { it in known }
        var best = alts[0]; var bs = score(best)
        for (a in alts.drop(1)) { val sc = score(a); if (sc > bs) { best = a; bs = sc } }
        return best
    }

    /** Contacts that match what was said, best first. More than one different name means the request is ambiguous. */
    private fun contactMatches(ctx: Context, who: String): List<Pair<String, String>> {
        val digits = who.filter { it.isDigit() || it == '+' }
        if (digits.length >= 6 && digits.length >= who.replace(" ", "").length - 2) return listOf(who to digits)
        val rows = contactRows(ctx)
        if (rows.isEmpty()) return emptyList()
        rows.filter { it.name.equals(who, true) }.let { ex -> if (ex.isNotEmpty()) return ex.map { it.name to it.number } }
        val words = who.split(" ").filter { it.isNotBlank() }
        // each spoken word -> the sound-keys of its nickname family
        val q = words.map { w -> nickGroup(w).map { skeleton(it) }.filter { it.isNotEmpty() }.toSet() }.filter { it.isNotEmpty() }
        var best = -1; val scored = ArrayList<Pair<Row, Int>>()
        for (r in rows) {
            val raw = r.name.lowercase().split(" ", "-", "_").filter { it.isNotBlank() }
            val ns = raw.map { skeleton(it) }.filter { it.isNotEmpty() }
            if (q.isEmpty() || ns.isEmpty()) continue
            val hit = q.count { grp -> ns.any { n -> grp.any { w -> n == w || (w.length >= 2 && n.startsWith(w)) || (n.length >= 2 && w.startsWith(n)) } } }
            if (hit < q.size) continue
            // exact spelling of the word (or one of its nicknames) in the contact name is a much stronger match than sounding alike
            val exact = words.count { w -> nickGroup(w).any { g -> raw.contains(g.lowercase()) } }
            val score = hit * 10 + exact * 5 - (ns.size - q.size)
            scored.add(r to score); if (score > best) best = score
        }
        val top = scored.filter { it.second == best }.map { it.first.name to it.first.number }
        if (top.isNotEmpty()) return top
        return rows.filter { it.name.contains(who, true) }.map { it.name to it.number }
    }

    private fun contact(ctx: Context, who: String): Pair<String, String>? = contactMatches(ctx, who).firstOrNull()

    private fun ambiguous(m: List<Pair<String, String>>): String? {
        val names = m.map { it.first }.distinctBy { it.lowercase() }
        return if (names.size > 1) "I found " + names.take(4).joinToString(", ") + ". Which one? Say the full name." else null
    }

    private fun call(ctx: Context, who: String): String {
        val m = contactMatches(ctx, who)
        ambiguous(m)?.let { return it }
        val c = m.firstOrNull()
        if (c == null) {
            launch(ctx, Intent(Intent.ACTION_DIAL))
            return if (has(ctx, android.Manifest.permission.READ_CONTACTS)) "I could not find $who in your contacts." else "Allow Contacts for Hukum (Settings > Apps > Hukum > Permissions) so I can call $who. I opened the dialer."
        }
        val uri = Uri.parse("tel:" + Uri.encode(c.second))
        return if (has(ctx, android.Manifest.permission.CALL_PHONE) && launch(ctx, Intent(Intent.ACTION_CALL, uri))) "Calling ${c.first}."
        else if (launch(ctx, Intent(Intent.ACTION_DIAL, uri))) "Dialling ${c.first}: tap the call button (allow Phone permission for Hukum to call directly)." else "I could not start the call."
    }

    private fun findApp(ctx: Context, name: String): Pair<String, String>? {
        val n = name.lowercase().trim()
        if (n.isBlank()) return null
        val pm = ctx.packageManager
        val apps = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { it.activityInfo.packageName to it.loadLabel(pm).toString() }
        val sk = skeleton(n)
        return apps.firstOrNull { it.second.lowercase() == n } ?: apps.firstOrNull { it.second.lowercase().contains(n) }
            ?: apps.firstOrNull { n.contains(it.second.lowercase()) && it.second.length > 2 }
            ?: apps.firstOrNull { sk.length >= 2 && skeleton(it.second) == sk }
    }
}
