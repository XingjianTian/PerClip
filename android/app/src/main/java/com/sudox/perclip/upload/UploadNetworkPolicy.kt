package com.sudox.perclip.upload

import androidx.work.NetworkType
import com.sudox.perclip.data.QueuedClip

object UploadNetworkPolicy {
    const val LARGE_FILE_THRESHOLD_BYTES = 10L * 1024L * 1024L
    const val CONFIG_MISSING_MESSAGE = "等待完成连接设置"

    fun requiredNetworkType(clip: QueuedClip, wifiOnlyLargeFiles: Boolean): NetworkType {
        if (!wifiOnlyLargeFiles) return NetworkType.CONNECTED
        return if (clip.totalKnownBytes() >= LARGE_FILE_THRESHOLD_BYTES) {
            NetworkType.UNMETERED
        } else {
            NetworkType.CONNECTED
        }
    }

    fun describeWaitingState(
        clip: QueuedClip,
        wifiOnlyLargeFiles: Boolean,
        uploadConfigured: Boolean = true,
    ): String {
        if (!uploadConfigured) return CONFIG_MISSING_MESSAGE
        return when (requiredNetworkType(clip, wifiOnlyLargeFiles)) {
            NetworkType.UNMETERED -> "等待 Wi-Fi 后自动同步"
            else -> "等待网络后自动同步"
        }
    }

    private fun QueuedClip.totalKnownBytes(): Long {
        return items.sumOf { it.sizeBytes ?: 0L }
    }
}
