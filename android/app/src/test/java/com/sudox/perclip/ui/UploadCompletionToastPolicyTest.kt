package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadCompletionToastPolicyTest {
    @Test
    fun consumesUploadedBaselineWithoutReplayingIt() {
        val evaluation = UploadCompletionToastPolicy.evaluate(
            records = listOf(record(id = "old-upload", status = UploadStatus.Uploaded)),
            state = UploadCompletionToastPolicy.State(),
        )

        assertTrue(evaluation.newlyUploadedClipIds.isEmpty())
        assertEquals(setOf("old-upload"), evaluation.state.announcedUploadedClipIds)
    }

    @Test
    fun announcesShareEquivalentRecordThatAppearsAfterBaseline() {
        val baseline = UploadCompletionToastPolicy.evaluate(
            records = emptyList(),
            state = UploadCompletionToastPolicy.State(),
        )
        val completed = UploadCompletionToastPolicy.evaluate(
            records = listOf(record(id = "share-1", status = UploadStatus.Uploaded)),
            state = baseline.state,
        )

        assertEquals(listOf("share-1"), completed.newlyUploadedClipIds)
    }

    @Test
    fun announcesEveryOutstandingCompletionExactlyOnce() {
        val baseline = UploadCompletionToastPolicy.evaluate(
            records = listOf(
                record(id = "flash-1", status = UploadStatus.Waiting),
                record(id = "share-1", status = UploadStatus.Waiting),
            ),
            state = UploadCompletionToastPolicy.State(),
        )
        val firstCompletion = UploadCompletionToastPolicy.evaluate(
            records = listOf(
                record(id = "flash-1", status = UploadStatus.Uploaded),
                record(id = "share-1", status = UploadStatus.Waiting),
            ),
            state = baseline.state,
        )
        val bothComplete = UploadCompletionToastPolicy.evaluate(
            records = listOf(
                record(id = "flash-1", status = UploadStatus.Uploaded),
                record(id = "share-1", status = UploadStatus.Uploaded),
            ),
            state = firstCompletion.state,
        )
        val unchanged = UploadCompletionToastPolicy.evaluate(
            records = listOf(
                record(id = "flash-1", status = UploadStatus.Uploaded),
                record(id = "share-1", status = UploadStatus.Uploaded),
            ),
            state = bothComplete.state,
        )

        assertEquals(listOf("flash-1"), firstCompletion.newlyUploadedClipIds)
        assertEquals(listOf("share-1"), bothComplete.newlyUploadedClipIds)
        assertTrue(unchanged.newlyUploadedClipIds.isEmpty())
        assertEquals(setOf("flash-1", "share-1"), unchanged.state.announcedUploadedClipIds)
    }

    private fun record(id: String, status: UploadStatus): UploadRecord {
        return UploadRecord(
            clip = SharedClip(
                id = id,
                kind = ClipKind.Text,
                titleHint = "note",
                text = "hello",
                mimeType = "text/plain",
            ),
            status = status,
            message = "",
        )
    }
}
