package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipItem
import org.junit.Assert.assertEquals
import org.junit.Test

class UploadQueueRefreshTest {
    @Test
    fun refreshesWaitingLargeFileMessageWhenWifiPolicyChanges() {
        val clip = clip(
            status = UploadStatus.Waiting,
            message = "等待 Wi-Fi 后自动同步",
            sizeBytes = UploadNetworkPolicy.LARGE_FILE_THRESHOLD_BYTES + 1,
            statusUpdatedAtEpochMs = 1L,
        )

        val refreshed = UploadQueueRefresh.refreshWaitingMessages(
            clips = listOf(clip),
            wifiOnlyLargeFiles = false,
            nowEpochMs = 99L,
        ).single()

        assertEquals("等待网络后自动同步", refreshed.message)
        assertEquals(99L, refreshed.statusUpdatedAtEpochMs)
    }

    @Test
    fun refreshesWaitingMessageWhenUploadConfigBecomesAvailable() {
        val clip = clip(
            status = UploadStatus.Waiting,
            message = UploadNetworkPolicy.CONFIG_MISSING_MESSAGE,
            sizeBytes = 1L,
            statusUpdatedAtEpochMs = 1L,
        )

        val refreshed = UploadQueueRefresh.refreshWaitingMessages(
            clips = listOf(clip),
            wifiOnlyLargeFiles = true,
            uploadConfigured = true,
            nowEpochMs = 99L,
        ).single()

        assertEquals("等待网络后自动同步", refreshed.message)
        assertEquals(99L, refreshed.statusUpdatedAtEpochMs)
    }

    @Test
    fun refreshesWaitingMessageWhenUploadConfigIsMissing() {
        val clip = clip(
            status = UploadStatus.Waiting,
            message = "等待网络后自动同步",
            sizeBytes = 1L,
            statusUpdatedAtEpochMs = 1L,
        )

        val refreshed = UploadQueueRefresh.refreshWaitingMessages(
            clips = listOf(clip),
            wifiOnlyLargeFiles = true,
            uploadConfigured = false,
            nowEpochMs = 99L,
        ).single()

        assertEquals(UploadNetworkPolicy.CONFIG_MISSING_MESSAGE, refreshed.message)
        assertEquals(99L, refreshed.statusUpdatedAtEpochMs)
    }

    @Test
    fun leavesAlreadyMatchingWaitingMessageUntouched() {
        val clip = clip(
            status = UploadStatus.Waiting,
            message = "等待网络后自动同步",
            sizeBytes = 1L,
            statusUpdatedAtEpochMs = 1L,
        )

        val refreshed = UploadQueueRefresh.refreshWaitingMessages(
            clips = listOf(clip),
            wifiOnlyLargeFiles = true,
            nowEpochMs = 99L,
        ).single()

        assertEquals(clip, refreshed)
    }

    @Test
    fun doesNotRewriteNonWaitingRecords() {
        val uploaded = clip(
            status = UploadStatus.Uploaded,
            message = "已保存，后台处理完成。",
            sizeBytes = UploadNetworkPolicy.LARGE_FILE_THRESHOLD_BYTES + 1,
            statusUpdatedAtEpochMs = 1L,
        )
        val failed = clip(
            status = UploadStatus.Failed,
            message = "HTTP 401",
            sizeBytes = UploadNetworkPolicy.LARGE_FILE_THRESHOLD_BYTES + 1,
            statusUpdatedAtEpochMs = 2L,
        )

        val refreshed = UploadQueueRefresh.refreshWaitingMessages(
            clips = listOf(uploaded, failed),
            wifiOnlyLargeFiles = false,
            nowEpochMs = 99L,
        )

        assertEquals(listOf(uploaded, failed), refreshed)
    }

    @Test
    fun requeuesAllWaitingRecordsWhenUploadIsConfigured() {
        val waitingNetwork = clip(
            status = UploadStatus.Waiting,
            message = "等待网络后自动同步",
            sizeBytes = 1L,
            statusUpdatedAtEpochMs = 1L,
        )
        val waitingConfig = clip(
            status = UploadStatus.Waiting,
            message = UploadNetworkPolicy.CONFIG_MISSING_MESSAGE,
            sizeBytes = 2L,
            statusUpdatedAtEpochMs = 2L,
        )
        val uploaded = clip(
            status = UploadStatus.Uploaded,
            message = "已保存，后台处理完成。",
            sizeBytes = 3L,
            statusUpdatedAtEpochMs = 3L,
        )

        assertEquals(
            listOf(waitingNetwork, waitingConfig),
            UploadQueueRefresh.waitingClipsToRequeue(
                clips = listOf(waitingNetwork, uploaded, waitingConfig),
                uploadConfigured = true,
            ),
        )
    }

    @Test
    fun doesNotRequeueWaitingRecordsWhenUploadConfigIsMissing() {
        val waiting = clip(
            status = UploadStatus.Waiting,
            message = UploadNetworkPolicy.CONFIG_MISSING_MESSAGE,
            sizeBytes = 1L,
            statusUpdatedAtEpochMs = 1L,
        )

        assertEquals(
            emptyList<QueuedClip>(),
            UploadQueueRefresh.waitingClipsToRequeue(
                clips = listOf(waiting),
                uploadConfigured = false,
            ),
        )
    }

    private fun clip(
        status: UploadStatus,
        message: String,
        sizeBytes: Long,
        statusUpdatedAtEpochMs: Long,
    ): QueuedClip {
        return QueuedClip(
            id = "clip-$status",
            kind = ClipKind.File,
            titleHint = "demo.bin",
            text = "",
            url = "",
            mimeType = "application/octet-stream",
            sourceApp = "test",
            note = "",
            items = listOf(
                QueuedClipItem(
                    cachedPath = "/tmp/demo.bin",
                    displayName = "demo.bin",
                    mimeType = "application/octet-stream",
                    sizeBytes = sizeBytes,
                ),
            ),
            status = status,
            message = message,
            remotePath = "",
            createdAtEpochMs = 1L,
            statusUpdatedAtEpochMs = statusUpdatedAtEpochMs,
        )
    }
}
