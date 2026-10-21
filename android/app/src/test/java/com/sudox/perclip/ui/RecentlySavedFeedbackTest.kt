package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecentlySavedFeedbackTest {
    @Test
    fun labelsWaitingClipAsJustSaved() {
        val record = record(status = UploadStatus.Waiting, message = "等待 Wi-Fi 后自动同步")

        assertEquals("刚刚保存", RecentlySavedFeedback.title(record))
        assertEquals("网页摘录 · 等待 Wi-Fi 后自动同步", RecentlySavedFeedback.body(record))
    }

    @Test
    fun labelsUploadedClipAsArchived() {
        val record = record(status = UploadStatus.Uploaded)

        assertEquals("已保存，后台处理完成", RecentlySavedFeedback.title(record))
        assertEquals("网页摘录 · 后台处理已完成。", RecentlySavedFeedback.body(record))
    }

    @Test
    fun failedClipUsesActualFailureMessageWhenPresent() {
        val record = record(
            status = UploadStatus.Failed,
            message = "无法读取分享文件，请从原 App 重新分享。",
        )

        assertEquals(
            "网页摘录 · 无法读取分享文件，请从原 App 重新分享。",
            RecentlySavedFeedback.body(record),
        )
    }

    @Test
    fun matchesOnlyTheRecentlySavedClip() {
        val record = record(id = "clip-1")

        assertTrue(RecentlySavedFeedback.matches(record, "clip-1"))
        assertFalse(RecentlySavedFeedback.matches(record, "clip-2"))
        assertFalse(RecentlySavedFeedback.matches(record, null))
    }

    private fun record(
        id: String = "clip-1",
        status: UploadStatus = UploadStatus.Waiting,
        message: String = "",
    ) = UploadRecord(
        clip = SharedClip(
            id = id,
            kind = ClipKind.Url,
            titleHint = "网页摘录",
            text = "https://example.com",
            mimeType = "text/plain",
        ),
        status = status,
        message = message,
    )
}
