package com.sudox.perclip.ui

import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus

object RecentlySavedFeedback {
    fun title(record: UploadRecord): String = when (record.status) {
        UploadStatus.Uploaded -> "已保存，后台处理完成"
        UploadStatus.Uploading -> "已保存，正在后台处理"
        UploadStatus.Failed -> "刚刚保存，等待处理"
        UploadStatus.Waiting -> "刚刚保存"
    }

    fun body(record: UploadRecord): String {
        val title = record.clip.titleHint.ifBlank { "这条内容" }
        val nextStep = when (record.status) {
            UploadStatus.Uploaded -> "后台处理已完成。"
            UploadStatus.Uploading -> "正在后台同步。"
            UploadStatus.Failed -> record.message.ifBlank { "后台同步失败，可以稍后重试。" }
            UploadStatus.Waiting -> record.message.ifBlank { "网络可用后会自动后台同步。" }
        }
        return "$title · $nextStep"
    }

    fun matches(record: UploadRecord, recentlySavedClipId: String?): Boolean =
        recentlySavedClipId != null && record.clip.id == recentlySavedClipId
}
