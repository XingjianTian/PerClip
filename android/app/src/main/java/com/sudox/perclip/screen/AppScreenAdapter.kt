package com.sudox.perclip.screen

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.view.accessibility.AccessibilityNodeInfo

interface AppScreenAdapter {
    fun canHandle(packageName: String): Boolean

    fun capture(
        request: AppScreenCaptureRequest,
        onResult: (AutoCaptureResult) -> Unit,
    )
}

data class AppScreenCaptureRequest(
    val service: AccessibilityService,
    val handler: Handler,
    val root: AccessibilityNodeInfo,
    val snapshot: ScreenClipSnapshot,
    val startedAtEpochMs: Long = System.currentTimeMillis(),
)

sealed class AutoCaptureResult {
    data class Success(val snapshot: ScreenClipSnapshot) : AutoCaptureResult()
    data class Fallback(val snapshot: ScreenClipSnapshot?, val reason: String) : AutoCaptureResult()
}
