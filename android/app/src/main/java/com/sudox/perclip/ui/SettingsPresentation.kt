package com.sudox.perclip.ui

import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppCapabilityFailure
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus

data class SettingsDashboardSummary(
    val connection: String,
    val connectionState: SettingsConnectionState,
    val processingQueue: String,
    val waitingCount: Int,
    val failedCount: Int,
)

enum class SettingsConnectionState {
    CHECKING,
    BASIC,
    FULL,
    DISCONNECTED,
}

object SettingsPresentation {
    fun dashboard(
        settings: PerClipSettings,
        capability: AppCapabilityResult?,
        records: List<UploadRecord>,
    ): SettingsDashboardSummary {
        val waiting = records.count { it.status == UploadStatus.Waiting || it.status == UploadStatus.Uploading }
        val failed = records.count { it.status == UploadStatus.Failed }
        val connectionState = when {
            !settings.normalized().hasUploadConfig -> SettingsConnectionState.DISCONNECTED
            capability == null -> SettingsConnectionState.CHECKING
            capability.complete -> SettingsConnectionState.FULL
            capability.contractValid || capability.failure in setOf(
                AppCapabilityFailure.CONTRACT_MISSING,
                AppCapabilityFailure.CONTRACT_MISMATCH,
                AppCapabilityFailure.FEATURES_INCOMPLETE,
                AppCapabilityFailure.INVALID_RESPONSE,
            ) -> SettingsConnectionState.BASIC
            else -> SettingsConnectionState.DISCONNECTED
        }
        return SettingsDashboardSummary(
            connection = when (connectionState) {
                SettingsConnectionState.CHECKING -> "检查中"
                SettingsConnectionState.BASIC -> "基础可用"
                SettingsConnectionState.FULL -> "完整连接"
                SettingsConnectionState.DISCONNECTED -> "未连接"
            },
            connectionState = connectionState,
            processingQueue = when {
                failed > 0 -> "$failed 条失败"
                waiting > 0 -> "$waiting 条待处理"
                else -> "队列为空"
            },
            waitingCount = waiting,
            failedCount = failed,
        )
    }
}
