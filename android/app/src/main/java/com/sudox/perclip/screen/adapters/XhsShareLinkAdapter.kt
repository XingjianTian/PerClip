package com.sudox.perclip.screen.adapters

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import com.sudox.perclip.screen.AccessibilityNodeTools
import com.sudox.perclip.screen.AppScreenAdapter
import com.sudox.perclip.screen.AppScreenCaptureRequest
import com.sudox.perclip.screen.AutoCaptureResult

class XhsShareLinkAdapter : AppScreenAdapter {
    override fun canHandle(packageName: String): Boolean = packageName == XHS_PACKAGE

    override fun capture(
        request: AppScreenCaptureRequest,
        onResult: (AutoCaptureResult) -> Unit,
    ) {
        val shareNode = findShareClickTarget(request.root)
        if (shareNode == null) {
            onResult(AutoCaptureResult.Fallback(request.snapshot, "当前小红书页面未找到分享入口"))
            return
        }

        val dispatched =
            run {
            Log.i(TAG, "tapping share target ${shareNode.boundsForLog()}")
            tapNode(
                service = request.service,
                node = shareNode,
            )
        }
        if (!dispatched) {
            onResult(AutoCaptureResult.Fallback(request.snapshot, "无法点击小红书分享按钮"))
        } else {
            request.handler.postDelayed({
                pollCopyLinkButton(request, onResult)
            }, AFTER_TAP_SETTLE_MS)
        }
    }

    private fun pollCopyLinkButton(
        request: AppScreenCaptureRequest,
        onResult: (AutoCaptureResult) -> Unit,
    ) {
        fun poll() {
            val elapsed = System.currentTimeMillis() - request.startedAtEpochMs
            if (elapsed > CAPTURE_TIMEOUT_MS) {
                onResult(AutoCaptureResult.Fallback(request.snapshot, "未找到复制链接入口"))
                return
            }

            val copyNode = findCopyLinkClickTarget(request)
            if (copyNode != null) {
                Log.i(TAG, "tapping copy link target ${copyNode.boundsForLog()}")
                val dispatched = tapNode(
                    service = request.service,
                    node = copyNode,
                )
                if (!dispatched) {
                    onResult(AutoCaptureResult.Fallback(request.snapshot, "无法点击复制链接"))
                } else {
                    request.handler.postDelayed({
                        onResult(AutoCaptureResult.Success(request.snapshot))
                    }, CLIPBOARD_SETTLE_MS)
                }
                return
            }

            if (elapsed + POLL_INTERVAL_MS > CAPTURE_TIMEOUT_MS) {
                Log.i(TAG, "copy link target not found; roots=${copySearchRoots(request).size}")
            }
            request.handler.postDelayed(::poll, POLL_INTERVAL_MS)
        }

        request.handler.postDelayed(::poll, POLL_INTERVAL_MS)
    }

    private fun findShareClickTarget(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        return AccessibilityNodeTools.allNodes(root)
            .mapNotNull { node ->
                val score = XhsNodeMatcher.shareScore(AccessibilityNodeTools.candidateFor(node, root))
                val tapTarget = when {
                    node.isToolbarSizedTapTarget() -> node
                    else -> AccessibilityNodeTools.nearestClickable(node)
                        ?.takeIf { it.isToolbarSizedTapTarget() }
                }
                if (score == null || tapTarget == null) {
                    null
                } else {
                    tapTarget to score
                }
            }
            .maxByOrNull { it.second }
            ?.first
    }

    private fun findCopyLinkClickTarget(request: AppScreenCaptureRequest): AccessibilityNodeInfo? {
        return copySearchRoots(request).firstNotNullOfOrNull { root ->
            AccessibilityNodeTools.allNodes(root, maxNodes = COPY_SEARCH_MAX_NODES)
                .firstNotNullOfOrNull { node ->
                    val candidate = AccessibilityNodeTools.candidateFor(node, root)
                    if (!XhsNodeMatcher.isCopyLinkButton(candidate)) {
                        null
                    } else {
                        AccessibilityNodeTools.nearestClickable(node) ?: node
                    }
                }
        }
    }

    private fun copySearchRoots(request: AppScreenCaptureRequest): List<AccessibilityNodeInfo> {
        val roots = mutableListOf<AccessibilityNodeInfo>()
        request.service.windows
            .mapNotNullTo(roots) { it.root }
        request.service.rootInActiveWindow?.let(roots::add)
        return roots.distinctBy { System.identityHashCode(it) }
    }

    private fun AccessibilityNodeInfo.boundsForLog(): String {
        val rect = Rect()
        getBoundsInScreen(rect)
        return "[${rect.left},${rect.top}][${rect.right},${rect.bottom}]"
    }

    private fun AccessibilityNodeInfo.isToolbarSizedTapTarget(): Boolean {
        val rect = Rect()
        getBoundsInScreen(rect)
        val width = rect.width()
        val height = rect.height()
        return width in 32..260 && height in 32..260
    }

    private fun tapNode(
        service: AccessibilityService,
        node: AccessibilityNodeInfo,
    ): Boolean {
        val rect = Rect()
        node.getBoundsInScreen(rect)
        if (rect.isEmpty) return false
        return service.dispatchGesture(
            tapGesture(rect.exactCenterX(), rect.exactCenterY()),
            object : AccessibilityService.GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) {
                    super.onCompleted(gestureDescription)
                    Log.i(TAG, "tap gesture completed")
                }

                override fun onCancelled(gestureDescription: GestureDescription?) {
                    super.onCancelled(gestureDescription)
                    Log.i(TAG, "tap gesture cancelled")
                }
            },
            null,
        )
    }

    private fun tapGesture(x: Float, y: Float): GestureDescription {
        val path = Path().apply {
            moveTo(x, y)
        }
        return GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0L, TAP_DURATION_MS))
            .build()
    }

    companion object {
        const val XHS_PACKAGE = "com.xingin.xhs"
        private const val TAG = "PerClipCapture"
        private const val CAPTURE_TIMEOUT_MS = 8_000L
        private const val POLL_INTERVAL_MS = 450L
        private const val AFTER_TAP_SETTLE_MS = 350L
        private const val CLIPBOARD_SETTLE_MS = 1_500L
        private const val COPY_SEARCH_MAX_NODES = 3_500
        private const val TAP_DURATION_MS = 80L
    }
}
