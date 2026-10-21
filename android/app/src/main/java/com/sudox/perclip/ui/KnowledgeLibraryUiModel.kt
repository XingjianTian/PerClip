package com.sudox.perclip.ui

import com.sudox.perclip.label
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class KnowledgeRecordState(val label: String) {
    Ingested("已处理"),
    Pending("待同步"),
    Failed("失败"),
}

enum class KnowledgeAttachmentFilter(val label: String) {
    All("全部"),
    WithAttachment("有附件"),
    WithoutAttachment("无附件"),
}

enum class KnowledgeTimeFilter(val label: String, val windowMs: Long?) {
    All("全部时间", null),
    Today("今天", 24L * 60 * 60 * 1000),
    Last7Days("近 7 天", 7L * 24 * 60 * 60 * 1000),
    Last30Days("近 30 天", 30L * 24 * 60 * 60 * 1000),
}

data class KnowledgeHomeFilters(
    val status: KnowledgeRecordState? = null,
    val source: String = "",
    val type: ClipLibraryTypeFilter = ClipLibraryTypeFilter.All,
    val attachment: KnowledgeAttachmentFilter = KnowledgeAttachmentFilter.All,
    val time: KnowledgeTimeFilter = KnowledgeTimeFilter.All,
) {
    val activeCount: Int
        get() = listOf(
            status != null,
            source.isNotBlank(),
            type != ClipLibraryTypeFilter.All,
            attachment != KnowledgeAttachmentFilter.All,
            time != KnowledgeTimeFilter.All,
        ).count { it }
}

data class KnowledgeHomeSummary(
    val ingested: Int?,
    val pending: Int,
    val failed: Int,
)

object KnowledgeLibraryUiModel {
    fun toggleStatus(current: KnowledgeRecordState?, selected: KnowledgeRecordState): KnowledgeRecordState? =
        if (current == selected) null else selected

    fun timeLabel(createdAtEpochMs: Long, nowEpochMs: Long = System.currentTimeMillis()): String {
        if (createdAtEpochMs <= 0L) return "时间未知"
        val age = (nowEpochMs - createdAtEpochMs).coerceAtLeast(0L)
        val time = SimpleDateFormat("HH:mm", Locale.CHINA).format(Date(createdAtEpochMs))
        return when {
            age < 24L * 60 * 60 * 1000 -> "今天 $time"
            age < 48L * 60 * 60 * 1000 -> "昨天 $time"
            else -> SimpleDateFormat("M月d日 HH:mm", Locale.CHINA).format(Date(createdAtEpochMs))
        }
    }

    fun state(record: UploadRecord): KnowledgeRecordState = when (record.status) {
        UploadStatus.Waiting, UploadStatus.Uploading -> KnowledgeRecordState.Pending
        UploadStatus.Uploaded -> KnowledgeRecordState.Ingested
        UploadStatus.Failed -> KnowledgeRecordState.Failed
    }

    fun summary(records: List<UploadRecord>, cloudIngestedCount: Int?) = KnowledgeHomeSummary(
        ingested = cloudIngestedCount,
        pending = records.count { state(it) == KnowledgeRecordState.Pending },
        failed = records.count { state(it) == KnowledgeRecordState.Failed },
    )

    fun source(record: UploadRecord): String {
        if (record.clip.sourceApp.isBlank()) return record.clip.kind.label()
        return SourcePlatformResolver.displayName(record.clip.sourceApp, record.clip.url)
    }

    fun sources(records: List<UploadRecord>): List<String> = records.map(::source).distinct().sorted()

    fun apply(
        records: List<UploadRecord>,
        filters: KnowledgeHomeFilters,
        nowEpochMs: Long = System.currentTimeMillis(),
    ): List<UploadRecord> = records.filter { record ->
        (filters.status == null || state(record) == filters.status) &&
            (filters.source.isBlank() || source(record) == filters.source) &&
            filters.type.matches(record) &&
            when (filters.attachment) {
                KnowledgeAttachmentFilter.All -> true
                KnowledgeAttachmentFilter.WithAttachment -> record.clip.items.isNotEmpty()
                KnowledgeAttachmentFilter.WithoutAttachment -> record.clip.items.isEmpty()
            } &&
            (filters.time.windowMs == null || record.createdAtEpochMs <= 0L || nowEpochMs - record.createdAtEpochMs <= filters.time.windowMs)
    }
}
