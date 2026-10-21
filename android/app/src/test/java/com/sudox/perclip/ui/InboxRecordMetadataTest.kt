package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.data.QueuedClipMetadata
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import java.time.Instant
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class InboxRecordMetadataTest {
    @Test
    fun formatsRelativeTimeLabels() {
        val now = 1_000_000_000L

        assertEquals("刚刚", InboxRecordMetadata.relativeTimeLabel(now - 30_000L, now))
        assertEquals("5 分钟前", InboxRecordMetadata.relativeTimeLabel(now - 5 * 60_000L, now))
        assertEquals("3 小时前", InboxRecordMetadata.relativeTimeLabel(now - 3 * 60 * 60_000L, now))
        assertEquals("昨天", InboxRecordMetadata.relativeTimeLabel(now - 25 * 60 * 60_000L, now))
        assertEquals("4 天前", InboxRecordMetadata.relativeTimeLabel(now - 4 * 24 * 60 * 60_000L, now))
        assertNull(InboxRecordMetadata.relativeTimeLabel(0L, now))
    }

    @Test
    fun fallsBackToDateForOlderRecords() {
        assertEquals(
            "2026-06-20",
            InboxRecordMetadata.relativeTimeLabel(
                createdAtEpochMs = Instant.parse("2026-06-20T00:00:00Z").toEpochMilli(),
                nowEpochMs = Instant.parse("2026-06-30T00:00:00Z").toEpochMilli(),
                zoneId = ZoneId.of("UTC"),
            ),
        )
    }

    @Test
    fun buildsSummaryLineForFileRecord() {
        val record = UploadRecord(
            clip = SharedClip(
                id = "clip-1",
                kind = ClipKind.Multiple,
                titleHint = "Batch",
                sourceApp = "Files",
            ),
            status = UploadStatus.Waiting,
            message = "等待后台同步",
            createdAtEpochMs = 1_000_000L,
        )

        assertEquals(
            "5 分钟前 · 多文件 · 来自 Files · 知识库：未记录",
            InboxRecordMetadata.summaryLine(record, nowEpochMs = 1_300_000L, zoneId = ZoneId.of("UTC")),
        )
    }

    @Test
    fun summaryLineIncludesKnowledgeBaseNameWhenRecorded() {
        val record = UploadRecord(
            clip = SharedClip(
                id = "clip-1",
                kind = ClipKind.Text,
                titleHint = "Note",
            ),
            status = UploadStatus.Waiting,
            message = "等待后台同步",
            createdAtEpochMs = 1_000_000L,
            metadata = QueuedClipMetadata(knowledgeBaseName = "Research"),
        )

        assertEquals(
            "5 分钟前 · 文字 · 知识库：Research",
            InboxRecordMetadata.summaryLine(record, nowEpochMs = 1_300_000L, zoneId = ZoneId.of("UTC")),
        )
    }
}
