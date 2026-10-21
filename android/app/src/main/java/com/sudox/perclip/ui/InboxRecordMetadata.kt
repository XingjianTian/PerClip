package com.sudox.perclip.ui

import com.sudox.perclip.label
import com.sudox.perclip.upload.UploadRecord
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

object InboxRecordMetadata {
    private const val MINUTE_MS = 60_000L
    private const val HOUR_MS = 60L * MINUTE_MS
    private const val DAY_MS = 24L * HOUR_MS
    private val DateFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd")

    fun summaryLine(
        record: UploadRecord,
        nowEpochMs: Long = System.currentTimeMillis(),
        zoneId: ZoneId = ZoneId.systemDefault(),
    ): String {
        val clip = record.clip
        val fileSummary = ClipPreviewMetadata.totalSizeLabel(clip)
            ?: if (clip.items.size > 1) "${clip.items.size} 个文件" else null

        return listOfNotNull(
            relativeTimeLabel(record.createdAtEpochMs, nowEpochMs, zoneId),
            clip.kind.label(),
            ClipPreviewMetadata.sourceLabel(clip.sourceApp),
            knowledgeBaseLabel(record),
            fileSummary,
        ).joinToString(" · ")
    }

    fun knowledgeBaseLabel(record: UploadRecord): String {
        return "知识库：${record.metadata.knowledgeBaseName.trim().ifBlank { "未记录" }}"
    }

    fun relativeTimeLabel(
        createdAtEpochMs: Long,
        nowEpochMs: Long = System.currentTimeMillis(),
        zoneId: ZoneId = ZoneId.systemDefault(),
    ): String? {
        if (createdAtEpochMs <= 0L) return null

        val ageMs = (nowEpochMs - createdAtEpochMs).coerceAtLeast(0L)
        return when {
            ageMs < MINUTE_MS -> "刚刚"
            ageMs < HOUR_MS -> "${ageMs / MINUTE_MS} 分钟前"
            ageMs < DAY_MS -> "${ageMs / HOUR_MS} 小时前"
            ageMs < 2L * DAY_MS -> "昨天"
            ageMs < 7L * DAY_MS -> "${ageMs / DAY_MS} 天前"
            else -> DateFormatter.withZone(zoneId).format(Instant.ofEpochMilli(createdAtEpochMs))
        }
    }
}
