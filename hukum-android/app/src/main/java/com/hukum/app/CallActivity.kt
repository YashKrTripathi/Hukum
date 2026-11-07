package com.hukum.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** The incoming-call screen, shown over the lock screen. */
class CallActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        val reason = intent.getStringExtra("reason") ?: "Study time"
        setContent {
            Column(
                Modifier.fillMaxSize().background(Color(0xFF0F1720)).padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.SpaceBetween
            ) {
                Spacer(Modifier.height(48.dp))
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(Modifier.size(120.dp).clip(CircleShape).background(Color(0xFF2F81F7)), contentAlignment = Alignment.Center) {
                        Text("H", color = Color.White, fontSize = 56.sp)
                    }
                    Spacer(Modifier.height(24.dp))
                    Text("Hukum", color = Color.White, fontSize = 34.sp)
                    Text("incoming call…", color = Color(0xFF8AA0B4), fontSize = 16.sp)
                    Spacer(Modifier.height(24.dp))
                    Text(reason, color = Color.White, fontSize = 18.sp, textAlign = TextAlign.Center)
                }
                Row(Modifier.fillMaxWidth().padding(bottom = 48.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
                    Box(Modifier.size(84.dp).clip(CircleShape).background(Color(0xFFD1242F))
                        .clickable { RingNotifier.stop(this@CallActivity); finish() }, contentAlignment = Alignment.Center) {
                        Text("✕", color = Color.White, fontSize = 34.sp)
                    }
                    Box(Modifier.size(84.dp).clip(CircleShape).background(Color(0xFF2EA043))
                        .clickable { answer(reason) }, contentAlignment = Alignment.Center) {
                        Text("📞", fontSize = 34.sp)
                    }
                }
            }
        }
    }

    private fun answer(reason: String) {
        RingNotifier.stop(this)
        startActivity(Intent(this, MainActivity::class.java)
            .putExtra("ring_reason", reason)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
        finish()
    }
}
