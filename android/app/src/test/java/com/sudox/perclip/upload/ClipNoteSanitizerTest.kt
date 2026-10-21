package com.sudox.perclip.upload

import org.junit.Assert.assertEquals
import org.junit.Test

class ClipNoteSanitizerTest {
    @Test
    fun trimsSurroundingWhitespace() {
        assertEquals("补充备注", ClipNoteSanitizer.normalize("  \n补充备注\t "))
    }

    @Test
    fun normalizesWhitespaceOnlyNoteToBlank() {
        assertEquals("", ClipNoteSanitizer.normalize(" \n\t "))
    }
}
