package com.sudox.perclip.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.ui.design.PerClipSectionCard

@Composable
fun DiagnosticsSettingsScreen(
    contentPadding: PaddingValues,
    capabilityResult: AppCapabilityResult?,
    onRefresh: () -> Unit,
    onBack: () -> Unit,
) {
    SettingsPageScaffold(contentPadding, "诊断与版本", onBack = onBack) {
        PerClipSectionCard("服务能力与版本", "诊断不接收或显示 token 与完整服务器地址。") {
            Text("App 版本 0.1.0")
            Text(capabilityResult?.message ?: "尚未检查服务能力。")
            Button(onClick = onRefresh, modifier = Modifier.fillMaxWidth()) { Text("重新检查服务能力") }
            Text("手机端不保存 RAGFlow API Key 或其它服务端密钥。")
        }
    }
}
