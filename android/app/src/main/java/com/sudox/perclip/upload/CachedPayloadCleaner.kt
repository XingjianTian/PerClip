package com.sudox.perclip.upload

import com.sudox.perclip.data.QueuedClip
import java.io.File

object CachedPayloadCleaner {
    fun deleteCachedPayloads(clip: QueuedClip, cacheDir: File): Int {
        val cacheRoot = cacheDir.canonicalFile
        var deletedCount = 0
        clip.items
            .map { File(it.cachedPath) }
            .forEach { file ->
                runCatching {
                    val canonicalFile = file.canonicalFile
                    val isCacheFile = canonicalFile == cacheRoot ||
                        canonicalFile.path.startsWith("${cacheRoot.path}${File.separator}")
                    if (isCacheFile && canonicalFile.delete()) {
                        deletedCount += 1
                    }
                }
            }
        return deletedCount
    }
}
