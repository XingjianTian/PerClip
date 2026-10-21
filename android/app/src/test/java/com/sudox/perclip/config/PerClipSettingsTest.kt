package com.sudox.perclip.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PerClipSettingsTest {
    @Test
    fun normalizedTrimsNetworkFieldsAndDefaultsDeviceName() {
        val settings = PerClipSettings(
            apiUrl = "  http://100.64.0.10:18081///  ",
            ingestToken = "  mobile-token  ",
            deviceName = "   ",
            wifiOnlyLargeFiles = false,
            persistentQuickEntry = true,
        )

        val normalized = settings.normalized()

        assertEquals("http://100.64.0.10:18081", normalized.apiUrl)
        assertEquals("mobile-token", normalized.ingestToken)
        assertEquals(PerClipSettings.DEFAULT_DEVICE_NAME, normalized.deviceName)
        assertFalse(normalized.wifiOnlyLargeFiles)
        assertTrue(normalized.persistentQuickEntry)
        assertEquals(7, normalized.recallPeriodDays)
        assertTrue(normalized.recallAutoSurface)
        assertTrue(normalized.recallGraphExpanded)
        assertFalse(normalized.reduceMotion)
        assertEquals(AppThemeMode.FOLLOW_SYSTEM, normalized.themeMode)
    }

    @Test
    fun themeModeStorageFallsBackSafelyAndResolvesAgainstSystem() {
        assertEquals(AppThemeMode.FOLLOW_SYSTEM, AppThemeMode.fromStorage(null))
        assertEquals(AppThemeMode.FOLLOW_SYSTEM, AppThemeMode.fromStorage("future-value"))
        assertEquals(AppThemeMode.LIGHT, AppThemeMode.fromStorage("light"))
        assertEquals(AppThemeMode.DARK, AppThemeMode.fromStorage("dark"))
        assertTrue(AppThemeMode.FOLLOW_SYSTEM.resolve(systemInDarkTheme = true))
        assertFalse(AppThemeMode.FOLLOW_SYSTEM.resolve(systemInDarkTheme = false))
        assertFalse(AppThemeMode.LIGHT.resolve(systemInDarkTheme = true))
        assertTrue(AppThemeMode.DARK.resolve(systemInDarkTheme = false))
    }

    @Test
    fun hasUploadConfigIgnoresSurroundingWhitespace() {
        assertTrue(
            PerClipSettings(
                apiUrl = "  http://100.64.0.10:18081  ",
                ingestToken = "  mobile-token  ",
                deviceName = "Phone",
                wifiOnlyLargeFiles = true,
                persistentQuickEntry = false,
            ).hasUploadConfig,
        )
        assertFalse(
            PerClipSettings(
                apiUrl = "  http://100.64.0.10:18081  ",
                ingestToken = "   ",
                deviceName = "Phone",
                wifiOnlyLargeFiles = true,
                persistentQuickEntry = false,
            ).hasUploadConfig,
        )
    }

    @Test
    fun normalizedKeepsAutomaticResurfacingEnabled() {
        val normalized = PerClipSettings(
            apiUrl = "",
            ingestToken = "",
            deviceName = "Phone",
            wifiOnlyLargeFiles = true,
            persistentQuickEntry = false,
            recallAutoSurface = false,
        ).normalized()

        assertTrue(normalized.recallAutoSurface)
    }

    @Test
    fun normalizedPreservesConfirmedCustomRangeForProcessRebuild() {
        val normalized = PerClipSettings(
            apiUrl = "",
            ingestToken = "",
            deviceName = "Phone",
            wifiOnlyLargeFiles = true,
            persistentQuickEntry = false,
            recallPeriodKind = "custom",
            recallCustomStartDate = "2026-07-01",
            recallCustomEndDate = "2026-07-05",
            recallCustomTimezone = "Asia/Shanghai",
        ).normalized()

        assertEquals("custom", normalized.recallPeriodKind)
        assertEquals("2026-07-01", normalized.recallCustomStartDate)
        assertEquals("2026-07-05", normalized.recallCustomEndDate)
        assertEquals("Asia/Shanghai", normalized.recallCustomTimezone)
    }

    @Test
    fun invalidCustomDateDraftCannotReplaceConfirmedState() {
        val normalized = PerClipSettings(
            apiUrl = "",
            ingestToken = "",
            deviceName = "Phone",
            wifiOnlyLargeFiles = true,
            persistentQuickEntry = false,
            recallPeriodKind = "custom",
            recallCustomStartDate = "draft",
            recallCustomEndDate = "",
            recallCustomTimezone = "UTC",
        ).normalized()

        assertEquals("", normalized.recallCustomStartDate)
        assertEquals("", normalized.recallCustomEndDate)
    }
}
