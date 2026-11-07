package com.hukum.app

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/** Everything the phone does to the PC goes through here: Hukum Desktop's dashboard API, relayed by the gateway. */
class DeskVM(app: Application) : AndroidViewModel(app) {
    private val api = Api(app)
    var home by mutableStateOf<JSONObject?>(null)
    var error by mutableStateOf<String?>(null)
    var toast by mutableStateOf<String?>(null)
    var tick by mutableStateOf(0)                     // bump to make open screens reload
    var lastReply by mutableStateOf<String?>(null)
    var thinking by mutableStateOf(false)

    suspend fun obj(path: String): JSONObject = withContext(Dispatchers.IO) { JSONObject(api.desktop("GET", path)) }
    suspend fun arr(path: String): JSONArray = withContext(Dispatchers.IO) { JSONArray(api.desktop("GET", path)) }
    suspend fun post(path: String, body: JSONObject = JSONObject()): JSONObject = withContext(Dispatchers.IO) { JSONObject(api.desktop("POST", path, body)) }

    suspend fun refreshHome() {
        if (!Prefs.configured(getApplication())) { error = "Not connected - open More > Connection"; return }
        try { home = obj("/api/m/home"); error = null } catch (e: Exception) { error = e.message ?: "PC unreachable" }
    }

    fun refreshNow() { viewModelScope.launch { refreshHome(); tick++ } }

    /** Run something on the PC and show its outcome as a toast; refresh afterwards. */
    fun act(path: String, body: JSONObject = JSONObject(), ok: String = "Done") {
        viewModelScope.launch {
            try {
                val r = post(path, body)
                val failed = r.has("ok") && !r.optBoolean("ok", true)
                toast = if (failed) "✖ " + r.s("error", "failed") else if (r.has("error")) "✖ " + r.s("error") else "✔ $ok"
            } catch (e: Exception) { toast = "✖ ${e.message}" }
            refreshHome(); tick++
        }
    }

    fun tool(name: String, args: JSONObject = JSONObject(), ok: String = "Done") =
        act("/api/tools/call", JSONObject().put("name", name).put("args", args), ok)

    /** Natural-language command to Hukum on the PC (same brain as the dashboard chat). */
    fun ask(text: String) {
        if (text.isBlank() || thinking) return
        thinking = true; lastReply = null
        viewModelScope.launch {
            try {
                val id = post("/api/m/chat", JSONObject().put("text", text)).s("id")
                repeat(120) {
                    delay(1000)
                    val r = obj("/api/m/chat_result?id=$id")
                    if (r.optBoolean("done")) { lastReply = r.s("reply"); return@launch }
                }
                lastReply = "Still working on it - check Alerts or the Security tab for approvals."
            } catch (e: Exception) { lastReply = "✖ ${e.message}" }
            finally { thinking = false; refreshHome() }
        }
    }

    fun decide(id: Int, approve: Boolean) = act("/api/approvals/decide", JSONObject().put("id", id).put("decision", if (approve) "approve" else "reject"), if (approve) "Approved" else "Rejected")
    fun estop(on: Boolean) = act("/api/estop", JSONObject().put("on", on), if (on) "Emergency stop ON" else "Released")
}
