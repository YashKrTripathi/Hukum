package com.hukum.app

import android.content.Context
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Talks to the Hukum brain (the Python server). All calls are blocking: run them off the main thread. */
class Api(private val ctx: Context) {
    data class Reply(val text: String, val speech: String, val actions: List<JSONObject> = emptyList())
    data class Event(val id: Int, val type: String, val text: String)

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(90, TimeUnit.SECONDS).build()
    private val poll = http.newBuilder().readTimeout(40, TimeUnit.SECONDS).build()
    private val json = "application/json; charset=utf-8".toMediaType()

    private fun req(path: String): Request.Builder =
        Request.Builder().url(Prefs.server(ctx).trimEnd('/') + path).header("X-Key", Prefs.key(ctx))

    private fun fail(code: Int, body: String): Nothing {
        val msg = try { JSONObject(body).optString("error") } catch (e: Exception) { "" }
        throw IOException(if (code == 401) "Wrong key - paste the link from the bot again" else msg.ifBlank { "Server error $code" })
    }

    fun chat(text: String): Reply {
        val body = JSONObject().put("text", text).toString().toRequestBody(json)
        http.newCall(req("/api/chat").post(body).build()).execute().use { r ->
            val s = r.body?.string() ?: ""
            if (!r.isSuccessful) fail(r.code, s)
            val j = JSONObject(s)
            val acts = j.optJSONArray("actions")
            val list = (0 until (acts?.length() ?: 0)).map { acts!!.getJSONObject(it) }
            return Reply(j.getString("text"), j.optString("speech", j.getString("text")), list)
        }
    }

    fun tts(text: String): ByteArray {
        val body = JSONObject().put("text", text).toString().toRequestBody(json)
        http.newCall(req("/api/tts").post(body).build()).execute().use { r ->
            if (!r.isSuccessful) fail(r.code, r.body?.string() ?: "")
            return r.body!!.bytes()
        }
    }

    /** Long-poll for server events (rings). since=-1 just returns the latest id. */
    fun events(since: Int): Pair<Int, List<Event>> {
        poll.newCall(req("/api/events?since=$since").build()).execute().use { r ->
            val s = r.body?.string() ?: ""
            if (!r.isSuccessful) fail(r.code, s)
            val j = JSONObject(s)
            val arr = j.getJSONArray("events")
            val list = (0 until arr.length()).map {
                val e = arr.getJSONObject(it)
                Event(e.getInt("id"), e.getString("type"), e.optString("text"))
            }
            return j.getInt("last") to list
        }
    }

    fun phoneState(state: String, app: String) {
        val body = JSONObject().put("state", state).put("app", app).toString().toRequestBody(json)
        http.newCall(req("/api/phone_state").post(body).build()).execute().close()
    }

    /** Sends notification events (new messages / removed) to the brain. */
    fun inbox(batch: org.json.JSONArray) {
        val body = JSONObject().put("batch", batch).toString().toRequestBody(json)
        http.newCall(req("/api/inbox").post(body).build()).execute().use { r ->
            if (!r.isSuccessful) fail(r.code, r.body?.string() ?: "")
        }
    }

    fun ping(): Boolean = try {
        http.newCall(req("/api/events?since=-1").build()).execute().use { it.isSuccessful }
    } catch (e: Exception) { false }
}
