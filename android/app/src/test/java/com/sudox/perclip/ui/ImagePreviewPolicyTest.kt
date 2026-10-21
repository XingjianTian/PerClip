package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ImagePreviewPolicyTest {
    @Test
    fun showsThumbnailForImageClip() {
        assertTrue(ImagePreviewPolicy.shouldShowThumbnail(ClipKind.Image, listOf("application/octet-stream")))
    }

    @Test
    fun showsThumbnailWhenFirstMimeTypeIsImage() {
        assertTrue(ImagePreviewPolicy.shouldShowThumbnail(ClipKind.File, listOf("image/png")))
    }

    @Test
    fun skipsThumbnailForNonImageFiles() {
        assertFalse(ImagePreviewPolicy.shouldShowThumbnail(ClipKind.File, listOf("application/pdf")))
        assertFalse(ImagePreviewPolicy.shouldShowThumbnail(ClipKind.Text, emptyList()))
    }
}
