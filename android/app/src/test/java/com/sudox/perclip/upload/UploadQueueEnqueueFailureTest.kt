package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadQueueEnqueueFailureTest {
    @Test
    fun failedCacheReadClipStoresFailedStatusAndNormalizedNote() {
        val clip = SharedClip(
            id = "clip-1",
            kind = ClipKind.File,
            titleHint = "合同",
            mimeType = "application/pdf",
            sourceApp = "Files",
        )

        val failed = UploadQueueEnqueueFailure.failedCacheReadClip(
            clip = clip,
            note = "  important  ",
            nowEpochMs = 123L,
        )

        assertEquals(UploadStatus.Failed, failed.status)
        assertEquals(UploadQueueEnqueueFailure.CACHE_READ_FAILED_MESSAGE, failed.message)
        assertEquals("important", failed.note)
        assertEquals(123L, failed.createdAtEpochMs)
        assertEquals(123L, failed.statusUpdatedAtEpochMs)
    }

    @Test
    fun failedCacheReadItemPreservesMetadataWithoutCachedPath() {
        val item = UploadQueueEnqueueFailure.failedCacheReadItem(
            displayName = "report.pdf",
            mimeType = "application/pdf",
            sizeBytes = 42L,
        )

        assertEquals("report.pdf", item.displayName)
        assertEquals("application/pdf", item.mimeType)
        assertEquals(42L, item.sizeBytes)
        assertTrue(item.cachedPath.isBlank())
    }
}
