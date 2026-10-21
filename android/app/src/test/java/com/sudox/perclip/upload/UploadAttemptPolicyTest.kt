package com.sudox.perclip.upload

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadAttemptPolicyTest {
    @Test
    fun retryableFailureStaysWaitingBeforeRetryLimit() {
        val disposition = UploadAttemptPolicy.forFailure(
            result = failedResult(message = "HTTP 503", retryable = true),
            runAttemptCount = 1,
            maxRetryAttempts = 3,
        )

        assertEquals(UploadStatus.Waiting, disposition.status)
        assertEquals("HTTP 503，等待自动重试。", disposition.message)
        assertTrue(disposition.shouldRetry)
        assertFalse(disposition.shouldNotifyFailure)
    }

    @Test
    fun retryableFailureBecomesFinalFailureAtRetryLimit() {
        val disposition = UploadAttemptPolicy.forFailure(
            result = failedResult(message = "HTTP 503", retryable = true),
            runAttemptCount = 3,
            maxRetryAttempts = 3,
        )

        assertEquals(UploadStatus.Failed, disposition.status)
        assertEquals("HTTP 503", disposition.message)
        assertFalse(disposition.shouldRetry)
        assertTrue(disposition.shouldNotifyFailure)
    }

    @Test
    fun nonRetryableFailureFailsImmediately() {
        val disposition = UploadAttemptPolicy.forFailure(
            result = failedResult(message = "HTTP 401", retryable = false),
            runAttemptCount = 0,
            maxRetryAttempts = 3,
        )

        assertEquals(UploadStatus.Failed, disposition.status)
        assertEquals("HTTP 401", disposition.message)
        assertFalse(disposition.shouldRetry)
        assertTrue(disposition.shouldNotifyFailure)
    }

    private fun failedResult(message: String, retryable: Boolean): UploadResult {
        return UploadResult(
            ok = false,
            title = "title",
            originalPath = "",
            ragflowDocumentId = "",
            duplicate = false,
            message = message,
            retryable = retryable,
        )
    }
}
