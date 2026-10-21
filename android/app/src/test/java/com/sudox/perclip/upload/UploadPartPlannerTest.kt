package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class UploadPartPlannerTest {
    @Test
    fun keepsLegacyRequestIdForTextClip() {
        val metadata = UploadPartPlanner.forClip(baseClip())

        assertEquals("clip-1:", metadata.clientRequestId)
        assertEquals("Research note", metadata.titleHint)
        assertEquals("", metadata.clientBatchId)
        assertEquals("clip-1:", metadata.parentClientRequestId)
        assertEquals(0, metadata.partIndex)
        assertEquals(1, metadata.partCount)
        assertEquals("text", metadata.partRole)
    }

    @Test
    fun keepsLegacyRequestIdForSingleFile() {
        val metadata = UploadPartPlanner.forItem(
            clip = baseClip(kind = ClipKind.File),
            displayName = "report.pdf",
            itemIndex = 0,
            totalItems = 1,
        )

        assertEquals("clip-1:report.pdf", metadata.clientRequestId)
        assertEquals("Research note", metadata.titleHint)
    }

    @Test
    fun givesSameNameMultiFilePartsDistinctRequestIds() {
        val clip = baseClip(kind = ClipKind.Multiple)
        val first = UploadPartPlanner.forItem(
            clip = clip,
            displayName = "image.png",
            itemIndex = 0,
            totalItems = 2,
        )
        val second = UploadPartPlanner.forItem(
            clip = clip,
            displayName = "image.png",
            itemIndex = 1,
            totalItems = 2,
        )

        assertEquals("clip-1:0:image.png", first.clientRequestId)
        assertEquals("clip-1:1:image.png", second.clientRequestId)
        assertNotEquals(first.clientRequestId, second.clientRequestId)
        assertEquals("clip-1:", first.parentClientRequestId)
        assertEquals("clip-1", first.clientBatchId)
        assertEquals(2, second.partCount)
    }

    @Test
    fun sameFilenameAcrossBatchesDoesNotCollide() {
        val first = UploadPartPlanner.forItem(baseClip(id = "batch-a", kind = ClipKind.Multiple), "same.pdf", itemIndex = 0, totalItems = 2)
        val second = UploadPartPlanner.forItem(baseClip(id = "batch-b", kind = ClipKind.Multiple), "same.pdf", itemIndex = 0, totalItems = 2)

        assertNotEquals(first.clientRequestId, second.clientRequestId)
        assertNotEquals(first.clientBatchId, second.clientBatchId)
    }

    @Test
    fun retrySkipsUploadedPartsWithoutChangingRemainingIdentity() {
        val first = UploadPartPlanner.toUploadPart(
            UploadPartPlanner.forItem(baseClip(kind = ClipKind.Multiple), "a.pdf", itemIndex = 0, totalItems = 2),
        ).copy(state = UploadState.Uploaded)
        val second = UploadPartPlanner.toUploadPart(
            UploadPartPlanner.forItem(baseClip(kind = ClipKind.Multiple), "b.pdf", itemIndex = 1, totalItems = 2),
        )

        assertEquals(listOf(second), UploadPartPlanner.pendingParts(listOf(first, second)))
        assertEquals("clip-1:1:b.pdf", second.clientRequestId)
    }

    @Test
    fun mixedFailuresKeepRetryablePartWaitingRegardlessOfOrder() {
        val permanent = part("clip-1:0:a.pdf") to failedResult(retryable = false, message = "unauthorized")
        val retryable = part("clip-1:1:b.pdf") to failedResult(retryable = true, message = "unavailable")

        listOf(listOf(permanent, retryable), listOf(retryable, permanent)).forEach { failures ->
            val disposition = UploadBatchFailurePolicy.evaluate(failures, runAttemptCount = 0, maxRetryAttempts = 3)
            val states = disposition.parts.associate { it.clientRequestId to it.state }
            assertEquals(UploadState.Failed, states["clip-1:0:a.pdf"])
            assertEquals(UploadState.Waiting, states["clip-1:1:b.pdf"])
            assertEquals(true, disposition.shouldRetry)
            assertEquals(listOf(part("clip-1:1:b.pdf")), UploadPartPlanner.pendingParts(disposition.parts.map {
                part(it.clientRequestId).copy(state = it.state)
            }))
        }
    }

    @Test
    fun usesMimeFallbackAndManualSourceIntent() {
        val metadata = UploadPartPlanner.forItem(
            clip = baseClip(kind = ClipKind.Multiple, sourceApp = "PerClip"),
            displayName = "",
            mimeType = "image/png",
            itemIndex = 0,
            totalItems = 2,
        )

        assertEquals("clip-1:0:item", metadata.clientRequestId)
        assertEquals("image", metadata.partRole)
        assertEquals("manual", metadata.sourceIntent)
    }

    @Test
    fun rejectsMoreThanOneHundredParts() {
        assertThrows(IllegalArgumentException::class.java) {
            UploadPartPlanner.forItem(baseClip(kind = ClipKind.Multiple), "a.pdf", itemIndex = 0, totalItems = 101)
        }
    }

    @Test
    fun usesFileNameAsTitleForMultiFileParts() {
        val metadata = UploadPartPlanner.forItem(
            clip = baseClip(kind = ClipKind.Multiple),
            displayName = "brief.docx",
            itemIndex = 1,
            totalItems = 3,
        )

        assertEquals("brief.docx", metadata.titleHint)
    }

    @Test
    fun sanitizesMultipartRequestIdFilenameWithoutChangingPartIndex() {
        val metadata = UploadPartPlanner.forItem(
            clip = baseClip(kind = ClipKind.Multiple), displayName = "../../中文 report?.pdf",
            itemIndex = 0, totalItems = 2,
        )

        assertEquals("clip-1:0:report_.pdf", metadata.clientRequestId)
        assertEquals("file", metadata.partRole)
    }

    private fun baseClip(
        id: String = "clip-1",
        kind: ClipKind = ClipKind.Text,
        sourceApp: String = "",
    ): SharedClip {
        return SharedClip(
            id = id,
            kind = kind,
            titleHint = "Research note",
            text = "hello",
            sourceApp = sourceApp,
        )
    }

    private fun part(id: String) = UploadPart(
        clientRequestId = id,
        titleHint = id,
        clientBatchId = "clip-1",
        parentClientRequestId = "clip-1:",
        partIndex = if (id.contains(":0:")) 0 else 1,
        partCount = 2,
        partRole = "file",
        sourceIntent = "share",
    )

    private fun failedResult(retryable: Boolean, message: String) = UploadResult(
        ok = false,
        title = "",
        originalPath = "",
        ragflowDocumentId = "",
        duplicate = false,
        message = message,
        retryable = retryable,
    )
}
