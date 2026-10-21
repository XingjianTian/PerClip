package com.sudox.perclip.ui.screens

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * KIMI 美化版设置首页（Figma 338:13820 / 338:13891）的视觉合同测试：
 * 固定行图标色值、亮/暗图标贴底色、卡片色与细分隔线色，防止后续改动漂移。
 */
class KimiSettingsVisualContractTest {

    @Test
    fun `row icon colors match the approved KIMI palette`() {
        assertEquals(Color(0xFF7862F2), KimiSettingsColors.Connection)
        assertEquals(Color(0xFF5B8DEF), KimiSettingsColors.Capture)
        assertEquals(Color(0xFF1FAD7A), KimiSettingsColors.KnowledgeBase)
        assertEquals(Color(0xFF9B5CF6), KimiSettingsColors.Planet)
        assertEquals(Color(0xFFE15A8C), KimiSettingsColors.Theme)
    }

    @Test
    fun `neutral row icon color switches between light and dark`() {
        assertEquals(Color(0xFF6F7891), KimiSettingsColors.neutralRow(isDark = false))
        assertEquals(Color(0xFF9AA3BC), KimiSettingsColors.neutralRow(isDark = true))
    }

    @Test
    fun `icon tile background uses tinted soft in light and white overlay in dark`() {
        val lightTile = KimiSettingsColors.iconTileBackground(KimiSettingsColors.Connection, isDark = false)
        assertEquals(31 / 255f, lightTile.alpha, 0.0001f)
        assertEquals(KimiSettingsColors.Connection.red, lightTile.red, 0.001f)

        val darkTile = KimiSettingsColors.iconTileBackground(KimiSettingsColors.Connection, isDark = true)
        assertEquals(20 / 255f, darkTile.alpha, 0.0001f)
        assertEquals(1f, darkTile.red, 0.001f)
        assertEquals(1f, darkTile.green, 0.001f)
        assertEquals(1f, darkTile.blue, 0.001f)
    }

    @Test
    fun `dark card uses soft plum surface with subtle white border`() {
        assertEquals(Color(0xFF251D31), KimiSettingsColors.CardDark)
        assertEquals(Color(0xFFEEEAFB), KimiSettingsColors.cardBorder(isDark = false))
        val darkBorder = KimiSettingsColors.cardBorder(isDark = true)
        assertEquals(18 / 255f, darkBorder.alpha, 0.0001f)
    }

    @Test
    fun `divider matches inset hairline contract for both modes`() {
        assertEquals(Color(0xFFF1EEFA), KimiSettingsColors.divider(isDark = false))
        val darkDivider = KimiSettingsColors.divider(isDark = true)
        assertEquals(15 / 255f, darkDivider.alpha, 0.0001f)
    }

    @Test
    fun `page background matches spec for both modes`() {
        assertEquals(Color(0xFFF8F6FE), KimiSettingsColors.pageBackground(isDark = false))
        assertEquals(Color(0xFF1A141E), KimiSettingsColors.pageBackground(isDark = true))
    }

    @Test
    fun `semantic text colors stay readable in both modes`() {
        assertEquals(Color(0xFF18172D), KimiSettingsColors.titleText(false, Color.Unspecified))
        assertEquals(Color(0xFFF4F0FC), KimiSettingsColors.titleText(true, Color.Unspecified))
        assertEquals(Color(0xFF69647D), KimiSettingsColors.summaryText(false, Color.Unspecified))
        assertEquals(Color(0xFFC4B7CA), KimiSettingsColors.summaryText(true, Color.Unspecified))
        assertEquals(Color(0xFF8D879F), KimiSettingsColors.tertiaryText(false))
        assertEquals(Color(0xFF99899F), KimiSettingsColors.tertiaryText(true))
    }

    @Test
    fun `switch track matches spec for both modes`() {
        assertEquals(Color(0xFFDDD6F0), KimiSettingsColors.switchTrack(isDark = false))
        assertEquals(Color(0xFF3A3148), KimiSettingsColors.switchTrack(isDark = true))
        assertEquals(Color(0xFF7862F2), KimiSettingsColors.switchTrack(checked = true, isDark = false))
        assertEquals(Color(0xFF917AFF), KimiSettingsColors.switchTrack(checked = true, isDark = true))
    }

    @Test
    fun `divider dark color stays at white 6 percent`() {
        val darkDivider = KimiSettingsColors.divider(isDark = true)
        assertEquals(15 / 255f, darkDivider.alpha, 0.0001f)
        assertEquals(1f, darkDivider.red, 0.001f)
    }

    @Test
    fun `appearance cards use shared white in light and soft plum in dark`() {
        assertEquals(Color.White, AppearanceSettingsColors.card(isDark = false))
        assertEquals(Color(0xFF281F2C), AppearanceSettingsColors.card(isDark = true))
    }
}
