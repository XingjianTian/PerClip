package com.sudox.perclip.debug

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.LibraryBooks
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.capabilities.AppCapabilities
import com.sudox.perclip.capabilities.AppCapabilityFailure
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppFeatures
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.config.PerClipSettingsStore
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.design.PerClipTheme
import com.sudox.perclip.ui.BottomNavigationIconSlot
import com.sudox.perclip.ui.BottomNavigationSpec
import com.sudox.perclip.ui.MemoryPlanetTabIcon
import com.sudox.perclip.ui.bottomNavigationSelection
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.ui.recall.RecallStateHolder
import com.sudox.perclip.ui.recall.RecallDomainLoader
import com.sudox.perclip.recall.RecallApiResult
import com.sudox.perclip.recall.repository.RecallDomainSnapshot
import com.sudox.perclip.recall.repository.RecallDomainTopic
import com.sudox.perclip.ui.screens.SettingsDestination
import com.sudox.perclip.ui.screens.SettingsScreen
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadResult
import com.sudox.perclip.upload.UploadStatus
import kotlinx.coroutines.delay

/** Debug-only fictional Settings states. This activity and its data are absent from release builds. */
class SettingsEvidenceActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val fixture = intent.getStringExtra("fixture") ?: "connected"
        val forceDark = intent.getBooleanExtra("dark", false)
        val connectionResult = intent.getStringExtra("connectionResult") ?: fixture
        val connectionShouldFail = connectionResult == "failure" || connectionResult == "connection-failure"
        val initialDestination = when (fixture) {
            "connection", "connection-success", "connection-failure" -> SettingsDestination.Connection
            "capture", "capture-persistence", "capture-dark" -> SettingsDestination.CaptureAndIngest
            "theme", "theme-dark" -> SettingsDestination.Appearance
            "about", "about-dark" -> SettingsDestination.Connection
            "knowledge" -> SettingsDestination.KnowledgeManagement
            "planet", "planet-failure", "planet-unavailable" -> SettingsDestination.RecallDisplayManagement
            else -> SettingsDestination.Home
        }
        val fixtureSettings = PerClipSettings(
            apiUrl = if (fixture == "disconnected") "" else "https://fictional.perclip.invalid/api",
            ingestToken = if (fixture == "disconnected") "" else "fictional-debug-token",
            deviceName = "虚构测试设备",
            wifiOnlyLargeFiles = true,
            persistentQuickEntry = false,
        )
        val settingsStore = PerClipSettingsStore(this)
        val initialSettings = if (fixture.contains("persistence")) settingsStore.load() else fixtureSettings
        val records = when (fixture) {
            "queue-error", "about" -> listOf(record("waiting", UploadStatus.Waiting), record("failed", UploadStatus.Failed), record("failed-2", UploadStatus.Failed))
            "empty-queue" -> emptyList()
            else -> listOf(record("waiting", UploadStatus.Waiting), record("uploaded", UploadStatus.Uploaded))
        }
        val capability = when (fixture) {
            "checking" -> null
            "disconnected" -> AppCapabilityResult(false, failure = AppCapabilityFailure.CONFIGURATION, message = "尚未配置连接")
            "unavailable", "planet-unavailable" -> AppCapabilityResult(false, failure = AppCapabilityFailure.CONTRACT_MISSING, message = "基础保存可用；高级功能不可用")
            else -> fullCapability()
        }
        setContent {
            var settings by remember { mutableStateOf(initialSettings) }
            PerClipTheme(darkTheme = settings.themeMode.resolve(forceDark || fixture == "dark" || fixture.endsWith("-dark"))) {
                val density = LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(density.density, if (fixture == "font130") 1.3f else density.fontScale)) {
                    Scaffold(bottomBar = { SettingsEvidenceBottomBar() }) { padding ->
                        SettingsScreen(
                            contentPadding = padding,
                            settings = settings,
                            recentRecords = records,
                            recallStateHolder = remember { RecallStateHolder() },
                            onRequestNotificationPermission = {},
                            onConnectionVerified = { records.count { it.status == UploadStatus.Waiting } },
                            onSettingsChange = { updated -> settings = updated; if (fixture.contains("persistence")) settingsStore.save(updated) },
                            onOpenKnowledgeRecords = {},
                            appCapabilityResult = capability,
                            knowledgeBases = listOf(KnowledgeBaseSummary("personal", "个人收藏", "虚构默认知识库", isDefault = true)),
                            onRequestCapabilityRefresh = {},
                            initialDestination = initialDestination,
                            verifyConnection = {
                                UploadResult(
                                    ok = !connectionShouldFail,
                                    title = "连接测试",
                                    originalPath = "",
                                    ragflowDocumentId = "",
                                    duplicate = false,
                                    message = if (connectionShouldFail) "连接失败：虚构服务不可达" else "连接正常",
                                )
                            },
                            recallDomainLoaderOverride = RecallDomainLoader { _, _ ->
                                delay(800)
                                if (fixture == "planet-failure") {
                                    RecallApiResult.failure("虚构主题加载失败")
                                } else {
                                    RecallApiResult.success(
                                        RecallDomainSnapshot(
                                            snapshotKey = "fictional-settings-evidence",
                                            topics = listOf(
                                                RecallDomainTopic("fictional-writing", "写作", "写作", clipCount = 12),
                                                RecallDomainTopic("fictional-learning", "学习", "学习", clipCount = 8),
                                            ),
                                        ),
                                    )
                                }
                            },
                        )
                    }
                }
            }
        }
    }

    private fun record(id: String, status: UploadStatus) = UploadRecord(SharedClip(id, ClipKind.Text, "虚构记忆 $id", text = "仅用于设置页截图的虚构内容"), status, "")

    private fun fullCapability() = AppCapabilityResult(
        true,
        AppCapabilities("perclip.app.v1", "perclip-ingest", AppFeatures(true, true, true, true, true, true, true)),
        message = "完整功能可用",
    )
}

@androidx.compose.runtime.Composable
private fun SettingsEvidenceBottomBar() {
    Surface(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), shape = RoundedCornerShape(22.dp), border = BorderStroke(1.dp, ColorTokens.FlashBorder)) {
        NavigationBar(modifier = Modifier.height(BottomNavigationSpec.NAVIGATION_HEIGHT_DP.dp).bottomNavigationSelection(3, ColorTokens.FlashPurple), containerColor = androidx.compose.ui.graphics.Color.Transparent) {
            val colors = NavigationBarItemDefaults.colors(selectedIconColor = ColorTokens.FlashPurple, selectedTextColor = ColorTokens.FlashPurple, indicatorColor = androidx.compose.ui.graphics.Color.Transparent)
            NavigationBarItem(false, {}, { BottomNavigationIconSlot { Icon(Icons.Rounded.Bolt, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("闪记") }, colors = colors)
            NavigationBarItem(false, {}, { BottomNavigationIconSlot { Icon(Icons.AutoMirrored.Rounded.LibraryBooks, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("知识库") }, colors = colors)
            NavigationBarItem(false, {}, { BottomNavigationIconSlot { MemoryPlanetTabIcon(selected = false, modifier = Modifier.size(BottomNavigationSpec.MEMORY_PLANET_ICON_DP.dp)) } }, label = { Text("记忆星球") }, colors = colors)
            NavigationBarItem(true, {}, { BottomNavigationIconSlot { Icon(Icons.Rounded.Settings, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("设置") }, colors = colors)
        }
    }
}
