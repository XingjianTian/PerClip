package com.sudox.perclip.upload

import com.sudox.perclip.data.QueuedClip

object UploadQueueRefresh {
    fun refreshWaitingMessages(
        clips: List<QueuedClip>,
        wifiOnlyLargeFiles: Boolean,
        uploadConfigured: Boolean = true,
        nowEpochMs: Long,
    ): List<QueuedClip> {
        return clips.map { clip ->
            if (clip.status != UploadStatus.Waiting) {
                clip
            } else {
                val message = UploadNetworkPolicy.describeWaitingState(
                    clip = clip,
                    wifiOnlyLargeFiles = wifiOnlyLargeFiles,
                    uploadConfigured = uploadConfigured,
                )
                if (clip.message == message) {
                    clip
                } else {
                    clip.copy(
                        message = message,
                        statusUpdatedAtEpochMs = nowEpochMs,
                    )
                }
            }
        }
    }

    fun waitingClipsToRequeue(
        clips: List<QueuedClip>,
        uploadConfigured: Boolean,
    ): List<QueuedClip> {
        if (!uploadConfigured) return emptyList()
        return clips.filter { clip -> clip.status == UploadStatus.Waiting }
    }
}
