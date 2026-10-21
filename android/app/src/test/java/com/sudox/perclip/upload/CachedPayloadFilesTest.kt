package com.sudox.perclip.upload

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CachedPayloadFilesTest {
    @Test
    fun createsDistinctCacheNamesForSameDisplayName() {
        val first = CachedPayloadFiles.cacheFileName("report.pdf", uniquePrefix = "clip-a")
        val second = CachedPayloadFiles.cacheFileName("report.pdf", uniquePrefix = "clip-b")

        assertNotEquals(first, second)
        assertTrue(first.endsWith("-report.pdf"))
        assertTrue(second.endsWith("-report.pdf"))
    }

    @Test
    fun recreationReusesRequestScopedCacheNameButIndependentShareDoesNot() {
        val firstPrefix = CachedPayloadFiles.captureRequestPrefix("request-1", 0)
        val replayPrefix = CachedPayloadFiles.captureRequestPrefix("request-1", 0)
        val nextSharePrefix = CachedPayloadFiles.captureRequestPrefix("request-2", 0)

        assertEquals(
            CachedPayloadFiles.cacheFileName("report.pdf", firstPrefix),
            CachedPayloadFiles.cacheFileName("report.pdf", replayPrefix),
        )
        assertNotEquals(
            CachedPayloadFiles.cacheFileName("report.pdf", firstPrefix),
            CachedPayloadFiles.cacheFileName("report.pdf", nextSharePrefix),
        )
    }

    @Test
    fun sanitizesDisplayNameForCachePath() {
        assertEquals("report_final.pdf", CachedPayloadFiles.safeFileName("../../report final.pdf"))
        assertEquals("中文文件.docx", CachedPayloadFiles.safeFileName("中文文件.docx"))
        assertEquals("perclip_upload", CachedPayloadFiles.safeFileName("???"))
    }

    @Test
    fun validatesCachedFileAvailability() {
        val temp = File.createTempFile("perclip", ".txt")
        try {
            assertTrue(CachedPayloadFiles.isUsable(temp))
            assertFalse(CachedPayloadFiles.isUsable(File(temp.parentFile, "missing.txt")))
            assertFalse(CachedPayloadFiles.isUsable(null))
        } finally {
            temp.delete()
        }
    }
}
