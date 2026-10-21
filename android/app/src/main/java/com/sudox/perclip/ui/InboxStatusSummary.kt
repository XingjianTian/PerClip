package com.sudox.perclip.ui

import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus

data class InboxStatusSnapshot(
    val total: Int,
    val uploaded: Int,
    val pending: Int,
    val failed: Int,
) {
    val healthLabel: String
        get() = when {
            total == 0 -> "暂无记录"
            failed > 0 -> "$failed 条需要处理"
            pending > 0 -> "$pending 条待同步"
            else -> "全部已保存"
        }
}

object InboxStatusSummary {
    fun from(records: List<UploadRecord>): InboxStatusSnapshot {
        val uploaded = records.count { record -> record.status == UploadStatus.Uploaded }
        val pending = records.count { record ->
            record.status == UploadStatus.Waiting || record.status == UploadStatus.Uploading
        }
        val failed = records.count { record -> record.status == UploadStatus.Failed }
        return InboxStatusSnapshot(
            total = records.size,
            uploaded = uploaded,
            pending = pending,
            failed = failed,
        )
    }
}
