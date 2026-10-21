package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.capabilities.AppCapabilities
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppCapabilityFailure
import com.sudox.perclip.capabilities.AppFeatures
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import org.junit.Assert.assertEquals
import org.junit.Test

class SettingsPresentationTest {
    private val settings = PerClipSettings("https://private.example/perclip", "secret-token", "Phone", true, false)
    private val capability = AppCapabilityResult(true, AppCapabilities("perclip.app.v1", "perclip-ingest", AppFeatures(true, true, true, true, true, true, true)), message = "ok")

    @Test fun dashboardUsesRealConnectionAndQueueSummaries() {
        val records = listOf(record("waiting", UploadStatus.Waiting), record("failed", UploadStatus.Failed))
        val result = SettingsPresentation.dashboard(settings, capability, records)
        assertEquals("完整连接", result.connection)
        assertEquals(SettingsConnectionState.FULL, result.connectionState)
        assertEquals("1 条失败", result.processingQueue)
        assertEquals(1, result.waitingCount)
        assertEquals(1, result.failedCount)

        assertEquals(
            SettingsConnectionState.CHECKING,
            SettingsPresentation.dashboard(settings, null, emptyList()).connectionState,
        )
        assertEquals(
            SettingsConnectionState.BASIC,
            SettingsPresentation.dashboard(
                settings,
                AppCapabilityResult(false, failure = AppCapabilityFailure.CONTRACT_MISSING, message = "legacy"),
                emptyList(),
            ).connectionState,
        )
        assertEquals(
            SettingsConnectionState.DISCONNECTED,
            SettingsPresentation.dashboard(
                settings,
                AppCapabilityResult(false, failure = AppCapabilityFailure.UNREACHABLE, message = "offline"),
                emptyList(),
            ).connectionState,
        )
    }

    @Test fun emptyQueueIsExplicit() {
        val result = SettingsPresentation.dashboard(settings, capability, emptyList())
        assertEquals("队列为空", result.processingQueue)
    }

    private fun record(id: String, status: UploadStatus) = UploadRecord(SharedClip(id, ClipKind.Text, id), status, "")
}
