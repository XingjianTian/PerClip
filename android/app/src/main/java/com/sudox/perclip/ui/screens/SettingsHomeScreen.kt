package com.sudox.perclip.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.CloudDone
import androidx.compose.material.icons.rounded.CloudOff
import androidx.compose.material.icons.rounded.CloudQueue
import androidx.compose.material.icons.rounded.Sync
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.MotionPhotosOff
import androidx.compose.material.icons.rounded.SaveAlt
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sudox.perclip.ui.SettingsDashboardSummary
import com.sudox.perclip.ui.SettingsConnectionState
import com.sudox.perclip.config.AppThemeMode

private const val SETTINGS_VERSION_FOOTER = "PerClip · 私有云记忆 · v0.3.0"

@Composable
fun SettingsHomeScreen(
    contentPadding: PaddingValues,
    summary: SettingsDashboardSummary,
    reduceMotion: Boolean,
    themeMode: AppThemeMode,
    onReduceMotionChanged: (Boolean) -> Unit,
    onOpen: (SettingsDestination) -> Unit,
) {
    val isDark = isDarkSettingsBackground()
    LazyColumn(
        Modifier.fillMaxSize().background(KimiSettingsColors.pageBackground(isDark)).padding(contentPadding),
        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 12.dp, bottom = 20.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        item {
            Text("设置", style = PerClipSettingsTypography.PageTitle, color = settingsPrimaryTextColor())
        }
        item {
            KimiSettingsGroupTitle("连接与同步")
            val connectionIcon = when (summary.connectionState) {
                SettingsConnectionState.CHECKING -> Icons.Rounded.Sync
                SettingsConnectionState.BASIC -> Icons.Rounded.CloudQueue
                SettingsConnectionState.FULL -> Icons.Rounded.CloudDone
                SettingsConnectionState.DISCONNECTED -> Icons.Rounded.CloudOff
            }
            KimiSettingsGroupCard {
                KimiSettingsRow("连接设置", summary.connection, connectionIcon, iconTint = KimiSettingsColors.Connection, onClick = { onOpen(SettingsDestination.Connection) })
                KimiSettingsCardDivider()
                KimiSettingsRow("记忆抓取设置", summary.processingQueue, Icons.Rounded.SaveAlt, iconTint = KimiSettingsColors.Capture, onClick = { onOpen(SettingsDestination.CaptureAndIngest) })
                KimiSettingsCardDivider()
                KimiSettingsRow("知识库管理", "默认库与自定义库", Icons.Rounded.Folder, iconTint = KimiSettingsColors.KnowledgeBase, onClick = { onOpen(SettingsDestination.KnowledgeManagement) })
                KimiSettingsCardDivider()
                KimiSettingsRow("记忆星球设置", "主题与显示", Icons.Rounded.AutoAwesome, iconTint = KimiSettingsColors.Planet, onClick = { onOpen(SettingsDestination.RecallDisplayManagement) })
            }
        }
        item {
            KimiSettingsGroupTitle("外观与辅助")
            KimiSettingsGroupCard {
                KimiSettingsRow("外观", "${themeMode.settingsLabel()} · PerClip 紫", Icons.Rounded.Palette, iconTint = KimiSettingsColors.Theme, onClick = { onOpen(SettingsDestination.Appearance) })
                KimiSettingsCardDivider()
                KimiSettingsRow("减少动态效果", if (reduceMotion) "已开启" else "已关闭", Icons.Rounded.MotionPhotosOff, iconTint = KimiSettingsColors.neutralRow(isDark), checked = reduceMotion, onCheckedChange = onReduceMotionChanged)
            }
        }
        item {
            Text(
                SETTINGS_VERSION_FOOTER,
                modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
                style = PerClipSettingsTypography.Supporting,
                color = settingsTertiaryTextColor(),
                textAlign = TextAlign.Center,
            )
        }
    }
}

internal fun AppThemeMode.settingsLabel(): String = when (this) {
    AppThemeMode.FOLLOW_SYSTEM -> "跟随系统"
    AppThemeMode.LIGHT -> "浅色"
    AppThemeMode.DARK -> "深色"
}
