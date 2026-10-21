package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import org.junit.Assert.assertEquals
import org.junit.Test

class KnowledgeLibraryUiModelTest {
    @Test fun mapsQueueStatesToThreeUserStates() {
        assertEquals(KnowledgeRecordState.Pending, KnowledgeLibraryUiModel.state(record("a", UploadStatus.Waiting)))
        assertEquals(KnowledgeRecordState.Pending, KnowledgeLibraryUiModel.state(record("b", UploadStatus.Uploading)))
        assertEquals(KnowledgeRecordState.Ingested, KnowledgeLibraryUiModel.state(record("c", UploadStatus.Uploaded)))
        assertEquals(KnowledgeRecordState.Failed, KnowledgeLibraryUiModel.state(record("d", UploadStatus.Failed)))
    }

    @Test fun summaryUsesCloudCountAndOnlyLocalExceptionQueueCounts() {
        val summary = KnowledgeLibraryUiModel.summary(
            records = listOf(record("a", UploadStatus.Waiting), record("b", UploadStatus.Uploading), record("c", UploadStatus.Uploaded), record("d", UploadStatus.Failed)),
            cloudIngestedCount = 34,
        )
        assertEquals(KnowledgeHomeSummary(34, 2, 1), summary)
    }

    @Test fun combinesPlatformTypeAttachmentAndTimeFilters() {
        val now = 10_000_000_000L
        val matching = record("x", UploadStatus.Uploaded, "com.zhihu.android", ClipKind.File, false, now - 1000)
        val records = listOf(matching, record("y", UploadStatus.Uploaded, "com.xingin.xhs", ClipKind.Url, false, now - 1000), record("z", UploadStatus.Uploaded, "com.zhihu.android", ClipKind.File, false, now - 40L * 24 * 60 * 60 * 1000))
        val result = KnowledgeLibraryUiModel.apply(records, KnowledgeHomeFilters(KnowledgeRecordState.Ingested, "知乎", ClipLibraryTypeFilter.File, KnowledgeAttachmentFilter.WithoutAttachment, KnowledgeTimeFilter.Last30Days), now)
        assertEquals(listOf("x"), result.map { it.clip.id })
    }

    @Test fun detectsApprovedPlatformLabels() {
        assertEquals("小红书", KnowledgeLibraryUiModel.source(record("x", source = "com.xingin.xhs")))
        assertEquals("知乎", KnowledgeLibraryUiModel.source(record("z", source = "com.zhihu.android")))
        assertEquals("微信", KnowledgeLibraryUiModel.source(record("w", source = "com.tencent.mm")))
        assertEquals("Chrome", KnowledgeLibraryUiModel.source(record("c", source = "com.android.chrome")))
    }

    @Test fun summaryMetricTogglesItsStatusFilter() {
        assertEquals(KnowledgeRecordState.Failed, KnowledgeLibraryUiModel.toggleStatus(null, KnowledgeRecordState.Failed))
        assertEquals(null, KnowledgeLibraryUiModel.toggleStatus(KnowledgeRecordState.Failed, KnowledgeRecordState.Failed))
        assertEquals(KnowledgeRecordState.Ingested, KnowledgeLibraryUiModel.toggleStatus(KnowledgeRecordState.Failed, KnowledgeRecordState.Ingested))
    }

    @Test fun legacyLocalSavedFilterRestoresAsPending() {
        val restored = com.sudox.perclip.ui.screens.KnowledgeHomeFiltersSavePolicy.decode(
            listOf("LocalSaved", "", "All", "All", "All"),
        )
        assertEquals(KnowledgeRecordState.Pending, restored.status)
    }

    @Test fun relativeTimeUsesUserFacingTodayYesterdayAndFallbackLabels() {
        val now = 2_000_000_000_000L
        assertEquals("时间未知", KnowledgeLibraryUiModel.timeLabel(0L, now))
        assert(KnowledgeLibraryUiModel.timeLabel(now - 60_000L, now).startsWith("今天 "))
        assert(KnowledgeLibraryUiModel.timeLabel(now - 25L * 60 * 60 * 1000, now).startsWith("昨天 "))
        assert(!KnowledgeLibraryUiModel.timeLabel(now - 72L * 60 * 60 * 1000, now).contains("今天"))
    }

    private fun record(id: String, status: UploadStatus = UploadStatus.Waiting, source: String = "", kind: ClipKind = ClipKind.Text, attachment: Boolean = false, createdAt: Long = 1L): UploadRecord {
        return UploadRecord(SharedClip(id, kind, id, sourceApp = source), status, "", createdAtEpochMs = createdAt)
    }
}
