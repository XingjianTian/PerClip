package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import org.junit.Assert.assertEquals
import org.junit.Test

class InboxStatusSummaryTest {
    @Test
    fun countsUploadedPendingAndFailedRecords() {
        val summary = InboxStatusSummary.from(
            listOf(
                record(UploadStatus.Uploaded),
                record(UploadStatus.Waiting),
                record(UploadStatus.Uploading),
                record(UploadStatus.Failed),
            ),
        )

        assertEquals(4, summary.total)
        assertEquals(1, summary.uploaded)
        assertEquals(2, summary.pending)
        assertEquals(1, summary.failed)
    }

    @Test
    fun prioritizesHealthLabelsByActionability() {
        assertEquals("暂无记录", InboxStatusSummary.from(emptyList()).healthLabel)
        assertEquals("全部已保存", InboxStatusSummary.from(listOf(record(UploadStatus.Uploaded))).healthLabel)
        assertEquals("1 条待同步", InboxStatusSummary.from(listOf(record(UploadStatus.Waiting))).healthLabel)
        assertEquals(
            "1 条需要处理",
            InboxStatusSummary.from(
                listOf(
                    record(UploadStatus.Waiting),
                    record(UploadStatus.Failed),
                ),
            ).healthLabel,
        )
    }

    private fun record(status: UploadStatus): UploadRecord {
        return UploadRecord(
            clip = SharedClip(
                id = "clip-$status",
                kind = ClipKind.Text,
                titleHint = "Note",
            ),
            status = status,
            message = "",
        )
    }
}
