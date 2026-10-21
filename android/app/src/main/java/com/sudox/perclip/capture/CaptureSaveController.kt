package com.sudox.perclip.capture

import android.content.Context
import com.sudox.perclip.SharedClip
import com.sudox.perclip.config.PerClipSettingsStore
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipMetadata
import com.sudox.perclip.knowledge.KnowledgeBaseCacheScope
import com.sudox.perclip.knowledge.KnowledgeBaseLocalCache
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.upload.UploadQueue
import com.sudox.perclip.upload.UploadStatus

object CaptureRoutingMode {
    const val DEFAULT_ONLY = "default_only"
}

object CaptureSaveFailurePolicy {
    const val USER_MESSAGE = "本地保存失败，请重试。"

    fun userMessage(@Suppress("UNUSED_PARAMETER") error: Throwable): String = USER_MESSAGE
}

object CaptureMetadataPolicy {
    fun defaultOnly(defaultKnowledgeBase: KnowledgeBaseSummary?): QueuedClipMetadata {
        return QueuedClipMetadata(
            routingMode = CaptureRoutingMode.DEFAULT_ONLY,
            knowledgeBaseId = defaultKnowledgeBase?.id.orEmpty(),
            knowledgeBaseName = defaultKnowledgeBase?.displayName.orEmpty(),
            routingDecisionType = "default",
            routingReason = "default knowledge base at capture time",
            manualOverride = false,
        )
    }
}

data class CaptureSaveResult(
    val queuedClip: QueuedClip? = null,
    val message: String = "",
) {
    val savedLocally: Boolean
        get() = queuedClip != null && queuedClip.status != UploadStatus.Failed
}

enum class CaptureOrigin {
    IN_APP_FLASH,
    ANDROID_SHARE,
    CLIPBOARD_BRIDGE,
    SCREEN_CAPTURE,
}

data class CaptureSaveRequest(
    val clip: SharedClip,
    val note: String = "",
    val origin: CaptureOrigin,
)

class CaptureSaveController(
    context: Context,
    private val uploadQueue: UploadQueue = UploadQueue(context),
) {
    private val appContext = context.applicationContext
    private val settingsStore = PerClipSettingsStore(appContext)

    fun save(request: CaptureSaveRequest): CaptureSaveResult {
        return runCatching {
            val settings = settingsStore.load()
            val cachedKnowledgeBases = KnowledgeBaseLocalCache(
                appContext,
                KnowledgeBaseCacheScope.fromSettings(settings),
            ).load()
            val defaultKnowledgeBase = cachedKnowledgeBases.firstOrNull { it.isDefault }
            val queuedClip = uploadQueue.enqueue(
                clip = request.clip,
                note = request.note,
                metadata = CaptureMetadataPolicy.defaultOnly(defaultKnowledgeBase),
            )
            if (queuedClip.status == UploadStatus.Failed) {
                CaptureSaveResult(
                    queuedClip = queuedClip,
                    message = queuedClip.message.ifBlank { CaptureSaveFailurePolicy.USER_MESSAGE },
                )
            } else {
                CaptureSaveResult(queuedClip = queuedClip)
            }
        }.getOrElse { error ->
            CaptureSaveResult(message = CaptureSaveFailurePolicy.userMessage(error))
        }
    }
}
