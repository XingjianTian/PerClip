package com.sudox.perclip.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ClipPreviewMetadataTest {
    @Test
    fun formatsByteSizesForPreview() {
        assertEquals("0 B", ClipPreviewMetadata.formatByteSize(0))
        assertEquals("512 B", ClipPreviewMetadata.formatByteSize(512))
        assertEquals("1 KB", ClipPreviewMetadata.formatByteSize(1024))
        assertEquals("1.5 KB", ClipPreviewMetadata.formatByteSize(1536))
        assertEquals("2 MB", ClipPreviewMetadata.formatByteSize(2 * 1024 * 1024))
        assertNull(ClipPreviewMetadata.formatByteSize(null))
        assertNull(ClipPreviewMetadata.formatByteSize(-1))
    }

    @Test
    fun buildsTotalSizeLabelForMultipleItems() {
        assertEquals("2 个文件 · 3 KB", ClipPreviewMetadata.totalSizeLabel(2, listOf(1024, 2048)))
        assertEquals("3 KB", ClipPreviewMetadata.totalSizeLabel(1, listOf(3072)))
        assertNull(ClipPreviewMetadata.totalSizeLabel(1, listOf(null)))
    }

    @Test
    fun omitsBlankSourceLabels() {
        assertNull(ClipPreviewMetadata.sourceLabel(""))
        assertEquals("来自 Browser", ClipPreviewMetadata.sourceLabel(" Browser "))
    }

}
