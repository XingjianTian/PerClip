package com.sudox.perclip.upload

import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.nio.file.Files
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CachedPayloadWriterTest {
    @Test
    fun writesCacheFileOnlyAfterSuccessfulCopy() {
        val dir = Files.createTempDirectory("perclip-cache-writer").toFile()
        try {
            val target = dir.resolve("payload.bin")

            CachedPayloadWriter.copyToFile(ByteArrayInputStream(byteArrayOf(1, 2, 3)), target)

            assertTrue(target.isFile)
            assertArrayEquals(byteArrayOf(1, 2, 3), target.readBytes())
            assertTrue(dir.listFiles().orEmpty().none { it.name.contains(".tmp-") })
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test
    fun removesTemporaryFileWhenCopyFails() {
        val dir = Files.createTempDirectory("perclip-cache-writer-fail").toFile()
        try {
            val target = dir.resolve("payload.bin")

            try {
                CachedPayloadWriter.copyToFile(FailingInputStream(), target)
            } catch (_: IOException) {
                // Expected.
            }

            assertFalse(target.exists())
            assertTrue(dir.listFiles().orEmpty().none { it.name.contains(".tmp-") })
        } finally {
            dir.deleteRecursively()
        }
    }

    private class FailingInputStream : InputStream() {
        private var emittedBytes = 0

        override fun read(): Int {
            if (emittedBytes++ < 2) {
                return emittedBytes
            }
            throw IOException("simulated source failure")
        }
    }
}
