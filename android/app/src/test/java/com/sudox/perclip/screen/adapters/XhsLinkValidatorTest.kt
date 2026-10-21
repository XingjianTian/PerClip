package com.sudox.perclip.screen.adapters

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class XhsLinkValidatorTest {
    @Test
    fun acceptsXhsHosts() {
        assertTrue(XhsLinkValidator.isXhsUrl("https://xhslink.com/a/b"))
        assertTrue(XhsLinkValidator.isXhsUrl("https://www.xiaohongshu.com/explore/abc"))
    }

    @Test
    fun rejectsNonXhsHosts() {
        assertFalse(XhsLinkValidator.isXhsUrl("https://example.com/a"))
        assertFalse(XhsLinkValidator.isXhsUrl(""))
    }

    @Test
    fun extractsFirstXhsUrlFromClipboardText() {
        val text = "看看这个 https://example.com/no 和 https://xhslink.com/o/abc 戳进小红书"

        assertEquals("https://xhslink.com/o/abc", XhsLinkValidator.extractXhsUrl(text))
    }
}
