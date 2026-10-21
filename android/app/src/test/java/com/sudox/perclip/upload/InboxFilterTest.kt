package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InboxFilterTest {
    @Test
    fun allFilterMatchesEveryRecord() {
        assertTrue(InboxFilter.All.matches(record(ClipKind.Url)))
        assertTrue(InboxFilter.All.matches(record(ClipKind.Text)))
        assertTrue(InboxFilter.All.matches(record(ClipKind.ScreenClip)))
        assertTrue(InboxFilter.All.matches(record(ClipKind.Image)))
        assertTrue(InboxFilter.All.matches(record(ClipKind.File)))
        assertTrue(InboxFilter.All.matches(record(ClipKind.Multiple)))
    }

    @Test
    fun fileFilterIncludesSingleAndMultipleFiles() {
        assertTrue(InboxFilter.Files.matches(record(ClipKind.File)))
        assertTrue(InboxFilter.Files.matches(record(ClipKind.Multiple)))
        assertFalse(InboxFilter.Files.matches(record(ClipKind.Image)))
    }

    @Test
    fun typeFiltersMatchOnlyTheirKind() {
        assertTrue(InboxFilter.Urls.matches(record(ClipKind.Url)))
        assertFalse(InboxFilter.Urls.matches(record(ClipKind.Text)))

        assertTrue(InboxFilter.Texts.matches(record(ClipKind.Text)))
        assertTrue(InboxFilter.Texts.matches(record(ClipKind.ScreenClip)))
        assertFalse(InboxFilter.Texts.matches(record(ClipKind.Url)))

        assertTrue(InboxFilter.Images.matches(record(ClipKind.Image)))
        assertFalse(InboxFilter.Images.matches(record(ClipKind.File)))
    }

    private fun record(kind: ClipKind): UploadRecord {
        return UploadRecord(
            clip = SharedClip(
                id = kind.name,
                kind = kind,
                titleHint = kind.name,
            ),
            status = UploadStatus.Waiting,
            message = "",
        )
    }
}
