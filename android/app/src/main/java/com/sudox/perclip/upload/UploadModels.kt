package com.sudox.perclip.upload

import com.sudox.perclip.SharedClip
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipItem
import com.sudox.perclip.data.QueuedClipMetadata

data class UploadRecord(
    val clip: SharedClip,
    val status: UploadStatus,
    val message: String,
    val remotePath: String = "",
    val createdAtEpochMs: Long = 0L,
    val note: String = "",
    val metadata: QueuedClipMetadata = QueuedClipMetadata(),
    val uploadParts: List<UploadPart> = emptyList(),
)

enum class UploadStatus {
    Waiting,
    Uploading,
    Uploaded,
    Failed,
}

enum class UploadState {
    Waiting,
    Uploading,
    Uploaded,
    Failed,
}

data class UploadPart(
    val clientRequestId: String,
    val titleHint: String,
    val clientBatchId: String,
    val parentClientRequestId: String,
    val partIndex: Int,
    val partCount: Int,
    val partRole: String,
    val sourceIntent: String,
    val state: UploadState = UploadState.Waiting,
    val message: String = "",
)

data class UploadBatch(
    val clientBatchId: String,
    val parentClientRequestId: String,
    val partCount: Int,
    val parts: List<UploadPart>,
) {
    val state: UploadState
        get() = when {
            parts.isNotEmpty() && parts.all { it.state == UploadState.Uploaded } -> UploadState.Uploaded
            parts.any { it.state == UploadState.Failed } -> UploadState.Failed
            parts.any { it.state == UploadState.Uploading || it.state == UploadState.Uploaded } -> UploadState.Uploading
            else -> UploadState.Waiting
        }
}

data class UploadResult(
    val ok: Boolean,
    val title: String,
    val originalPath: String,
    val ragflowDocumentId: String,
    val duplicate: Boolean,
    val message: String = "",
    val retryable: Boolean = false,
    val archiveStatus: String = "",
)

object UploadFailurePolicy {
    fun isRetryableHttpStatus(code: Int): Boolean {
        return code == 408 || code == 409 || code == 429 || code in 500..599
    }
}

data class UploadPartFailureDisposition(
    val clientRequestId: String,
    val state: UploadState,
    val message: String,
)

data class UploadBatchFailureDisposition(
    val parts: List<UploadPartFailureDisposition>,
    val status: UploadStatus,
    val message: String,
    val shouldRetry: Boolean,
)

object UploadBatchFailurePolicy {
    fun evaluate(
        failures: List<Pair<UploadPart, UploadResult>>,
        runAttemptCount: Int,
        maxRetryAttempts: Int,
    ): UploadBatchFailureDisposition {
        require(failures.isNotEmpty())
        val evaluated = failures.map { (part, result) ->
            val disposition = UploadAttemptPolicy.forFailure(result, runAttemptCount, maxRetryAttempts)
            UploadPartFailureDisposition(
                clientRequestId = part.clientRequestId,
                state = if (disposition.shouldRetry) UploadState.Waiting else UploadState.Failed,
                message = result.message,
            ) to disposition
        }
        val retry = evaluated.firstOrNull { it.second.shouldRetry }?.second
        val aggregate = retry ?: evaluated.first().second
        return UploadBatchFailureDisposition(
            parts = evaluated.map { it.first },
            status = aggregate.status,
            message = aggregate.message,
            shouldRetry = retry != null,
        )
    }
}

object UploadPartAggregate {
    fun status(parts: List<UploadPart>): UploadStatus = when {
        parts.isNotEmpty() && parts.all { it.state == UploadState.Uploaded } -> UploadStatus.Uploaded
        parts.any { it.state == UploadState.Waiting || it.state == UploadState.Uploading } -> UploadStatus.Waiting
        parts.any { it.state == UploadState.Failed } -> UploadStatus.Failed
        else -> UploadStatus.Failed
    }
}

object UploadManualRetryPlanner {
    const val MISSING_PAYLOAD_MESSAGE = "本地缓存文件不可用，请从原 App 重新分享。"

    fun prepare(
        clip: QueuedClip,
        isCachedItemUsable: (QueuedClipItem) -> Boolean,
    ): QueuedClip {
        val parts = clip.uploadParts.map { part ->
            when (part.state) {
                UploadState.Uploaded -> part
                UploadState.Uploading -> part.copy(state = UploadState.Waiting, message = "")
                UploadState.Waiting -> part
                UploadState.Failed -> {
                    val needsFile = part.partRole in setOf("file", "image", "mixed")
                    val item = clip.items.getOrNull(part.partIndex)
                    if (!needsFile || (item != null && item.cachedPath.isNotBlank() && isCachedItemUsable(item))) {
                        part.copy(state = UploadState.Waiting, message = "")
                    } else {
                        part.copy(message = MISSING_PAYLOAD_MESSAGE)
                    }
                }
            }
        }
        val status = UploadPartAggregate.status(parts)
        return clip.copy(
            uploadParts = parts,
            status = status,
            message = if (status == UploadStatus.Failed) MISSING_PAYLOAD_MESSAGE else clip.message,
        )
    }
}

object UploadEnqueuePartPlanner {
    fun applyCacheResults(parts: List<UploadPart>, cachedPaths: List<String>): List<UploadPart> {
        require(parts.size == cachedPaths.size)
        return parts.mapIndexed { index, part ->
            if (cachedPaths[index].isBlank()) {
                part.copy(state = UploadState.Failed, message = UploadQueueEnqueueFailure.CACHE_READ_FAILED_MESSAGE)
            } else {
                part.copy(state = UploadState.Waiting, message = "")
            }
        }
    }
}
