package com.sudox.perclip.upload

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadFailurePolicyTest {
    @Test
    fun retriesTransientHttpStatuses() {
        assertTrue(UploadFailurePolicy.isRetryableHttpStatus(408))
        assertTrue(UploadFailurePolicy.isRetryableHttpStatus(409))
        assertTrue(UploadFailurePolicy.isRetryableHttpStatus(429))
        assertTrue(UploadFailurePolicy.isRetryableHttpStatus(500))
        assertTrue(UploadFailurePolicy.isRetryableHttpStatus(503))
    }

    @Test
    fun doesNotRetryPermanentClientErrors() {
        assertFalse(UploadFailurePolicy.isRetryableHttpStatus(400))
        assertFalse(UploadFailurePolicy.isRetryableHttpStatus(401))
        assertFalse(UploadFailurePolicy.isRetryableHttpStatus(413))
        assertFalse(UploadFailurePolicy.isRetryableHttpStatus(415))
    }
}
