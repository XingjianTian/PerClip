package com.sudox.perclip.ui

import com.sudox.perclip.ui.screens.KnowledgeHomeLayoutSpec
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Paths
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UiConsistencyContractTest {
    @Test fun knowledgeStatusCardKeepsACompactConnectionIndependentHeaderGap() {
        assertEquals(56, KnowledgeHomeLayoutSpec.HEADER_HEIGHT_DP)

        val source = source("src/main/java/com/sudox/perclip/ui/screens/KnowledgeHomeScreen.kt")
        val summary = source.indexOf("SummaryCard(summary.ingested")
        val offlineNotice = source.indexOf("val showOfflineNotice")
        assertTrue(summary >= 0)
        assertTrue(offlineNotice > summary)
    }

    @Test fun flashTabUsesTheOriginalRoundedBolt() {
        val source = source("src/main/java/com/sudox/perclip/ui/PerClipApp.kt")
        assertTrue(source.contains("imageVector = Icons.Rounded.Bolt"))
        assertFalse(source.contains("ic_flash_navigation"))
    }

    @Test fun everyTopLevelSettingsEntryShowsHome() {
        val source = source("src/main/java/com/sudox/perclip/ui/PerClipApp.kt")
        assertTrue(source.contains("fun openSettingsHome()"))
        assertTrue(source.contains("onClick = ::openSettingsHome"))
        assertTrue(source.contains("onGoToSettings = ::openSettingsHome"))
    }

    @Test fun settingsUseOneSemanticTypeAndColorRamp() {
        val source = source("src/main/java/com/sudox/perclip/ui/screens/SettingsComponents.kt")

        assertTrue(source.contains("PageTitle = TextStyle(fontSize = 28.sp"))
        assertTrue(source.contains("RowTitle = TextStyle(fontSize = 16.sp"))
        assertTrue(source.contains("Supporting = TextStyle(fontSize = 13.sp"))
        assertTrue(source.contains("TextSecondaryLight = Color(0xFF69647D)"))
        assertTrue(source.contains("TextSecondaryDark = Color(0xFFC4B7CA)"))
        assertTrue(source.contains("TextTertiaryDark = Color(0xFF99899F)"))
    }

    @Test fun darkRecallUsesReadableSemanticTextColors() {
        val source = source("src/main/java/com/sudox/perclip/ui/recall/RecallHomeScreen.kt")

        assertTrue(source.contains("ColorTokens.DarkPlumPlanet"))
        assertTrue(source.contains("Text(topicLabel, color = palette.ink"))
        assertTrue(source.contains("color = if (active) palette.accentText else palette.ink"))
    }

    @Test fun ragflowDiagnosticsLiveOnlyOnTheConnectionPage() {
        val home = source("src/main/java/com/sudox/perclip/ui/screens/SettingsHomeScreen.kt")
        val destination = source("src/main/java/com/sudox/perclip/ui/screens/SettingsDestination.kt")
        val connection = source("src/main/java/com/sudox/perclip/ui/screens/ServerSettingsScreen.kt")

        assertFalse(home.contains("诊断与关于"))
        assertFalse(home.contains("系统信息"))
        assertFalse(destination.contains("SystemInformation"))
        assertTrue(connection.contains("RAGFlow 检查"))
        assertTrue(connection.contains("knowledgeBaseApi.ragflowProbe"))
    }

    private fun source(path: String): String = String(
        Files.readAllBytes(Paths.get(path)),
        StandardCharsets.UTF_8,
    )
}
