package com.sudox.perclip

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ShareCaptureRequestPolicyTest {
    @Test
    fun restoresStableRequestIdAcrossRecreation() {
        val restored = ShareCaptureRequestPolicy.restoreRequestId("request-stable") { "request-new" }

        assertEquals("request-stable", restored)
    }

    @Test
    fun independentShareCreatesNewRequestId() {
        val first = ShareCaptureRequestPolicy.restoreRequestId(null) { "request-1" }
        val second = ShareCaptureRequestPolicy.restoreRequestId(null) { "request-2" }

        assertEquals("request-1", first)
        assertEquals("request-2", second)
    }

    @Test
    fun launchesAtMostOncePerActivityInstanceAndReplaysIncompleteRecreation() {
        assertTrue(ShareCaptureRequestPolicy.shouldLaunchSave(saveCompleted = false, launchedInCurrentInstance = false))
        assertFalse(ShareCaptureRequestPolicy.shouldLaunchSave(saveCompleted = false, launchedInCurrentInstance = true))
        assertFalse(ShareCaptureRequestPolicy.shouldLaunchSave(saveCompleted = true, launchedInCurrentInstance = false))
    }
}
