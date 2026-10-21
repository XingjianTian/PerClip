package com.sudox.perclip

import java.nio.file.Files
import java.nio.file.Paths
import java.nio.charset.StandardCharsets
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureEntryPointContractTest {
    @Test
    fun flashKeepsCompactGlobalDefaultControlWithoutPerDraftOverride() {
        val screen = source("src/main/java/com/sudox/perclip/ui/screens/FlashNoteScreen.kt")
        val app = source("src/main/java/com/sudox/perclip/ui/PerClipApp.kt")

        assertTrue(screen.contains("DefaultKnowledgeBaseEntry"))
        assertTrue(screen.contains("默认保存至"))
        assertTrue(screen.contains("更改"))
        assertTrue(app.contains("openDefaultPickerOnManagement"))
        assertTrue(app.contains("returnToFlashAfterManagement"))
        assertFalse(screen.contains("routing rule"))
        assertFalse(screen.contains("manualOverride"))
        assertTrue(app.contains("CaptureOrigin.IN_APP_FLASH"))
    }

    @Test
    fun captureOriginsAreMappedWithoutMainActivityShareHandling() {
        val main = source("src/main/java/com/sudox/perclip/MainActivity.kt")
        val share = source("src/main/java/com/sudox/perclip/ShareCaptureActivity.kt")
        val bridge = source("src/main/java/com/sudox/perclip/ClipboardBridgeActivity.kt")
        val screen = source("src/main/java/com/sudox/perclip/screen/PerClipAccessibilityService.kt")
        val notification = source("src/main/java/com/sudox/perclip/notifications/QuickEntryNotificationHelper.kt")

        assertFalse(main.contains("Intent.ACTION_SEND"))
        assertFalse(main.contains("saveExternalShare"))
        assertFalse(main.contains("ShareIntentParser"))
        assertFalse(main.contains("ACTION_CAPTURE_SCREEN"))
        assertFalse(main.contains("ScreenClipStore"))
        assertTrue(share.contains("CaptureOrigin.ANDROID_SHARE"))
        assertTrue(bridge.contains("CaptureOrigin.CLIPBOARD_BRIDGE"))
        assertTrue(bridge.contains("CaptureOrigin.SCREEN_CAPTURE"))
        assertTrue(screen.contains("CaptureOrigin.SCREEN_CAPTURE"))
        assertFalse(screen.contains("openFallbackPreview"))
        assertTrue(notification.contains("PendingIntent.getBroadcast"))
        assertTrue(notification.contains("CaptureTriggerReceiver::class.java"))
    }

    @Test
    fun settingsManagementEntriesAreOrdinaryConnectionRows() {
        val screen = source("src/main/java/com/sudox/perclip/ui/screens/SettingsHomeScreen.kt")
        val connectionStart = screen.indexOf("SettingsGroupTitle(\"连接与同步\")")
        val appearanceStart = screen.indexOf("SettingsGroupTitle(\"外观与辅助\")")
        val knowledgeRow = screen.indexOf("SettingsRow(\"知识库管理\"")
        val recallRow = screen.indexOf("SettingsRow(\"记忆星球设置\"")

        assertTrue(connectionStart >= 0)
        assertTrue(appearanceStart > connectionStart)
        assertTrue(knowledgeRow in (connectionStart + 1) until appearanceStart)
        assertTrue(recallRow in (connectionStart + 1) until appearanceStart)
        assertFalse(screen.contains("SettingsShortcut"))
        assertFalse(screen.contains("记忆星球管理"))
    }

    private fun source(path: String): String = String(
        Files.readAllBytes(Paths.get(path)),
        StandardCharsets.UTF_8,
    )
}
