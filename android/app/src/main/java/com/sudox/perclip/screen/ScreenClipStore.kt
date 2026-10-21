package com.sudox.perclip.screen

import android.content.Context
import org.json.JSONObject

class ScreenClipStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun savePendingAutoCapture(snapshot: ScreenClipSnapshot) {
        prefs.edit()
            .putString(KEY_PENDING_AUTO_CAPTURE, snapshot.toJson().toString())
            .apply()
    }

    fun consumePendingAutoCapture(maxAgeMs: Long = PENDING_AUTO_CAPTURE_MAX_AGE_MS): ScreenClipSnapshot? {
        val raw = prefs.getString(KEY_PENDING_AUTO_CAPTURE, "").orEmpty()
        prefs.edit().remove(KEY_PENDING_AUTO_CAPTURE).apply()
        if (raw.isBlank()) return null
        val snapshot = runCatching { snapshotFromJson(JSONObject(raw)) }.getOrNull() ?: return null
        val age = System.currentTimeMillis() - snapshot.capturedAtEpochMs
        return snapshot.takeIf { age in 0..maxAgeMs }
    }

    private fun ScreenClipSnapshot.toJson(): JSONObject = JSONObject()
        .put("packageName", packageName)
        .put("appLabel", appLabel)
        .put("title", title)
        .put("text", text)
        .put("url", url)
        .put("capturedAtEpochMs", capturedAtEpochMs)

    private fun snapshotFromJson(json: JSONObject): ScreenClipSnapshot {
        return ScreenClipSnapshot(
            packageName = json.optString("packageName"),
            appLabel = json.optString("appLabel"),
            title = json.optString("title"),
            text = json.optString("text"),
            url = json.optString("url"),
            capturedAtEpochMs = json.optLong("capturedAtEpochMs"),
        )
    }

    companion object {
        private const val PREFS_NAME = "perclip_screen_clip"
        private const val KEY_PENDING_AUTO_CAPTURE = "pending_auto_capture"
        const val PENDING_AUTO_CAPTURE_MAX_AGE_MS = 60 * 1000L
    }
}
