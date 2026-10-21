package com.sudox.perclip.screen

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TriggeredCaptureGateTest {
    @Test
    fun oneTriggerCanCompleteAtMostOnce() {
        val gate = TriggeredCaptureGate()

        assertTrue(gate.tryStart())
        assertFalse(gate.tryStart())
        assertTrue(gate.tryComplete())
        assertFalse(gate.tryComplete())
    }

    @Test
    fun releaseAllowsRetryAfterFailureOrCompletion() {
        val gate = TriggeredCaptureGate()

        assertTrue(gate.tryStart())
        gate.release()

        assertFalse(gate.isActive())
        assertTrue(gate.tryStart())
        assertTrue(gate.tryComplete())
    }
}
