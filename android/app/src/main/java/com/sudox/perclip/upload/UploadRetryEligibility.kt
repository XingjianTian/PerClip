package com.sudox.perclip.upload

import com.sudox.perclip.data.QueuedClip
import java.io.File

object UploadRetryEligibility {
    fun canRetry(clip: QueuedClip): Boolean {
        if (clip.status != UploadStatus.Failed) return false
        if (clip.message == UploadQueueEnqueueFailure.TOO_MANY_ITEMS_MESSAGE) return false
        if (clip.uploadParts.isNotEmpty()) {
            return UploadManualRetryPlanner.prepare(clip) { item -> File(item.cachedPath).isFile }
                .uploadParts.any { it.state == UploadState.Waiting }
        }
        if (clip.items.isEmpty()) return true
        return clip.items.any { item -> hasRetryableCachedFile(item.cachedPath, File(item.cachedPath).isFile) }
    }

    fun canRetry(record: UploadRecord): Boolean {
        if (record.status != UploadStatus.Failed) return false
        if (record.message == UploadQueueEnqueueFailure.TOO_MANY_ITEMS_MESSAGE) return false
        if (record.uploadParts.isNotEmpty()) {
            return record.uploadParts.any { part ->
                if (part.state != UploadState.Failed && part.state != UploadState.Uploading) return@any false
                if (part.state == UploadState.Uploading || part.partRole !in setOf("file", "image", "mixed")) return@any true
                val item = record.clip.items.getOrNull(part.partIndex) ?: return@any false
                hasRetryableCachedUri(
                    scheme = item.uri.scheme,
                    path = item.uri.path,
                    fileExists = item.uri.path?.let { path -> File(path).isFile } == true,
                )
            }
        }
        if (record.clip.items.isEmpty()) return true
        return record.clip.items.any { item ->
            hasRetryableCachedUri(
                scheme = item.uri.scheme,
                path = item.uri.path,
                fileExists = item.uri.path?.let { path -> File(path).isFile } == true,
            )
        }
    }

    fun hasRetryableCachedUri(scheme: String?, path: String?, fileExists: Boolean): Boolean {
        return scheme == "file" && hasRetryableCachedFile(path, fileExists)
    }

    fun hasRetryableCachedFile(path: String?, fileExists: Boolean): Boolean {
        return path?.isNotBlank() == true && fileExists
    }

}
