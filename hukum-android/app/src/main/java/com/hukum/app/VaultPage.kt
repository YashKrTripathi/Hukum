package com.hukum.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.material3.OutlinedTextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.unit.dp

/** More > Passwords: the only place a password is entered for Hukum (never by voice). Shows names only, never the secrets. */
@Composable
fun VaultPage() {
    val ctx = LocalContext.current
    var labels by remember { mutableStateOf(Vault.labels(ctx)) }
    var label by remember { mutableStateOf("") }
    var secret by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var del by remember { mutableStateOf<String?>(null) }
    Page {
        H("Passwords", "Saved on this phone only, encrypted")
        Panel {
            Title("How this stays safe")
            Mut("• Encrypted with a key held by Android's Keystore. Never sent to the server, the PC, the AI or the history.")
            Mut("• Hukum fills a password into an app only after you confirm with your fingerprint or screen lock.")
            Mut("• Hukum never reads a password aloud and never takes one by voice. Say \"do I have a WhatsApp password saved?\" to check.")
            Mut("• Name each one like the app: WhatsApp, Instagram, Gmail. That is how Hukum finds it.")
        }
        Panel(hot = true) {
            Title("Add or replace")
            OutlinedTextField(label, { label = it }, Modifier.fillMaxWidth(), label = { Mut("Name (app or site)") }, singleLine = true)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(secret, { secret = it }, Modifier.fillMaxWidth(), label = { Mut("Password") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
            Spacer(Modifier.height(8.dp))
            Btn("Save in vault", primary = true, enabled = label.isNotBlank() && secret.isNotEmpty()) {
                try { Vault.put(ctx, label, secret); labels = Vault.labels(ctx); note = "Saved \"${label.trim()}\"."; label = ""; secret = "" }
                catch (e: Exception) { note = "Could not save: ${e.message}" }
            }
            if (note.isNotBlank()) Mut(note, Modifier.padding(top = 8.dp))
        }
        Panel {
            Title("Saved (${labels.size})")
            if (labels.isEmpty()) Mut("Nothing saved yet.")
            labels.forEach { l ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                    Tx(l); Btn("Delete", danger = true) { del = l }
                }
                Spacer(Modifier.size(6.dp))
            }
        }
    }
    del?.let { d -> Confirm("Delete \"$d\"?", "The saved password is erased from this phone.", "Delete", true, { Vault.delete(ctx, d); labels = Vault.labels(ctx) }, { del = null }) }
}
