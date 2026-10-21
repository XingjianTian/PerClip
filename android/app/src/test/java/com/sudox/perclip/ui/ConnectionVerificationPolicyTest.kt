package com.sudox.perclip.ui

import com.sudox.perclip.capabilities.AppCapabilityFailure
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppCapabilities
import com.sudox.perclip.capabilities.AppFeatures
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionVerificationPolicyTest {
    @Test fun healthyOldServerRequeuesDespiteCapability404() {
        val old = AppCapabilityResult(false, failure = AppCapabilityFailure.CONTRACT_MISSING, message = "404")
        val result = ConnectionVerificationPolicy.evaluate(healthOk = true, capability = old)
        assertTrue(result.shouldRequeue)
        assertTrue(result.advancedStatus.contains("版本不兼容"))
    }

    @Test fun healthFailureNeverRequeues() {
        assertFalse(ConnectionVerificationPolicy.evaluate(false, null).shouldRequeue)
    }

    @Test fun fullServerStillRequeuesAndReportsComplete() {
        val full = AppCapabilityResult(
            true,
            AppCapabilities(AppCapabilities.EXPECTED_CONTRACT, AppCapabilities.EXPECTED_SERVICE, AppFeatures(true, true, true, true, true, true, true)),
            message = "full",
        )
        val result = ConnectionVerificationPolicy.evaluate(true, full)
        assertTrue(result.shouldRequeue)
        assertTrue(result.advancedStatus.contains("完整"))
    }
}
