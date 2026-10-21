package com.sudox.perclip.upload

import androidx.work.NetworkType
import com.sudox.perclip.ClipKind
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipItem
import org.junit.Assert.assertEquals
import org.junit.Test

class UploadNetworkPolicyTest {
    @Test
    fun usesConnectedNetworkForTextClips() {
        assertEquals(
            NetworkType.CONNECTED,
            UploadNetworkPolicy.requiredNetworkType(textClip(), wifiOnlyLargeFiles = true),
        )
    }

    @Test
    fun usesUnmeteredNetworkForLargeFilesWhenEnabled() {
        assertEquals(
            NetworkType.UNMETERED,
            UploadNetworkPolicy.requiredNetworkType(
                fileClip(sizeBytes = UploadNetworkPolicy.LARGE_FILE_THRESHOLD_BYTES),
                wifiOnlyLargeFiles = true,
            ),
        )
    }

    @Test
    fun usesConnectedNetworkForLargeFilesWhenDisabled() {
        assertEquals(
            NetworkType.CONNECTED,
            UploadNetworkPolicy.requiredNetworkType(
                fileClip(sizeBytes = UploadNetworkPolicy.LARGE_FILE_THRESHOLD_BYTES * 2),
                wifiOnlyLargeFiles = false,
            ),
        )
    }

    @Test
    fun describesWaitingForWifiWhenLargeFilePolicyApplies() {
        assertEquals(
            "等待 Wi-Fi 后自动同步",
            UploadNetworkPolicy.describeWaitingState(
                fileClip(sizeBytes = UploadNetworkPolicy.LARGE_FILE_THRESHOLD_BYTES + 1),
                wifiOnlyLargeFiles = true,
            ),
        )
    }

    @Test
    fun describesWaitingForNetworkForSmallClips() {
        assertEquals(
            "等待网络后自动同步",
            UploadNetworkPolicy.describeWaitingState(textClip(), wifiOnlyLargeFiles = true),
        )
    }

    @Test
    fun describesWaitingForConfigurationBeforeNetworkPolicy() {
        assertEquals(
            UploadNetworkPolicy.CONFIG_MISSING_MESSAGE,
            UploadNetworkPolicy.describeWaitingState(
                fileClip(sizeBytes = UploadNetworkPolicy.LARGE_FILE_THRESHOLD_BYTES + 1),
                wifiOnlyLargeFiles = true,
                uploadConfigured = false,
            ),
        )
    }

    private fun textClip(): QueuedClip = baseClip(items = emptyList())

    private fun fileClip(sizeBytes: Long): QueuedClip = baseClip(
        kind = ClipKind.File,
        items = listOf(
            QueuedClipItem(
                cachedPath = "/tmp/file.bin",
                displayName = "file.bin",
                mimeType = "application/octet-stream",
                sizeBytes = sizeBytes,
            ),
        ),
    )

    private fun baseClip(
        kind: ClipKind = ClipKind.Text,
        items: List<QueuedClipItem>,
    ): QueuedClip {
        return QueuedClip(
            id = "clip-1",
            kind = kind,
            titleHint = "clip",
            text = "hello",
            url = "",
            mimeType = "text/plain",
            sourceApp = "test",
            note = "",
            items = items,
            status = UploadStatus.Waiting,
            message = "",
            remotePath = "",
            createdAtEpochMs = 1L,
        )
    }
}
