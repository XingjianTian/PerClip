package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipItem
import java.nio.file.Files
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CachedPayloadCleanerTest {
    @Test
    fun deletesOnlyFilesUnderCacheDirectory() {
        val root = Files.createTempDirectory("perclip-cleaner").toFile()
        val cacheDir = root.resolve("cache").apply { mkdirs() }
        val sharedPayloads = cacheDir.resolve("shared_payloads").apply { mkdirs() }
        val cached = sharedPayloads.resolve("payload.pdf").apply { writeText("cached") }
        val outside = root.resolve("outside.pdf").apply { writeText("outside") }
        val missing = sharedPayloads.resolve("missing.pdf")
        try {
            val deleted = CachedPayloadCleaner.deleteCachedPayloads(
                clip = queuedClip(
                    cached.absolutePath,
                    outside.absolutePath,
                    missing.absolutePath,
                ),
                cacheDir = cacheDir,
            )

            assertEquals(1, deleted)
            assertFalse(cached.exists())
            assertTrue(outside.exists())
        } finally {
            root.deleteRecursively()
        }
    }

    private fun queuedClip(vararg cachedPaths: String): QueuedClip {
        return QueuedClip(
            id = "clip",
            kind = ClipKind.File,
            titleHint = "file",
            text = "",
            url = "",
            mimeType = "application/pdf",
            sourceApp = "",
            note = "",
            items = cachedPaths.mapIndexed { index, path ->
                QueuedClipItem(
                    cachedPath = path,
                    displayName = "file-$index.pdf",
                    mimeType = "application/pdf",
                    sizeBytes = 1L,
                )
            },
            status = UploadStatus.Uploaded,
            message = "",
            remotePath = "",
            createdAtEpochMs = 1L,
        )
    }
}
