package com.sudox.perclip.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.config.SettingsValidation
import com.sudox.perclip.knowledge.KnowledgeBaseApi
import com.sudox.perclip.knowledge.KnowledgeBaseApiResult
import com.sudox.perclip.knowledge.RagflowProbeSummary
import com.sudox.perclip.ui.design.PerClipSectionCard
import com.sudox.perclip.ui.ConnectionVerificationPolicy
import com.sudox.perclip.ui.RagflowConnectionPresentation
import com.sudox.perclip.ui.RagflowConnectionTone
import com.sudox.perclip.upload.PersonalClipsApi
import com.sudox.perclip.upload.UploadResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun ServerSettingsScreen(
    contentPadding: PaddingValues,
    settings: PerClipSettings,
    capabilityResult: AppCapabilityResult?,
    capabilityLoading: Boolean,
    onSettingsChange: (PerClipSettings) -> Unit,
    onConnectionVerified: () -> Int,
    onRequestCapabilityRefresh: () -> Unit,
    onBack: () -> Unit,
    verifyConnection: suspend (PerClipSettings) -> UploadResult = { PersonalClipsApi().health(it) },
) {
    var apiUrl by remember(settings.apiUrl) { mutableStateOf(settings.apiUrl) }
    var apiUrlVisible by remember { mutableStateOf(false) }
    var token by remember(settings.ingestToken) { mutableStateOf(settings.ingestToken) }
    var tokenVisible by remember { mutableStateOf(false) }
    var checking by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }
    var ragflowChecking by remember(apiUrl, token) { mutableStateOf(false) }
    var ragflowResult by remember(apiUrl, token) {
        mutableStateOf<KnowledgeBaseApiResult<RagflowProbeSummary>?>(null)
    }
    val validation = remember(apiUrl, token) { SettingsValidation.validate(apiUrl, token) }
    val scope = rememberCoroutineScope()
    val knowledgeBaseApi = remember { KnowledgeBaseApi() }
    val ragflowStatus = RagflowConnectionPresentation.status(ragflowChecking, ragflowResult)
    SettingsPageScaffold(contentPadding, "连接设置", "地址与凭据仅在此页可见", onBack) {
        PerClipSectionCard("服务器连接", "保存与高级功能能力分别检查。") {
            OutlinedTextField(
                if (apiUrlVisible) apiUrl else if (apiUrl.isBlank()) "" else "已配置（地址已隐藏）",
                { if (apiUrlVisible) { apiUrl = it; onSettingsChange(settings.copy(apiUrl = it)) } },
                Modifier.fillMaxWidth(),
                label = { Text("服务地址") },
                singleLine = true,
                isError = validation.apiUrlError != null,
                readOnly = !apiUrlVisible,
                trailingIcon = {
                    IconButton({ apiUrlVisible = !apiUrlVisible }) {
                        Icon(if (apiUrlVisible) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility, null)
                    }
                },
                supportingText = { Text(validation.apiUrlError ?: validation.apiUrlWarning ?: "例如 https://perclip.example.com") },
            )
            OutlinedTextField(
                token,
                { token = it; onSettingsChange(settings.copy(ingestToken = it)) },
                Modifier.fillMaxWidth(),
                label = { Text("连接令牌") },
                singleLine = true,
                isError = validation.tokenError != null,
                visualTransformation = if (tokenVisible) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    IconButton({ tokenVisible = !tokenVisible }) {
                        Icon(if (tokenVisible) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility, null)
                    }
                },
                supportingText = { Text(validation.tokenError ?: "只保存连接令牌，不保存服务端处理密钥。") },
            )
            Button(
                onClick = {
                    checking = true
                    message = "正在测试保存连接…"
                    val snapshot = settings.copy(apiUrl = apiUrl, ingestToken = token)
                    scope.launch {
                        val health = withContext(Dispatchers.IO) { verifyConnection(snapshot) }
                        val policy = ConnectionVerificationPolicy.evaluate(health.ok, capabilityResult)
                        if (policy.shouldRequeue) {
                            val requeued = onConnectionVerified()
                            message = "保存连接正常。重新排队 $requeued 条待同步记录。"
                            onRequestCapabilityRefresh()
                        } else {
                            message = health.message
                        }
                        checking = false
                    }
                },
                enabled = !checking && validation.isValid,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (checking) "正在测试" else "测试连接") }
            if (message.isNotBlank()) Text(message)
            if (capabilityLoading) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                    Text("正在检查高级功能…")
                }
            } else capabilityResult?.let {
                Text(
                    when {
                        it.complete -> "完整功能可用：${it.message}"
                        it.contractValid -> "部分功能可用：${it.message}"
                        else -> "高级功能不可用：${it.message}"
                    },
                    style = PerClipSettingsTypography.Supporting,
                    color = settingsSecondaryTextColor(),
                )
            }
        }
        PerClipSectionCard(
            "RAGFlow 检查",
            "由 PerClip 服务端代理执行，Android 不保存 RAGFlow 密钥。",
        ) {
            Text(
                ragflowStatus.title,
                style = PerClipSettingsTypography.RowTitle,
                color = when (ragflowStatus.tone) {
                    RagflowConnectionTone.SUCCESS -> KimiSettingsColors.KnowledgeBase
                    RagflowConnectionTone.ERROR -> MaterialTheme.colorScheme.error
                    RagflowConnectionTone.WARNING -> MaterialTheme.colorScheme.primary
                    RagflowConnectionTone.NEUTRAL -> settingsPrimaryTextColor()
                },
            )
            Text(
                ragflowStatus.detail,
                style = PerClipSettingsTypography.Supporting,
                color = settingsSecondaryTextColor(),
            )
            OutlinedButton(
                onClick = {
                    ragflowChecking = true
                    ragflowResult = null
                    val snapshot = settings.copy(apiUrl = apiUrl, ingestToken = token)
                    scope.launch {
                        ragflowResult = withContext(Dispatchers.IO) { knowledgeBaseApi.ragflowProbe(snapshot) }
                        ragflowChecking = false
                    }
                },
                enabled = !ragflowChecking && validation.isValid,
                modifier = Modifier.fillMaxWidth(),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.primary),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.primary),
            ) {
                Text(if (ragflowChecking) "正在检查" else "检查 RAGFlow")
            }
        }
    }
}
