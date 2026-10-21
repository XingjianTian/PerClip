package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class InboxRecordPresentationTest {
    @Test
    fun infersReadableTitleWhenStoredTitleIsGeneric() {
        val record = record(
            titleHint = "PerClip smoke",
            text = "外网域名入库测试 https://xhslink.com/o/perclip-public-domain-test 戳进【小红书】看看这篇好文！",
            url = "https://xhslink.com/o/perclip-public-domain-test",
        )

        assertEquals("外网域名入库测试", InboxRecordPresentation.title(record))
        assertEquals("https://xhslink.com/o/perclip-public-domain-test", InboxRecordPresentation.summary(record))
    }

    @Test
    fun keepsRealSourceTitleOverInferredText() {
        val record = record(
            titleHint = "浏览器标题",
            text = "正文标题 https://example.com/read",
            url = "https://example.com/read",
        )

        assertEquals("浏览器标题", InboxRecordPresentation.title(record))
    }

    @Test
    fun includesRemotePathOnlyInExpandedDetails() {
        val record = record(
            titleHint = "浏览器标题",
            text = "正文标题 https://example.com/read",
            url = "https://example.com/read",
            remotePath = "/srv/personal-clips/url/2026/demo.html",
        )

        val details = InboxRecordPresentation.detailLines(record)

        assertTrue(details.any { (label, _) -> label == "存放地址" })
    }

    private fun record(
        titleHint: String,
        text: String,
        url: String,
        remotePath: String = "",
    ): UploadRecord = UploadRecord(
        clip = SharedClip(
            id = "clip-1",
            kind = ClipKind.Url,
            titleHint = titleHint,
            text = text,
            url = url,
            sourceApp = "小红书",
        ),
        status = UploadStatus.Uploaded,
        message = "已保存，后台处理完成。",
        remotePath = remotePath,
        createdAtEpochMs = 1_000L,
    )
}
