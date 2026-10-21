package com.sudox.perclip.capabilities

import com.sudox.perclip.config.PerClipSettings
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppCapabilityCoordinatorTest {
    @Test fun sameConfigurationHasOneInflightAndPartialDoesNotRefetch() {
        val coordinator = AppCapabilityCoordinator()
        val request = coordinator.begin(settings())
        assertNotNull(request)
        assertNull(coordinator.begin(settings()))
        assertNull(coordinator.begin(settings(), force = true))
        coordinator.accept(request!!, partial())
        assertNull(coordinator.begin(settings()))
    }

    @Test fun rapidConfigurationChangeRejectsOldResponse() {
        val coordinator = AppCapabilityCoordinator()
        val old = coordinator.begin(settings())!!
        val newerSettings = settings().copy(apiUrl = "http://127.0.0.2:18082")
        val newer = coordinator.begin(newerSettings)!!
        assertFalse(coordinator.accept(old, partial()))
        assertTrue(coordinator.accept(newer, partial()))
    }

    @Test fun noConfigurationIsExplicitlyUnavailable() {
        val coordinator = AppCapabilityCoordinator()
        assertNull(coordinator.begin(settings().copy(ingestToken = "")))
        assertFalse(coordinator.state.loading)
        assertTrue(coordinator.state.result?.failure == AppCapabilityFailure.CONFIGURATION)
    }

    @Test fun fingerprintIsStableButDoesNotExposeInput() {
        val one = capabilityConfigurationFingerprint(settings())
        val two = capabilityConfigurationFingerprint(settings())
        assertTrue(one == two)
        assertFalse(one.contains("test-token"))
        assertNotEquals(one, capabilityConfigurationFingerprint(settings().copy(ingestToken = "other")))
    }

    private fun settings() = PerClipSettings("http://127.0.0.1:18082", "test-token", "test", true, false)
    private fun partial() = AppCapabilityResult(
        true,
        AppCapabilities(AppCapabilities.EXPECTED_CONTRACT, AppCapabilities.EXPECTED_SERVICE, AppFeatures(true, true, false, true, true, true, true)),
        AppCapabilityFailure.FEATURES_INCOMPLETE,
        "partial",
    )
}
