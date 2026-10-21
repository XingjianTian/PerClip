package com.sudox.perclip.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.notifications.QuickEntryNotificationHelper
import com.sudox.perclip.notifications.QuickEntryNotificationState
import com.sudox.perclip.screen.ScreenCaptureAccessibilityStatus
import com.sudox.perclip.shortcuts.PinShortcutResult
import com.sudox.perclip.shortcuts.PinnedShortcutRequester
import com.sudox.perclip.ui.design.PerClipSectionCard

@Composable
fun QuickEntrySettingsScreen(
    contentPadding: PaddingValues,
    settings: PerClipSettings,
    onRequestNotificationPermission: () -> Unit,
    onChange: (PerClipSettings) -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val notifications = remember { QuickEntryNotificationHelper(context) }
    val shortcutSupported = remember { PinnedShortcutRequester.isSupported(context) }
    var accessibilityEnabled by remember { mutableStateOf(ScreenCaptureAccessibilityStatus.isEnabled(context)) }
    var message by remember { mutableStateOf("") }
    SettingsPageScaffold(contentPadding, "快捷入口", onBack = onBack) {
        PerClipSectionCard("通知与系统入口", "控制通知栏、截屏和桌面入口。") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { Text("通知栏闪记入口", fontWeight = FontWeight.Bold); Text("点击通知捕获当前屏幕内容。") }
                PerClipSettingsSwitch(settings.persistentQuickEntry, { enabled ->
                    onChange(settings.copy(persistentQuickEntry = enabled))
                    if (enabled) onRequestNotificationPermission()
                    message = when (notifications.sync(enabled)) {
                        QuickEntryNotificationState.Visible -> "通知栏入口已开启。"
                        QuickEntryNotificationState.PermissionRequired -> "需要允许通知权限后才能显示入口。"
                        QuickEntryNotificationState.Cancelled -> "通知栏入口已关闭。"
                    }
                })
            }
            Button({ context.startActivity(ScreenCaptureAccessibilityStatus.settingsIntent()); accessibilityEnabled = ScreenCaptureAccessibilityStatus.isEnabled(context) }, Modifier.fillMaxWidth()) {
                Text(if (accessibilityEnabled) "检查无障碍设置" else "去开启无障碍服务")
            }
            Button({
                message = when (PinnedShortcutRequester.requestQuickNote(context)) {
                    PinShortcutResult.Requested -> "已请求固定，请按系统提示确认。"
                    PinShortcutResult.NotSupported -> "当前启动器不支持固定快捷方式。"
                    PinShortcutResult.Failed -> "固定快捷方式请求未被系统接受。"
                }
            }, Modifier.fillMaxWidth(), enabled = shortcutSupported) { Text(if (shortcutSupported) "固定到桌面" else "启动器不支持固定") }
            if (message.isNotBlank()) Text(message)
        }
    }
}
