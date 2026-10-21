package com.sudox.perclip

import android.content.ClipboardManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import com.sudox.perclip.screen.ScreenClipBuilder
import com.sudox.perclip.screen.ScreenClipSnapshot
import com.sudox.perclip.screen.ScreenClipStore
import com.sudox.perclip.screen.adapters.XhsLinkValidator
import com.sudox.perclip.capture.CaptureSaveController
import com.sudox.perclip.capture.CaptureOrigin
import com.sudox.perclip.capture.CaptureSaveRequest

class ClipboardBridgeActivity : ComponentActivity() {
    private val handler = Handler(Looper.getMainLooper())
    private var completionStarted = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(TAG, "clipboard bridge created action=${intent?.action.orEmpty()}")
    }

    override fun onResume() {
        super.onResume()
        if (completionStarted) return
        completionStarted = true
        handler.postDelayed({ handleCompletedAutoCapture() }, INITIAL_CLIPBOARD_READ_DELAY_MS)
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun handleCompletedAutoCapture() {
        val store = ScreenClipStore(this)
        val snapshot = store.consumePendingAutoCapture()
        if (snapshot == null) {
            Toast.makeText(this, "没有可保存的当前屏幕内容。", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        completeAutoCaptureWhenClipboardReady(snapshot, attempt = 0)
    }

    private fun completeAutoCaptureWhenClipboardReady(
        snapshot: ScreenClipSnapshot,
        attempt: Int,
    ) {
        val clipboardText = readClipboardText()
        val xhsUrl = XhsLinkValidator.extractXhsUrl(clipboardText)
        if (xhsUrl.isBlank()) {
            if (attempt < CLIPBOARD_READ_RETRY_COUNT) {
                Log.i(TAG, "xhs bridge clipboard not ready attempt=$attempt length=${clipboardText.length}")
                handler.postDelayed({
                    completeAutoCaptureWhenClipboardReady(snapshot, attempt + 1)
                }, CLIPBOARD_READ_RETRY_DELAY_MS)
            } else {
                Log.i(TAG, "xhs bridge clipboard unavailable after retries")
                saveSnapshot(snapshot)
            }
            return
        }

        val enrichedSnapshot = snapshot.copy(
            url = xhsUrl,
            text = appendOriginalUrl(snapshot.text, xhsUrl),
        )
        val clip = ScreenClipBuilder.toUrlClip(enrichedSnapshot)
        val result = CaptureSaveController(this).save(
            CaptureSaveRequest(
                clip = clip,
                origin = CaptureOrigin.CLIPBOARD_BRIDGE,
            ),
        )
        Log.i(TAG, "xhs bridge url clip saved id=${clip.id} success=${result.savedLocally}")
        Toast.makeText(
            this,
            if (result.savedLocally) "已闪记小红书链接。" else result.message.ifBlank { "本地保存失败，请重试。" },
            if (result.savedLocally) Toast.LENGTH_SHORT else Toast.LENGTH_LONG,
        ).show()
        finish()
    }

    private fun readClipboardText(): String {
        val clipboard = getSystemService(ClipboardManager::class.java) ?: return ""
        val clipData = clipboard.primaryClip ?: return ""
        return buildString {
            for (index in 0 until clipData.itemCount) {
                val text = clipData.getItemAt(index).coerceToText(this@ClipboardBridgeActivity)
                    ?.toString()
                    .orEmpty()
                if (text.isNotBlank()) {
                    if (isNotEmpty()) append('\n')
                    append(text)
                }
            }
        }
    }

    private fun appendOriginalUrl(text: String, url: String): String {
        if (text.contains(url)) return text
        return text.trimEnd() + "\n\n原始链接：$url"
    }

    private fun saveSnapshot(snapshot: ScreenClipSnapshot) {
        val result = CaptureSaveController(this).save(
            CaptureSaveRequest(
                clip = ScreenClipBuilder.toSharedClip(snapshot),
                origin = CaptureOrigin.SCREEN_CAPTURE,
            ),
        )
        Log.i(TAG, "xhs bridge snapshot fallback saved success=${result.savedLocally}")
        Toast.makeText(
            this,
            if (result.savedLocally) "未复制到链接，已保存当前屏幕。" else result.message.ifBlank { "本地保存失败，请重试。" },
            if (result.savedLocally) Toast.LENGTH_SHORT else Toast.LENGTH_LONG,
        ).show()
        finish()
    }

    companion object {
        private const val TAG = "PerClipCapture"
        private const val INITIAL_CLIPBOARD_READ_DELAY_MS = 180L
        private const val CLIPBOARD_READ_RETRY_COUNT = 10
        private const val CLIPBOARD_READ_RETRY_DELAY_MS = 500L
    }
}
