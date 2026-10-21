package com.sudox.perclip.upload

import com.sudox.perclip.SharedClip
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipItem
import com.sudox.perclip.data.QueuedClipMetadata

object UploadQueueEnqueueFailure {
    const val CACHE_READ_FAILED_MESSAGE = "无法读取分享文件，请从原 App 重新分享。"
    const val TOO_MANY_ITEMS_MESSAGE = "单次最多分享 100 个项目，请分批重试。"

    fun failedTooManyItemsClip(
        clip: SharedClip,
        note: String,
        nowEpochMs: Long,
        metadata: QueuedClipMetadata = QueuedClipMetadata(),
    ): QueuedClip = failedCacheReadClip(clip, note, nowEpochMs, metadata).copy(
        items = emptyList(),
        message = TOO_MANY_ITEMS_MESSAGE,
    )

    fun failedCacheReadClip(
        clip: SharedClip,
        note: String,
        nowEpochMs: Long,
        metadata: QueuedClipMetadata = QueuedClipMetadata(),
    ): QueuedClip {
        return QueuedClip(
            id = clip.id,
            kind = clip.kind,
            titleHint = clip.titleHint,
            text = clip.text,
            url = clip.url,
            mimeType = clip.mimeType,
            sourceApp = clip.sourceApp,
            note = ClipNoteSanitizer.normalize(note),
            items = clip.items.map { item ->
                failedCacheReadItem(
                    displayName = item.displayName,
                    mimeType = item.mimeType,
                    sizeBytes = item.sizeBytes,
                )
            },
            status = UploadStatus.Failed,
            message = CACHE_READ_FAILED_MESSAGE,
            remotePath = "",
            createdAtEpochMs = nowEpochMs,
            statusUpdatedAtEpochMs = nowEpochMs,
            metadata = metadata,
        )
    }

    fun failedCacheReadItem(
        displayName: String,
        mimeType: String,
        sizeBytes: Long?,
    ): QueuedClipItem {
        return QueuedClipItem(
            cachedPath = "",
            displayName = displayName,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
        )
    }
}
