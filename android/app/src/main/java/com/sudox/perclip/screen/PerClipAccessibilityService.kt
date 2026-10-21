package com.sudox.perclip.screen

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import com.sudox.perclip.ClipboardBridgeActivity
import com.sudox.perclip.PerClipActions
import com.sudox.perclip.capture.CaptureOrigin
import com.sudox.perclip.capture.CaptureSaveController
import com.sudox.perclip.capture.CaptureSaveRequest
import java.lang.ref.WeakReference
import java.util.concurrent.Executors

class PerClipAccessibilityService : AccessibilityService() {
    private val store by lazy { ScreenClipStore(this) }
    private val saveController by lazy { CaptureSaveController(this) }
    private val handler = Handler(Looper.getMainLooper())
    private val saveExecutor = Executors.newSingleThreadExecutor()
    private val captureGate = TriggeredCaptureGate()

    override fun onServiceConnected() {
        super.onServiceConnected()
        activeService = WeakReference(this)
        Log.i(TAG, "accessibility service connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        if (activeService?.get() === this) {
            activeService = null
        }
        handler.removeCallbacksAndMessages(null)
        saveExecutor.shutdownNow()
        super.onDestroy()
    }

    fun requestTriggeredCapture(): Boolean {
        if (!captureGate.tryStart()) return false
        Log.i(TAG, "triggered capture scheduled")
        val delayMs = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            performGlobalAction(GLOBAL_ACTION_DISMISS_NOTIFICATION_SHADE)
            DISMISS_NOTIFICATION_SHADE_DELAY_MS
        } else {
            INITIAL_CAPTURE_DELAY_MS
        }
        handler.postDelayed({ performTriggeredCapture(attempt = 0) }, delayMs)
        return true
    }

    private fun performTriggeredCapture(attempt: Int) {
        val root = rootInActiveWindow
        val packageName = root?.packageName?.toString().orEmpty()
        Log.i(TAG, "trigger attempt=$attempt rootPackage=$packageName rootNull=${root == null}")
        if (root == null || shouldIgnorePackage(packageName)) {
            if (attempt < ACTIVE_WINDOW_RETRY_COUNT) {
                handler.postDelayed({ performTriggeredCapture(attempt + 1) }, ACTIVE_WINDOW_RETRY_DELAY_MS)
            } else {
                finishWithoutSaving("还没有可读取的当前屏幕内容")
            }
            return
        }

        val now = System.currentTimeMillis()
        val snapshot = ScreenClipBuilder.buildSnapshot(
            packageName = packageName,
            appLabel = appLabelFor(packageName),
            rawTexts = AccessibilityNodeTextExtractor.extract(root),
            capturedAtEpochMs = now,
        )
        if (snapshot == null) {
            finishWithoutSaving("当前屏幕没有可读取文字")
            return
        }

        val adapter = ScreenCaptureAdapterRegistry.adapterFor(packageName)
        Log.i(TAG, "snapshot built package=$packageName adapter=${adapter?.javaClass?.simpleName.orEmpty()}")
        if (adapter == null) {
            saveSnapshot(snapshot)
            return
        }

        adapter.capture(
            request = AppScreenCaptureRequest(
                service = this,
                handler = handler,
                root = root,
                snapshot = snapshot,
                startedAtEpochMs = now,
            ),
            onResult = ::handleAutoCaptureResult,
        )
    }

    private fun handleAutoCaptureResult(result: AutoCaptureResult) {
        when (result) {
            is AutoCaptureResult.Success -> {
                if (!markTriggeredCaptureCompleted()) return
                Log.i(TAG, "auto capture success; launching clipboard completion")
                store.savePendingAutoCapture(result.snapshot)
                releaseTriggeredCaptureSoon()
                startActivity(
                    Intent(this, ClipboardBridgeActivity::class.java)
                        .setAction(PerClipActions.ACTION_COMPLETE_AUTO_CAPTURE)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                )
            }
            is AutoCaptureResult.Fallback -> {
                Log.i(TAG, "auto capture fallback")
                val snapshot = result.snapshot
                if (snapshot == null) {
                    finishWithoutSaving(result.reason.ifBlank { "当前屏幕没有可读取文字" })
                } else {
                    saveSnapshot(snapshot)
                }
            }
        }
    }

    private fun saveSnapshot(snapshot: ScreenClipSnapshot) {
        if (!markTriggeredCaptureCompleted()) return
        saveExecutor.execute {
            val result = saveController.save(
                CaptureSaveRequest(
                    clip = ScreenClipBuilder.toSharedClip(snapshot),
                    origin = CaptureOrigin.SCREEN_CAPTURE,
                ),
            )
            handler.post {
                val message = if (result.savedLocally) {
                    "已保存当前屏幕。"
                } else {
                    result.message.ifBlank { "本地保存失败，请重试。" }
                }
                android.widget.Toast.makeText(
                    this,
                    message,
                    if (result.savedLocally) android.widget.Toast.LENGTH_SHORT else android.widget.Toast.LENGTH_LONG,
                ).show()
                releaseTriggeredCaptureSoon()
            }
        }
    }

    private fun finishWithoutSaving(message: String) {
        if (!markTriggeredCaptureCompleted()) return
        android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_LONG).show()
        releaseTriggeredCaptureSoon()
    }

    private fun markTriggeredCaptureCompleted(): Boolean {
        return captureGate.tryComplete()
    }

    private fun releaseTriggeredCaptureSoon() {
        handler.postDelayed({
            captureGate.release()
        }, RELEASE_CAPTURE_DELAY_MS)
    }

    private fun appLabelFor(packageName: String): String {
        if (packageName.isBlank()) return ""
        return runCatching {
            val applicationInfo = packageManager.getApplicationInfo(packageName, 0)
            packageManager.getApplicationLabel(applicationInfo).toString()
        }.getOrElse { packageName }
    }

    private fun shouldIgnorePackage(packageName: String): Boolean {
        return packageName.isBlank() ||
            packageName == applicationContext.packageName ||
            packageName in IGNORED_PACKAGES ||
            packageName.startsWith("com.android.permissioncontroller")
    }

    companion object {
        private const val TAG = "PerClipCapture"
        private const val INITIAL_CAPTURE_DELAY_MS = 450L
        private const val DISMISS_NOTIFICATION_SHADE_DELAY_MS = 1_250L
        private const val ACTIVE_WINDOW_RETRY_DELAY_MS = 250L
        private const val ACTIVE_WINDOW_RETRY_COUNT = 6
        private const val RELEASE_CAPTURE_DELAY_MS = 1_500L
        private val IGNORED_PACKAGES = setOf(
            "com.android.systemui",
            "com.coloros.systemui",
            "com.oplus.notificationmanager",
            "com.oplus.safecenter",
            "com.coloros.safecenter",
            "com.android.settings",
            "li.songe.gkd",
        )

        private var activeService: WeakReference<PerClipAccessibilityService>? = null

        fun requestTriggeredCapture(): Boolean {
            val service = activeService?.get() ?: return false
            service.requestTriggeredCapture()
            return true
        }
    }
}
