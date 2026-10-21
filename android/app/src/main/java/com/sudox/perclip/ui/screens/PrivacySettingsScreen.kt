package com.sudox.perclip.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.sudox.perclip.ui.design.PerClipSectionCard

@Composable
fun PrivacySettingsScreen(contentPadding: PaddingValues, onBack: () -> Unit) {
    SettingsPageScaffold(contentPadding, "隐私与安全", onBack = onBack) {
        PerClipSectionCard("安全", "确认当前数据边界和本地可见信息。") {
            Text("Token 默认隐藏；公开网络建议使用 HTTPS，避免 mobile token 明文传输。")
            Text("Android 只保存连接所需配置，服务端处理密钥留在服务端。")
        }
    }
}
