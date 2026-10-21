package com.sudox.perclip.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.ui.design.PerClipSectionCard

@Composable
fun UploadSettingsScreen(contentPadding: PaddingValues, settings: PerClipSettings, onChange: (PerClipSettings) -> Unit, onBack: () -> Unit) {
    SettingsPageScaffold(contentPadding, "保存与网络", onBack = onBack) {
        PerClipSectionCard("保存与后台同步", "控制设备名、网络策略和本地队列。") {
            OutlinedTextField(settings.deviceName, { onChange(settings.copy(deviceName = it)) }, Modifier.fillMaxWidth(), label = { Text("默认设备名") }, singleLine = true)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { Text("大文件仅 Wi-Fi 同步", fontWeight = FontWeight.Bold); Text("10MB 以上文件会等待 Wi-Fi 或非计费网络。") }
                PerClipSettingsSwitch(settings.wifiOnlyLargeFiles, { onChange(settings.copy(wifiOnlyLargeFiles = it)) })
            }
            Text("后台同步会在网络恢复后继续处理，失败记录可在闪记库重试。")
        }
    }
}
