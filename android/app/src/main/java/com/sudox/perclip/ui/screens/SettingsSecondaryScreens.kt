package com.sudox.perclip.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Shortcut
import androidx.compose.material.icons.rounded.AccessibilityNew
import androidx.compose.material.icons.rounded.BrightnessAuto
import androidx.compose.material.icons.rounded.DarkMode
import androidx.compose.material.icons.rounded.Devices
import androidx.compose.material.icons.rounded.LightMode
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.SaveAlt
import androidx.compose.material.icons.rounded.Storage
import androidx.compose.material.icons.rounded.Wifi
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Icon
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.config.AppThemeMode
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.design.perClipAccentColor
import com.sudox.perclip.design.perClipIsDarkTheme
import com.sudox.perclip.notifications.QuickEntryNotificationHelper
import com.sudox.perclip.notifications.QuickEntryNotificationState
import com.sudox.perclip.screen.ScreenCaptureAccessibilityStatus
import com.sudox.perclip.shortcuts.PinShortcutResult
import com.sudox.perclip.shortcuts.PinnedShortcutRequester
import com.sudox.perclip.ui.SettingsDashboardSummary

@Composable
fun CaptureAndIngestSettingsScreen(
    contentPadding: PaddingValues,
    settings: PerClipSettings,
    summary: SettingsDashboardSummary,
    onRequestNotificationPermission: () -> Unit,
    onChange: (PerClipSettings) -> Unit,
    onOpenFailedRecords: () -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val notifications = remember { QuickEntryNotificationHelper(context) }
    val shortcutSupported = remember { PinnedShortcutRequester.isSupported(context) }
    var accessibilityEnabled by remember { mutableStateOf(ScreenCaptureAccessibilityStatus.isEnabled(context)) }
    var message by remember { mutableStateOf("") }
    var editingDeviceName by remember { mutableStateOf(false) }
    var deviceNameDraft by remember(settings.deviceName) { mutableStateOf(settings.deviceName) }
    val deviceNameFocus = remember { FocusRequester() }
    fun saveDeviceName() {
        onChange(settings.copy(deviceName = normalizedDeviceName(deviceNameDraft)))
        editingDeviceName = false
    }
    SettingsPageScaffold(contentPadding, "记忆抓取设置", "本地优先，网络恢复后继续", onBack) {
        SettingsGroupTitle("设备与网络")
        SettingsRow("设备名称", settings.deviceName, Icons.Rounded.Devices, onClick = {
            deviceNameDraft = settings.deviceName
            editingDeviceName = true
        })
        SettingsRow("大文件仅 Wi-Fi 同步", "10MB 以上文件等待 Wi-Fi 或非计费网络", Icons.Rounded.Wifi, checked = settings.wifiOnlyLargeFiles, onCheckedChange = { onChange(settings.copy(wifiOnlyLargeFiles = it)) })
        SettingsGroupTitle("系统入口")
        SettingsRow("通知栏闪记入口", if (settings.persistentQuickEntry) "已开启" else "已关闭", Icons.Rounded.Notifications, checked = settings.persistentQuickEntry, onCheckedChange = { enabled ->
            onChange(settings.copy(persistentQuickEntry = enabled))
            if (enabled) onRequestNotificationPermission()
            message = when (notifications.sync(enabled)) {
                QuickEntryNotificationState.Visible -> "通知栏入口已开启。"
                QuickEntryNotificationState.PermissionRequired -> "需要允许通知权限后才能显示入口。"
                QuickEntryNotificationState.Cancelled -> "通知栏入口已关闭。"
            }
        })
        SettingsRow("无障碍截屏入口", if (accessibilityEnabled) "系统服务已开启" else "需要系统授权", Icons.Rounded.AccessibilityNew, onClick = {
            context.startActivity(ScreenCaptureAccessibilityStatus.settingsIntent())
            accessibilityEnabled = ScreenCaptureAccessibilityStatus.isEnabled(context)
        })
        SettingsRow("桌面快捷方式", if (shortcutSupported) "由启动器确认固定" else "当前启动器不支持", Icons.AutoMirrored.Rounded.Shortcut, enabled = shortcutSupported, onClick = {
            message = when (PinnedShortcutRequester.requestQuickNote(context)) {
                PinShortcutResult.Requested -> "已请求固定，请按系统提示确认。"
                PinShortcutResult.NotSupported -> "当前启动器不支持固定快捷方式。"
                PinShortcutResult.Failed -> "固定快捷方式请求未被系统接受。"
            }
        })
        SettingsGroupTitle("处理队列")
        SettingsRow("队列摘要", summary.processingQueue, Icons.Rounded.Storage, onClick = onOpenFailedRecords)
        Text("后台同步队列、本地优先和断网恢复策略保持不变。", style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor())
        if (message.isNotBlank()) Text(message, style = PerClipSettingsTypography.Supporting, color = settingsPrimaryTextColor())
    }
    if (editingDeviceName) {
        AlertDialog(
            onDismissRequest = { editingDeviceName = false },
            title = { Text("编辑设备名称") },
            text = {
                OutlinedTextField(
                    value = deviceNameDraft,
                    onValueChange = { deviceNameDraft = it },
                    modifier = Modifier.fillMaxWidth().focusRequester(deviceNameFocus),
                    label = { Text("设备名称") },
                    supportingText = { Text("用于标识这台设备保存的记忆") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { saveDeviceName() }),
                )
            },
            confirmButton = { TextButton(onClick = ::saveDeviceName) { Text("保存") } },
            dismissButton = { TextButton(onClick = { editingDeviceName = false }) { Text("取消") } },
        )
        androidx.compose.runtime.LaunchedEffect(Unit) { deviceNameFocus.requestFocus() }
    }
}

