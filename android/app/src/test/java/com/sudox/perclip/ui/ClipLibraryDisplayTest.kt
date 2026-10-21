package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.data.QueuedClipMetadata
import com.sudox.perclip.upload.ClipLibraryFilter
import com.sudox.perclip.upload.ClipLibraryQuery
import com.sudox.perclip.upload.ClipLibraryStatusFilter
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ClipLibraryDisplayTest {
    @Test
    fun overviewMetricsExposeClickableSelectedFilters() {
        val summary = InboxStatusSummary.from(
            listOf(
                record(id = "waiting", status = UploadStatus.Waiting),
                record(id = "uploading", status = UploadStatus.Uploading),
                record(id = "uploaded", status = UploadStatus.Uploaded),
                record(id = "failed", status = UploadStatus.Failed),
            ),
        )

        val metrics = ClipLibraryOverviewModel.metrics(summary, ClipLibraryStatusFilter.Waiting)

        assertEquals(listOf("全部", "待处理", "已保存", "失败"), metrics.map { it.label })
        assertEquals(listOf(4, 2, 1, 1), metrics.map { it.value })
        assertTrue(metrics.single { it.filter == ClipLibraryStatusFilter.Waiting }.selected)
    }

    @Test
    fun typeFilterSummaryKeepsHomeScreenCompact() {
        assertEquals("全部类型", ClipLibraryTypeFilterModel.summary(ClipLibraryTypeFilter.All))
        assertEquals("text", ClipLibraryTypeFilterModel.summary(ClipLibraryTypeFilter.Text))
        assertEquals("url", ClipLibraryTypeFilterModel.summary(ClipLibraryTypeFilter.Url))
        assertEquals("image", ClipLibraryTypeFilterModel.summary(ClipLibraryTypeFilter.Image))
        assertEquals("file", ClipLibraryTypeFilterModel.summary(ClipLibraryTypeFilter.File))
        assertEquals("screen_clip", ClipLibraryTypeFilterModel.summary(ClipLibraryTypeFilter.ScreenClip))
    }

    @Test
    fun combinedSearchTypeAndStatusFilteringStillWorks() {
        val records = listOf(
            record(
                id = "match",
                kind = ClipKind.Url,
                status = UploadStatus.Uploaded,
                metadata = QueuedClipMetadata(enrichmentTags = listOf("research")),
            ),
            record(id = "wrong-type", kind = ClipKind.Text, status = UploadStatus.Uploaded),
            record(id = "wrong-status", kind = ClipKind.Url, status = UploadStatus.Waiting),
        )

        val filtered = ClipLibraryFilter.apply(
            records,
            ClipLibraryQuery(
                text = "research",
                statusFilter = ClipLibraryStatusFilter.Uploaded,
                typeFilter = ClipLibraryTypeFilter.Url,
            ),
        )

        assertEquals(listOf("match"), filtered.map { it.clip.id })
    }

    @Test
    fun cardModelPrefersEnrichmentSummaryAndShowsBadges() {
        val model = ClipLibraryCardModelBuilder.from(
            record(
                id = "clip",
                text = "原始正文",
                status = UploadStatus.Uploaded,
                metadata = QueuedClipMetadata(
                    enrichmentStatus = "completed",
                    enrichmentSummary = "处理后的摘要",
                    ragflowSyncOperation = "upload_document",
                    ragflowSyncStatus = "planned",
                ),
            ),
        )

        assertEquals("处理后的摘要", model.summary)
        assertTrue(model.badges.any { it.label == "已保存" })
        assertTrue(model.badges.any { it.label == "已处理" })
        assertTrue(model.badges.any { it.label == "已规划" })
        assertFalse(model.showDeleteAsPrimaryAction)
    }

    @Test
    fun failedCardShowsRetryEntry() {
        val model = ClipLibraryCardModelBuilder.from(record(id = "failed", status = UploadStatus.Failed))

        assertTrue(model.canRetry)
        assertTrue(model.badges.any { it.label == "同步失败" })
    }

    private fun record(
        id: String,
        kind: ClipKind = ClipKind.Text,
        text: String = "",
        status: UploadStatus = UploadStatus.Waiting,
        metadata: QueuedClipMetadata = QueuedClipMetadata(),
    ): UploadRecord {
        return UploadRecord(
            clip = SharedClip(
                id = id,
                kind = kind,
                titleHint = id,
                text = text,
            ),
            status = status,
            message = status.name,
            metadata = metadata,
        )
    }
}
