package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipItem
import java.nio.file.Files
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadRetryEligibilityTest {
    @Test
    fun queuedTextFailureCanRetry() {
        assertTrue(UploadRetryEligibility.canRetry(queuedClip(items = emptyList())))
    }

    @Test
    fun queuedFileFailureCannotRetryWhenCachePathIsBlank() {
        assertFalse(
            UploadRetryEligibility.canRetry(
                queuedClip(
                    items = listOf(
                        QueuedClipItem(
                            cachedPath = "",
                            displayName = "report.pdf",
                            mimeType = "application/pdf",
                            sizeBytes = 1L,
                        ),
                    ),
                ),
            ),
        )
    }

    @Test
    fun queuedFileFailureCannotRetryWhenCacheFileIsMissing() {
        assertFalse(
            UploadRetryEligibility.canRetry(
                queuedClip(
                    items = listOf(
                        QueuedClipItem(
                            cachedPath = "/tmp/perclip-missing-payload.pdf",
                            displayName = "report.pdf",
                            mimeType = "application/pdf",
                            sizeBytes = 1L,
                        ),
                    ),
                ),
            ),
        )
    }

    @Test
    fun queuedFileFailureCanRetryWhenCacheFileExists() {
        val cached = Files.createTempFile("perclip-retry", ".pdf").toFile()
        try {
            assertTrue(
                UploadRetryEligibility.canRetry(
                    queuedClip(
                        items = listOf(
                            QueuedClipItem(
                                cachedPath = cached.absolutePath,
                                displayName = "report.pdf",
                                mimeType = "application/pdf",
                                sizeBytes = cached.length(),
                            ),
                        ),
                    ),
                ),
            )
        } finally {
            cached.delete()
        }
    }

    @Test
    fun textFailureCanRetryDespiteLegacyLocalReadMessage() {
        assertTrue(
            UploadRetryEligibility.canRetry(
                queuedClip(
                    message = UploadQueueEnqueueFailure.CACHE_READ_FAILED_MESSAGE,
                    items = emptyList(),
                ),
            ),
        )
        assertTrue(
            UploadRetryEligibility.canRetry(
                queuedClip(
                    message = CachedPayloadFiles.MISSING_FILE_MESSAGE,
                    items = emptyList(),
                ),
            ),
        )
    }

    @Test
    fun queuedWaitingClipCannotRetry() {
        assertFalse(
            UploadRetryEligibility.canRetry(
                queuedClip(status = UploadStatus.Waiting, items = emptyList()),
            ),
        )
    }

    @Test
    fun retryableCachedUriRequiresFileSchemeAndPath() {
        assertTrue(UploadRetryEligibility.hasRetryableCachedUri("file", "/tmp/report.pdf", fileExists = true))
        assertFalse(UploadRetryEligibility.hasRetryableCachedUri("content", "/tmp/report.pdf", fileExists = true))
        assertFalse(UploadRetryEligibility.hasRetryableCachedUri("file", "", fileExists = true))
        assertFalse(UploadRetryEligibility.hasRetryableCachedUri("file", "/tmp/report.pdf", fileExists = false))
        assertFalse(UploadRetryEligibility.hasRetryableCachedUri(null, "/tmp/report.pdf", fileExists = true))
    }

    private fun queuedClip(
        status: UploadStatus = UploadStatus.Failed,
        message: String = status.name,
        items: List<QueuedClipItem>,
    ): QueuedClip {
        return QueuedClip(
            id = "clip",
            kind = if (items.isEmpty()) ClipKind.Text else ClipKind.File,
            titleHint = "title",
            text = if (items.isEmpty()) "hello" else "",
            url = "",
            mimeType = "text/plain",
            sourceApp = "",
            note = "",
            items = items,
            status = status,
            message = message,
            remotePath = "",
            createdAtEpochMs = 1L,
        )
    }

}