internal fun normalizedDeviceName(value: String): String =
    value.trim().ifBlank { PerClipSettings.DEFAULT_DEVICE_NAME }

internal object AppearanceSettingsColors {
    val CardLight = Color(0xFFFFFFFF)

    fun card(isDark: Boolean): Color =
        if (isDark) ColorTokens.DarkPlumSurface else CardLight
}

@Composable
fun AppearanceSettingsScreen(
    contentPadding: PaddingValues,
    selectedMode: AppThemeMode,
    onModeSelected: (AppThemeMode) -> Unit,
    onBack: () -> Unit,
) {
    val dark = perClipIsDarkTheme()
    val border = if (dark) ColorTokens.DarkPlumBorder else Color(0xFFE7DFF0)
    val card = AppearanceSettingsColors.card(dark)
    SettingsPageScaffold(contentPadding, "外观", "主题模式与显示", onBack) {
        SettingsGroupTitle("主题模式")
        AdaptiveThemePreview(border, card)
        Surface(
            shape = RoundedCornerShape(24.dp),
            color = card,
            border = BorderStroke(1.dp, border),
        ) {
            Column {
                AppearanceModeRow(
                    title = "跟随系统",
                    summary = "根据设备设置自动切换",
                    icon = Icons.Rounded.BrightnessAuto,
                    selected = selectedMode == AppThemeMode.FOLLOW_SYSTEM,
                    onClick = { onModeSelected(AppThemeMode.FOLLOW_SYSTEM) },
                )
                KimiSettingsCardDivider()
                AppearanceModeRow(
                    title = "浅色",
                    summary = "始终使用浅色外观",
                    icon = Icons.Rounded.LightMode,
                    selected = selectedMode == AppThemeMode.LIGHT,
                    onClick = { onModeSelected(AppThemeMode.LIGHT) },
                )
                KimiSettingsCardDivider()
                AppearanceModeRow(
                    title = "深色",
                    summary = "始终使用深色外观",
                    icon = Icons.Rounded.DarkMode,
                    selected = selectedMode == AppThemeMode.DARK,
                    onClick = { onModeSelected(AppThemeMode.DARK) },
                )
            }
        }
        SettingsGroupTitle("主题颜色")
        Surface(
            shape = RoundedCornerShape(24.dp),
            color = card,
            border = BorderStroke(1.dp, border),
        ) {
            Row(
                Modifier.fillMaxWidth().padding(16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Box(Modifier.size(40.dp).background(perClipAccentColor(), RoundedCornerShape(12.dp)))
                Column(Modifier.weight(1f)) {
                    Text("PerClip 紫", style = PerClipSettingsTypography.RowTitle, color = settingsPrimaryTextColor())
                    Text("品牌主色 · 当前唯一可用", style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor())
                }
                Surface(shape = CircleShape, color = perClipAccentColor(), modifier = Modifier.size(22.dp)) {
                    Box(contentAlignment = Alignment.Center) { Text("✓", color = Color.White, style = MaterialTheme.typography.labelMedium) }
                }
            }
        }
        SettingsGroupTitle("切换说明")
        Surface(
            shape = RoundedCornerShape(22.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
            border = BorderStroke(1.dp, border),
        ) {
            Text(
                "选择后立即生效，并保存到此设备。\n“跟随系统”会响应系统亮色与暗色变化。",
                modifier = Modifier.fillMaxWidth().padding(16.dp),
                style = PerClipSettingsTypography.Supporting,
                color = settingsSecondaryTextColor(),
            )
        }
    }
}

@Composable
private fun AdaptiveThemePreview(border: Color, card: Color) {
    Surface(
        shape = RoundedCornerShape(24.dp),
        color = card,
        border = BorderStroke(1.dp, border),
    ) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth().height(84.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                MiniThemePreview(Color(0xFFFCFAFF), Color.White, Color(0xFFD8CCE3), Modifier.weight(1f))
                MiniThemePreview(ColorTokens.DarkPlumSurface, ColorTokens.DarkPlumRaised, Color(0xFFA99BB1), Modifier.weight(1f))
            }
            Text(
                "跟随系统：设备切换时自动同步",
                modifier = Modifier.fillMaxWidth(),
                style = PerClipSettingsTypography.Supporting,
                color = settingsSecondaryTextColor(),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
}

@Composable
private fun MiniThemePreview(background: Color, card: Color, line: Color, modifier: Modifier) {
    Surface(modifier, shape = RoundedCornerShape(16.dp), color = background, border = BorderStroke(1.dp, line.copy(alpha = .35f))) {
        Row(
            Modifier.padding(10.dp).background(card, RoundedCornerShape(11.dp)).padding(8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Box(Modifier.size(20.dp).background(ColorTokens.DarkPlumAccent, CircleShape))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                Box(Modifier.fillMaxWidth(.88f).height(6.dp).background(line, CircleShape))
                Box(Modifier.fillMaxWidth(.58f).height(5.dp).background(line.copy(alpha = .55f), CircleShape))
            }
        }
    }
}

@Composable
private fun AppearanceModeRow(
    title: String,
    summary: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SettingsIcon(icon, containerSize = 36.dp, iconSize = 18.dp)
        Column(Modifier.weight(1f).padding(start = 14.dp)) {
            Text(title, style = PerClipSettingsTypography.RowTitle, color = settingsPrimaryTextColor())
            Text(summary, style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor())
        }
        RadioButton(
            selected = selected,
            onClick = onClick,
            colors = RadioButtonDefaults.colors(selectedColor = perClipAccentColor()),
        )
    }
}
