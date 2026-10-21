package com.sudox.perclip.ui.screens

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.data.QueuedClipMetadata
import com.sudox.perclip.knowledge.ClipTopicAssignment
import com.sudox.perclip.knowledge.KnowledgeReadMode
import com.sudox.perclip.knowledge.TopicLabel
import com.sudox.perclip.ui.KnowledgeRecordState
import com.sudox.perclip.ui.KnowledgeHomeFilters
import com.sudox.perclip.ui.KnowledgeLibraryUiModel
import com.sudox.perclip.ui.KnowledgeTimeFilter
import com.sudox.perclip.upload.ClipLibraryFilter
import com.sudox.perclip.upload.ClipLibraryQuery
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import java.time.Instant
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeMemoryCardPolicyTest {
    @Test
    fun `local card does not promote enrichment tags to formal topics`() {
        val record = UploadRecord(
            clip = SharedClip("local", ClipKind.Text, "Synthetic"),
            status = UploadStatus.Uploaded,
            message = "",
            metadata = QueuedClipMetadata(
                enrichmentTags = listOf("设计", "", "产品", "设计", "规范", "忽略"),
            ),
        )

        assertEquals(emptyList<String>(), KnowledgeMemoryCardPolicy.localTopicLabels(record))
    }

    @Test
    fun `remote card exposes primary and at most one secondary topic`() {
        val assignment = ClipTopicAssignment(
            primary = TopicLabel("design", "设计"),
            secondary = listOf(
                TopicLabel("product", "产品"),
                TopicLabel("spec", "规范"),
                TopicLabel("extra", "忽略"),
            ),
            unclassified = false,
        )

        assertEquals(
            listOf("设计", "产品"),
            KnowledgeMemoryCardPolicy.remoteTopicLabels(assignment),
        )
    }

    @Test
    fun `date label uses time today and date on older days`() {
        val zone = ZoneId.of("Asia/Shanghai")
        val now = Instant.parse("2026-07-27T08:00:00Z").toEpochMilli()

        assertEquals(
            "15:30",
            KnowledgeMemoryCardPolicy.localDateLabel(
                Instant.parse("2026-07-27T07:30:00Z").toEpochMilli(),
                now,
                zone,
            ),
        )
        assertEquals(
            "7月26日",
            KnowledgeMemoryCardPolicy.remoteDateLabel("2026-07-26T07:30:00Z", now, zone),
        )
    }

    @Test
    fun `unified list count includes remote memories`() {
        assertEquals(34, KnowledgeUnifiedListPolicy.visibleCount(localCount = 0, remoteCount = 34))
        assertEquals("共 34 条", KnowledgeUnifiedListPolicy.countLabel(status = null, count = 34))
    }

    @Test
    fun `remote memories participate only in ingested status`() {
        val remote = listOf("one", "two")

        assertEquals(remote, KnowledgeUnifiedListPolicy.remoteItems(remote, status = null))
        assertEquals(remote, KnowledgeUnifiedListPolicy.remoteItems(remote, KnowledgeRecordState.Ingested))
        assertEquals(emptyList<String>(), KnowledgeUnifiedListPolicy.remoteItems(remote, KnowledgeRecordState.Pending))
        assertEquals(emptyList<String>(), KnowledgeUnifiedListPolicy.remoteItems(remote, KnowledgeRecordState.Failed))
        assertEquals("已处理 · 2 条", KnowledgeUnifiedListPolicy.countLabel(KnowledgeRecordState.Ingested, 2))
    }

    @Test
    fun `count labels distinguish v2 authority legacy loaded and local only`() {
        assertEquals(
            "共 501 条",
            KnowledgeCountLabelPolicy.listLabel(KnowledgeReadMode.V2_LOCAL_FIRST, null, 501, 501),
        )
        assertEquals(
            "读取中",
            KnowledgeCountLabelPolicy.listLabel(KnowledgeReadMode.V2_LOCAL_FIRST, null, null, 12),
        )
        assertEquals(
            "已加载 12 条",
            KnowledgeCountLabelPolicy.listLabel(KnowledgeReadMode.LEGACY_QUALITY_READ, null, null, 12),
        )
        assertEquals(
            "已加载 3 条",
            KnowledgeCountLabelPolicy.listLabel(
                KnowledgeReadMode.LEGACY_QUALITY_READ, KnowledgeRecordState.Ingested, null, 3,
            ),
        )
        assertEquals(
            "本机 4 条",
            KnowledgeCountLabelPolicy.listLabel(KnowledgeReadMode.LOCAL_ONLY, null, null, 4),
        )
        assertEquals(501, KnowledgeCountLabelPolicy.cloudTotal(KnowledgeReadMode.V2_LOCAL_FIRST, 501))
        assertEquals(null, KnowledgeCountLabelPolicy.cloudTotal(KnowledgeReadMode.LEGACY_QUALITY_READ, 12))
        assertEquals(null, KnowledgeCountLabelPolicy.cloudTotal(KnowledgeReadMode.LOCAL_ONLY, 4))
    }

    @Test
    fun `unconfirmed uploaded contributes once until remote correlation confirms it`() {
        assertEquals(
            106,
            KnowledgeUnifiedListPolicy.statusCount(
                status = null,
                remoteMatchingCount = 100,
                pendingCount = 3,
                failedCount = 2,
                unconfirmedUploadedCount = 1,
            ),
        )
        assertEquals(
            101,
            KnowledgeUnifiedListPolicy.statusCount(
                status = KnowledgeRecordState.Ingested,
                remoteMatchingCount = 100,
                pendingCount = 0,
                failedCount = 0,
                unconfirmedUploadedCount = 1,
            ),
        )
        assertEquals(
            100,
            KnowledgeUnifiedListPolicy.statusCount(
                status = KnowledgeRecordState.Ingested,
                remoteMatchingCount = 100,
                pendingCount = 0,
                failedCount = 0,
                unconfirmedUploadedCount = 0,
            ),
        )
        assertEquals(
            3,
            KnowledgeUnifiedListPolicy.statusCount(
                status = KnowledgeRecordState.Pending,
                remoteMatchingCount = 100,
                pendingCount = 3,
                failedCount = 2,
                unconfirmedUploadedCount = 1,
            ),
        )
        assertEquals(
            2,
            KnowledgeUnifiedListPolicy.statusCount(
                status = KnowledgeRecordState.Failed,
                remoteMatchingCount = 100,
                pendingCount = 3,
                failedCount = 2,
                unconfirmedUploadedCount = 1,
            ),
        )
    }

    @Test
    fun `pending and failed empty authority ignores unrelated server ingested count`() {
        assertEquals(0, KnowledgeEmptyAuthoritativeCount.forStatus(KnowledgeRecordState.Pending, 501))
        assertEquals(0, KnowledgeEmptyAuthoritativeCount.forStatus(KnowledgeRecordState.Failed, 501))
        assertEquals(501, KnowledgeEmptyAuthoritativeCount.forStatus(KnowledgeRecordState.Ingested, 501))
        assertEquals(501, KnowledgeEmptyAuthoritativeCount.forStatus(null, 501))

        fun empty(status: KnowledgeRecordState, pending: Int = 0, failed: Int = 0) =
            com.sudox.perclip.knowledge.KnowledgeEmptyStatePolicy.shouldShow(
                cacheReadComplete = true,
                loading = false,
                offline = false,
                partialSyncFailure = false,
                authoritativeCount = KnowledgeEmptyAuthoritativeCount.forStatus(status, 501),
                remoteItemCount = 0,
                pendingCount = pending,
                failedCount = failed,
                unconfirmedUploadedCount = 0,
                dirty = false,
            )

        assertTrue(empty(KnowledgeRecordState.Pending))
        assertTrue(empty(KnowledgeRecordState.Failed))
        assertFalse(empty(KnowledgeRecordState.Pending, pending = 1))
        assertFalse(empty(KnowledgeRecordState.Failed, failed = 1))
    }

    @Test
    fun `filtered pending and failed zero remain authoritative empty while unsafe states do not`() {
        val now = Instant.parse("2026-07-28T12:00:00Z").toEpochMilli()
        val pending = localRecord("pending", UploadStatus.Waiting, now - 40L * 24 * 60 * 60 * 1000)
        val failed = localRecord("failed", UploadStatus.Failed, now - 40L * 24 * 60 * 60 * 1000)
        val filtered = listOf(
            ClipLibraryFilter.apply(listOf(pending), ClipLibraryQuery(text = "no match")),
            KnowledgeLibraryUiModel.apply(
                listOf(pending),
                KnowledgeHomeFilters(status = KnowledgeRecordState.Pending, type = ClipLibraryTypeFilter.File),
                now,
            ),
            KnowledgeLibraryUiModel.apply(
                listOf(failed),
                KnowledgeHomeFilters(status = KnowledgeRecordState.Failed, source = "No such platform"),
                now,
            ),
            KnowledgeLibraryUiModel.apply(
                listOf(failed),
                KnowledgeHomeFilters(status = KnowledgeRecordState.Failed, time = KnowledgeTimeFilter.Today),
                now,
            ),
        )
        assertTrue(filtered.all { it.isEmpty() })
        filtered.forEach {
            assertTrue(com.sudox.perclip.knowledge.KnowledgeEmptyStatePolicy.shouldShow(
                true, false, false, false, 0, 0, 0, 0, 0, false,
            ))
        }
        assertFalse(com.sudox.perclip.knowledge.KnowledgeEmptyStatePolicy.shouldShow(
            true, false, true, false, 0, 0, 0, 0, 0, false,
        ))
        assertFalse(com.sudox.perclip.knowledge.KnowledgeEmptyStatePolicy.shouldShow(
            true, false, false, true, 0, 0, 0, 0, 0, false,
        ))
        assertFalse(com.sudox.perclip.knowledge.KnowledgeEmptyStatePolicy.shouldShow(
            true, false, false, false, 0, 0, 0, 0, 0, true,
        ))
    }

    private fun localRecord(id: String, status: UploadStatus, createdAt: Long) = UploadRecord(
        clip = SharedClip(id, ClipKind.Text, "Synthetic $id", text = "safe local fixture"),
        status = status,
        message = "",
        createdAtEpochMs = createdAt,
    )
}
