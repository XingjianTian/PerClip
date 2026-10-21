package com.sudox.perclip.share

import org.junit.Assert.assertEquals
import org.junit.Test

class SharingShortcutPublisherTest {
    @Test
    fun exposesStableShareShortcutIdentifiers() {
        assertEquals("save_to_personalclips", SharingShortcutPublisher.SAVE_TO_PERSONALCLIPS_ID)
        assertEquals(
            "com.sudox.perclip.category.SAVE_TO_PERSONALCLIPS",
            SharingShortcutPublisher.SAVE_TO_PERSONALCLIPS_CATEGORY,
        )
    }
}
