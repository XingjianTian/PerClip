package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipItem
import java.nio.file.Files
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadQueueStatePolicyTest {
    @Test
    fun firstQueueInANewProcessRecoversInterruptedUploadsImmediately() {
        assertEquals(0L, UploadProcessRecoveryPolicy.staleAfterMs(firstQueueInProcess = true))
        assertEquals(
            com.sudox.perclip.data.ClipQueueStore.STALE_UPLOADING_AFTER_MS,
            UploadProcessRecoveryPolicy.staleAfterMs(firstQueueInProcess = false),
        )
    }

    @Test
    fun manualRetryRestoresOnlyFailedPartsWithUsablePayloads() {
        val cached = Files.createTempFile("perclip-manual-retry", ".pdf").toFile()
        try {
            val clip = queuedClip(
                items = listOf(item(cached.absolutePath, "a.pdf"), item("", "b.pdf")),
                parts = listOf(part(0, "a.pdf", UploadState.Failed), part(1, "b.pdf", UploadState.Failed)),
            )

            val prepared = UploadManualRetryPlanner.prepare(clip) { it.cachedPath == cached.absolutePath }

            assertEquals(UploadState.Waiting, prepared.uploadParts[0].state)
            assertEquals(UploadState.Failed, prepared.uploadParts[1].state)
            assertEquals(UploadManualRetryPlanner.MISSING_PAYLOAD_MESSAGE, prepared.uploadParts[1].message)
            assertEquals(listOf("parent:0:a.pdf"), UploadPartPlanner.pendingParts(prepared.uploadParts).map { it.clientRequestId })
            assertEquals(UploadStatus.Waiting, prepared.status)
        } finally {
            cached.delete()
        }
    }

    @Test
    fun manualRetryKeepsUploadedPartsAndFrozenCaptureProvenance() {
        val clip = queuedClip(
            items = emptyList(),
            parts = listOf(part(0, "text", UploadState.Uploaded, role = "text")),
        ).copy(capturedAtEpochMs = 1_700_000_000_000L, capturedTimezone = "Asia/Shanghai")

        val prepared = UploadManualRetryPlanner.prepare(clip) { false }

        assertEquals(UploadState.Uploaded, prepared.uploadParts.single().state)
        assertEquals(emptyList<UploadPart>(), UploadPartPlanner.pendingParts(prepared.uploadParts))
        assertEquals(UploadStatus.Uploaded, UploadPartAggregate.status(prepared.uploadParts))
        assertEquals(clip.capturedAtEpochMs, prepared.capturedAtEpochMs)
        assertEquals(clip.capturedTimezone, prepared.capturedTimezone)
    }

    @Test
    fun failedPartWithoutCacheCannotBecomePendingOrUploaded() {
        val clip = queuedClip(
            items = listOf(item("", "missing.pdf")),
            parts = listOf(part(0, "missing.pdf", UploadState.Failed)),
        )

        val prepared = UploadManualRetryPlanner.prepare(clip) { false }

        assertEquals(emptyList<UploadPart>(), UploadPartPlanner.pendingParts(prepared.uploadParts))
        assertEquals(UploadStatus.Failed, UploadPartAggregate.status(prepared.uploadParts))
    }

    @Test
    fun staleUploadingPartReturnsToWaiting() {
        val clip = queuedClip(
            items = listOf(item("/tmp/a.pdf", "a.pdf")),
            parts = listOf(part(0, "a.pdf", UploadState.Uploading)),
        ).copy(status = UploadStatus.Uploading, statusUpdatedAtEpochMs = 1L)

        val recovered = com.sudox.perclip.data.UploadQueueRecovery.recoverStaleUploading(
            listOf(clip),
            nowEpochMs = 1_000L,
            staleAfterMs = 100L,
        ).single()

        assertEquals(UploadStatus.Waiting, recovered.status)
        assertEquals(UploadState.Waiting, recovered.uploadParts.single().state)
    }

    @Test
    fun partialCacheFailureKeepsStableIndicesAndOtherPartsWaiting() {
        val planned = listOf(
            part(0, "same.pdf", UploadState.Waiting),
            part(1, "same.pdf", UploadState.Waiting),
            part(2, "same.pdf", UploadState.Waiting),
        )
        listOf(
            listOf("", "/cache/1", "/cache/2") to listOf(0),
            listOf("/cache/0", "", "/cache/2") to listOf(1),
            listOf("/cache/0", "/cache/1", "") to listOf(2),
        ).forEach { (paths, failedIndices) ->
            val parts = UploadEnqueuePartPlanner.applyCacheResults(planned, paths)
            assertEquals(listOf(0, 1, 2), parts.map { it.partIndex })
            assertEquals(3, parts.map { it.partCount }.distinct().single())
            assertEquals(failedIndices, parts.filter { it.state == UploadState.Failed }.map { it.partIndex })
            assertEquals(2, parts.count { it.state == UploadState.Waiting })
            assertEquals(3, parts.map { it.clientRequestId }.distinct().size)
        }
    }

    @Test
    fun allCacheFailuresRemainFailedWithoutPendingParts() {
        val planned = listOf(
            part(0, "a.pdf", UploadState.Waiting),
            part(1, "b.pdf", UploadState.Waiting),
            part(2, "c.pdf", UploadState.Waiting),
        )

        val parts = UploadEnqueuePartPlanner.applyCacheResults(planned, listOf("", "", ""))

        assertTrue(parts.all { it.state == UploadState.Failed })
        assertEquals(emptyList<UploadPart>(), UploadPartPlanner.pendingParts(parts))
        assertEquals(UploadStatus.Failed, UploadPartAggregate.status(parts))
    }

    private fun queuedClip(items: List<QueuedClipItem>, parts: List<UploadPart>) = QueuedClip(
        id = "parent",
        kind = if (items.isEmpty()) ClipKind.Text else ClipKind.Multiple,
        titleHint = "capture",
        text = if (items.isEmpty()) "text" else "",
        url = "",
        mimeType = "",
        sourceApp = "share",
        note = "",
        items = items,
        status = UploadStatus.Failed,
        message = "failed",
        remotePath = "",
        createdAtEpochMs = 10L,
        uploadParts = parts,
    )

    private fun item(path: String, name: String) = QueuedClipItem(path, name, "application/pdf", 1L)

    private fun part(index: Int, name: String, state: UploadState, role: String = "file") = UploadPart(
        clientRequestId = "parent:$index:$name",
        titleHint = name,
        clientBatchId = "parent",
        parentClientRequestId = "parent:",
        partIndex = index,
        partCount = 3,
        partRole = role,
        sourceIntent = "share",
        state = state,
    )
}
