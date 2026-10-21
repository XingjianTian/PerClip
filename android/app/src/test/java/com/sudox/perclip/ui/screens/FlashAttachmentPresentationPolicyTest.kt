package com.sudox.perclip.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FlashAttachmentPresentationPolicyTest {
    @Test
    fun recordingUsesOneFileNameAndUnifiedMetadata() {
        val presentation = FlashAttachmentPresentationPolicy.forSingleAttachment(
            titleHint = "录音-20260810-221725.m4a",
            text = "",
            sourceApp = "PerClip",
            displayName = "录音-20260810-221725.m4a",
            mimeType = "audio/mp4",
            sizeBytes = 6042,
        )

        assertEquals("录音", presentation.typeLabel)
        assertNull(presentation.headline)
        assertEquals("录音-20260810-221725.m4a", presentation.fileName)
        assertEquals("来自 PerClip · M4A 音频 · 5.9 KB", presentation.metadata)
    }

    @Test
    fun customTitleRemainsWhenItIsNotTheFileName() {
        val presentation = FlashAttachmentPresentationPolicy.forSingleAttachment(
            titleHint = "项目访谈",
            text = "",
            sourceApp = "Recorder",
            displayName = "meeting-final.m4a",
            mimeType = "audio/mp4",
            sizeBytes = 1024,
        )

        assertEquals("项目访谈", presentation.headline)
        assertEquals("来自 Recorder · M4A 音频 · 1 KB", presentation.metadata)
    }

    @Test
    fun unnamedAudioGetsAStableFallback() {
        val presentation = FlashAttachmentPresentationPolicy.forSingleAttachment(
            titleHint = "",
            text = "",
            sourceApp = "",
            displayName = "",
            mimeType = "audio/mp4",
            sizeBytes = null,
        )

        assertEquals("未命名录音", presentation.fileName)
        assertEquals("音频文件", presentation.metadata)
    }
}
