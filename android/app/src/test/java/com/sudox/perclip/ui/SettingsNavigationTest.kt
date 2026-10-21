package com.sudox.perclip.ui

import com.sudox.perclip.ui.screens.SettingsDestination
import com.sudox.perclip.ui.screens.SettingsNavigation
import com.sudox.perclip.ui.screens.SettingsStateHolder
import com.sudox.perclip.ui.screens.normalizedDeviceName
import com.sudox.perclip.config.PerClipSettings
import org.junit.Assert.assertEquals
import org.junit.Test

class SettingsNavigationTest {
    @Test fun primaryChildrenReturnHome() {
        listOf<SettingsDestination>(
            SettingsDestination.Connection,
            SettingsDestination.CaptureAndIngest,
            SettingsDestination.Appearance,
        ).forEach { assertEquals(SettingsDestination.Home, SettingsNavigation.back(it)) }
    }

    @Test fun sharedManagementRoutesReturnToKnowledgeEntry() {
        assertEquals(SettingsDestination.Home, SettingsNavigation.back(SettingsDestination.KnowledgeManagement))
        assertEquals(SettingsDestination.Home, SettingsNavigation.back(SettingsDestination.RecallDisplayManagement))
    }

    @Test fun activeSettingsTitlesAreExplicit() {
        assertEquals("连接设置", SettingsNavigation.title(SettingsDestination.Connection))
        assertEquals("记忆抓取设置", SettingsNavigation.title(SettingsDestination.CaptureAndIngest))
        assertEquals("外观", SettingsNavigation.title(SettingsDestination.Appearance))
        assertEquals("我的手机", normalizedDeviceName("  我的手机  "))
        assertEquals(PerClipSettings.DEFAULT_DEVICE_NAME, normalizedDeviceName("   "))
    }

    @Test fun topLevelSettingsEntryResetsChildRouteToHome() {
        val holder = SettingsStateHolder()
        holder.navigate(SettingsDestination.Appearance)
        holder.showHome()
        assertEquals(SettingsDestination.Home, holder.destination)
    }
}
