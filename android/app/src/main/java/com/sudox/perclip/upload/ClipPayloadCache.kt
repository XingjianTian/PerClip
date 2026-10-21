package com.sudox.perclip.upload

import android.content.Context
import com.sudox.perclip.SharedClipItem
import java.io.File

class ClipPayloadCache(private val context: Context) {
    fun copyToCache(item: SharedClipItem, uniquePrefix: String): File {
        val dir = File(context.cacheDir, "shared_payloads").apply { mkdirs() }
        val file = File(dir, CachedPayloadFiles.cacheFileName(item.displayName, uniquePrefix))
        context.contentResolver.openInputStream(item.uri).use { input ->
            requireNotNull(input) { "Unable to open shared file stream: ${item.displayName}" }
            CachedPayloadWriter.copyToFile(input, file)
        }
        return file
    }
}
