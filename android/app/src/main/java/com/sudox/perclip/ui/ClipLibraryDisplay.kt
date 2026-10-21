package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.label
import com.sudox.perclip.ui.design.PerClipStatusTone
import com.sudox.perclip.upload.ClipLibraryStatusFilter
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadRetryEligibility
import com.sudox.perclip.upload.UploadStatus

data class StatusFilterMetric(
    val filter: ClipLibraryStatusFilter,
    val label: String,
    val value: Int,
    val selected: Boolean,
    val tone: PerClipStatusTone,
)

object ClipLibraryOverviewModel {
    fun metrics(
        summary: InboxStatusSnapshot,
        selectedFilter: ClipLibraryStatusFilter,
    ): List<StatusFilterMetric> = listOf(
        StatusFilterMetric(
            filter = ClipLibraryStatusFilter.All,
            label = "全部",
            value = summary.total,
            selected = selectedFilter == ClipLibraryStatusFilter.All,
            tone = PerClipStatusTone.Neutral,
        ),
        StatusFilterMetric(
            filter = ClipLibraryStatusFilter.Waiting,
            label = "待处理",
            value = summary.pending,
            selected = selectedFilter == ClipLibraryStatusFilter.Waiting,
            tone = PerClipStatusTone.Pending,
        ),
        StatusFilterMetric(
            filter = ClipLibraryStatusFilter.Uploaded,
            label = "已保存",
            value = summary.uploaded,
            selected = selectedFilter == ClipLibraryStatusFilter.Uploaded,
            tone = PerClipStatusTone.Success,
        ),
        StatusFilterMetric(
            filter = ClipLibraryStatusFilter.Failed,
            label = "失败",
            value = summary.failed,
            selected = selectedFilter == ClipLibraryStatusFilter.Failed,
            tone = PerClipStatusTone.Danger,
        ),
    )
}

object ClipLibraryTypeFilterModel {
    fun summary(filter: ClipLibraryTypeFilter): String = when (filter) {
        ClipLibraryTypeFilter.All -> "全部类型"
        ClipLibraryTypeFilter.Text -> "text"
        ClipLibraryTypeFilter.Url -> "url"
        ClipLibraryTypeFilter.Image -> "image"
        ClipLibraryTypeFilter.File -> "file"
        ClipLibraryTypeFilter.ScreenClip -> "screen_clip"
    }
}

data class ClipLibraryBadgeModel(
    val label: String,
    val tone: PerClipStatusTone,
)

data class ClipLibraryCardModel(
    val title: String,
    val metadataLine: String,
    val summary: String,
    val badges: List<ClipLibraryBadgeModel>,
    val canRetry: Boolean,
    val showDeleteAsPrimaryAction: Boolean,
)

object ClipLibraryCardModelBuilder {
    fun from(record: UploadRecord): ClipLibraryCardModel {
        return ClipLibraryCardModel(
            title = InboxRecordPresentation.title(record),
            metadataLine = InboxRecordMetadata.summaryLine(record),
            summary = InboxRecordPresentation.summary(record),
            badges = buildList {
                add(uploadBadge(record.status))
                add(enrichmentBadge(record))
                syncBadge(record)?.let { add(it) }
            },
            canRetry = UploadRetryEligibility.canRetry(record),
            showDeleteAsPrimaryAction = false,
        )
    }

    private fun uploadBadge(status: UploadStatus): ClipLibraryBadgeModel = when (status) {
        UploadStatus.Waiting -> ClipLibraryBadgeModel("待同步", PerClipStatusTone.Pending)
        UploadStatus.Uploading -> ClipLibraryBadgeModel("同步中", PerClipStatusTone.Pending)
        UploadStatus.Uploaded -> ClipLibraryBadgeModel("已保存", PerClipStatusTone.Success)
        UploadStatus.Failed -> ClipLibraryBadgeModel("同步失败", PerClipStatusTone.Danger)
    }

    private fun enrichmentBadge(record: UploadRecord): ClipLibraryBadgeModel {
        return when (record.metadata.enrichmentStatus.ifBlank { inferEnrichmentStatus(record) }) {
            "completed" -> ClipLibraryBadgeModel("已处理", PerClipStatusTone.Success)
            "running" -> ClipLibraryBadgeModel("处理中", PerClipStatusTone.Pending)
            "failed" -> ClipLibraryBadgeModel("处理失败", PerClipStatusTone.Danger)
            "skipped" -> ClipLibraryBadgeModel("已跳过", PerClipStatusTone.Neutral)
            else -> ClipLibraryBadgeModel("待处理", PerClipStatusTone.Neutral)
        }
    }

    private fun syncBadge(record: UploadRecord): ClipLibraryBadgeModel? {
        val status = record.metadata.ragflowSyncStatus
        val operation = record.metadata.ragflowSyncOperation
        return when {
            status == "planned" -> ClipLibraryBadgeModel("已规划", PerClipStatusTone.Planned)
            status == "blocked" -> ClipLibraryBadgeModel("同步阻塞", PerClipStatusTone.Danger)
            status == "failed" -> ClipLibraryBadgeModel("规划失败", PerClipStatusTone.Danger)
            status == "skipped" -> ClipLibraryBadgeModel("跳过同步", PerClipStatusTone.Neutral)
            operation.isNotBlank() -> ClipLibraryBadgeModel("待同步", PerClipStatusTone.Planned)
            else -> null
        }
    }

    private fun inferEnrichmentStatus(record: UploadRecord): String {
        return if (
            record.metadata.enrichmentSummary.isNotBlank() ||
            record.metadata.summary.isNotBlank() ||
            record.metadata.extractedText.isNotBlank()
        ) {
            "completed"
        } else {
            ""
        }
    }
}

fun ClipKind.shortTypeLabel(): String = when (this) {
    ClipKind.ScreenClip -> "screen_clip"
    ClipKind.Multiple -> "file"
    else -> label()
}
