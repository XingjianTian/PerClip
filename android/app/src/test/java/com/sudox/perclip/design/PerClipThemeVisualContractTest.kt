package com.sudox.perclip.design

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Test

class PerClipThemeVisualContractTest {

    @Test
    fun `light scheme uses purple white surfaces and lavender hierarchy`() {
        assertEquals(ColorTokens.FlashPurple, PerClipLightScheme.primary)
        assertEquals(Color.White, PerClipLightScheme.onPrimary)
        assertEquals(ColorTokens.FlashBackground, PerClipLightScheme.background)
        assertEquals(Color.White, PerClipLightScheme.surface)
        assertEquals(Color(0xFFF3EFF8), PerClipLightScheme.surfaceVariant)
        assertEquals(Color(0xFFEEE8F3), PerClipLightScheme.outlineVariant)
    }

    @Test
    fun `dark scheme keeps soft plum surfaces and borders`() {
        assertEquals(ColorTokens.DarkPlumBackground, PerClipDarkScheme.background)
        assertEquals(ColorTokens.DarkPlumSurface, PerClipDarkScheme.surface)
        assertEquals(ColorTokens.DarkPlumRaised, PerClipDarkScheme.surfaceVariant)
        assertEquals(ColorTokens.DarkPlumBorderSoft, PerClipDarkScheme.outlineVariant)
        assertEquals(Color(0xFF3B2E43), PerClipDarkScheme.surfaceContainerHighest)
    }
}
