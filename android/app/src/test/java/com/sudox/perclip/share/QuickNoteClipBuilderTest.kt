package com.sudox.perclip.share

import com.sudox.perclip.ClipKind
import org.junit.Assert.assertEquals
import org.junit.Test

class QuickNoteClipBuilderTest {
    @Test
    fun buildsUrlClipWhenQuickNoteContainsUrl() {
        val clip = QuickNoteClipBuilder.build(
            text = "今晚阅读：https://example.com/article。",
            id = "quick-1",
        )

        assertEquals("quick-1", clip.id)
        assertEquals(ClipKind.Url, clip.kind)
        assertEquals("今晚阅读", clip.titleHint)
        assertEquals("https://example.com/article", clip.url)
        assertEquals("text/plain", clip.mimeType)
        assertEquals("PerClip", clip.sourceApp)
    }

    @Test
    fun buildsTextClipForPlainQuickNote() {
        val clip = QuickNoteClipBuilder.build(
            text = "明天整理 PersonalClips 标签",
            id = "quick-2",
        )

        assertEquals("quick-2", clip.id)
        assertEquals(ClipKind.Text, clip.kind)
        assertEquals("文字闪记", clip.titleHint)
        assertEquals("", clip.url)
        assertEquals("明天整理 PersonalClips 标签", clip.text)
    }
}
