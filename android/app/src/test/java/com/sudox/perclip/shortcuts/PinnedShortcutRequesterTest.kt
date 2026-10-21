package com.sudox.perclip.shortcuts

import org.junit.Assert.assertEquals
import org.junit.Test

class PinnedShortcutRequesterTest {
    @Test
    fun exposesStableQuickNotePinnedShortcutId() {
        assertEquals("pinned_quick_note", PinnedShortcutRequester.QUICK_NOTE_PINNED_ID)
    }
}
