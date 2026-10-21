package com.sudox.perclip.screen

import com.sudox.perclip.screen.adapters.XhsShareLinkAdapter
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenCaptureAdapterRegistryTest {
    @Test
    fun routesXhsPackageToXhsAdapter() {
        assertTrue(ScreenCaptureAdapterRegistry.adapterFor("com.xingin.xhs") is XhsShareLinkAdapter)
    }

    @Test
    fun unknownPackageUsesDefaultScreenCapture() {
        assertNull(ScreenCaptureAdapterRegistry.adapterFor("com.example.browser"))
    }
}
