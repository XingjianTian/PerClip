package com.sudox.perclip

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import com.sudox.perclip.capture.CaptureOrigin
import com.sudox.perclip.capture.CaptureSaveController
import com.sudox.perclip.capture.CaptureSaveRequest
import com.sudox.perclip.share.ShareIntentParser
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

object ShareCaptureRequestPolicy {
    fun restoreRequestId(savedRequestId: String?, createRequestId: () -> String): String {
        return savedRequestId?.trim().orEmpty().ifBlank(createRequestId)
    }

    fun shouldLaunchSave(saveCompleted: Boolean, launchedInCurrentInstance: Boolean): Boolean {
        return !saveCompleted && !launchedInCurrentInstance
    }
}

private object ShareCaptureSaveCoordinator {
    private val requestSaveMutex = Mutex()

    suspend fun <T> serialize(block: () -> T): T = requestSaveMutex.withLock { block() }
}

class ShareCaptureActivity : ComponentActivity() {
    private lateinit var captureRequestId: String
    private var saveStarted = false
    private var saveCompleted = false
    private var saveLaunchedInCurrentInstance = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        captureRequestId = ShareCaptureRequestPolicy.restoreRequestId(
            savedRequestId = savedInstanceState?.getString(STATE_CAPTURE_REQUEST_ID),
            createRequestId = { UUID.randomUUID().toString() },
        )
        saveStarted = savedInstanceState?.getBoolean(STATE_SAVE_STARTED) ?: false
        saveCompleted = savedInstanceState?.getBoolean(STATE_SAVE_COMPLETED) ?: false

        if (saveCompleted) {
            finish()
            return
        }
        launchSaveIfNeeded(intent)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString(STATE_CAPTURE_REQUEST_ID, captureRequestId)
        outState.putBoolean(STATE_SAVE_STARTED, saveStarted)
        outState.putBoolean(STATE_SAVE_COMPLETED, saveCompleted)
        super.onSaveInstanceState(outState)
    }

    private fun launchSaveIfNeeded(shareIntent: Intent?) {
        if (!ShareCaptureRequestPolicy.shouldLaunchSave(saveCompleted, saveLaunchedInCurrentInstance)) return
        saveLaunchedInCurrentInstance = true
        saveStarted = true

        val clip = ShareIntentParser.parse(
            context = this,
            intent = shareIntent,
            clipId = captureRequestId,
        )
        if (clip == null) {
            completeWithMessage("没有可保存的分享内容。", savedLocally = false)
            return
        }

        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                ShareCaptureSaveCoordinator.serialize {
                    CaptureSaveController(this@ShareCaptureActivity).save(
                        CaptureSaveRequest(
                            clip = clip,
                            origin = CaptureOrigin.ANDROID_SHARE,
                        ),
                    )
                }
            }
            completeWithMessage(
                message = if (result.savedLocally) {
                    "已保存"
                } else {
                    result.message.ifBlank { "本地保存失败，请重试。" }
                },
                savedLocally = result.savedLocally,
            )
        }
    }

    private fun completeWithMessage(message: String, savedLocally: Boolean) {
        saveCompleted = true
        Toast.makeText(
            this,
            message,
            if (savedLocally) Toast.LENGTH_SHORT else Toast.LENGTH_LONG,
        ).show()
        finish()
    }

    companion object {
        internal const val STATE_CAPTURE_REQUEST_ID = "share_capture_request_id"
        internal const val STATE_SAVE_STARTED = "share_capture_save_started"
        internal const val STATE_SAVE_COMPLETED = "share_capture_save_completed"
    }
}
