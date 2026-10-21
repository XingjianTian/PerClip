package com.sudox.perclip.upload

import java.io.File
import java.util.UUID

object CachedPayloadFiles {
    const val MISSING_FILE_MESSAGE = "本地缓存文件丢失，请从原 App 重新分享。"

    fun cacheFileName(displayName: String, uniquePrefix: String = UUID.randomUUID().toString()): String {
        return "${safeFileName(uniquePrefix)}-${safeFileName(displayName)}"
    }

    fun captureRequestPrefix(clipId: String, itemIndex: Int): String {
        return "${safeFileName(clipId)}-$itemIndex"
    }

    fun isUsable(cachedFile: File?): Boolean {
        return cachedFile?.isFile == true
    }

    fun safeFileName(name: String): String {
        val cleaned = name.substringAfterLast('/').replace(Regex("""[^A-Za-z0-9._\-\u4e00-\u9fff]+"""), "_")
        return cleaned.trim('.', '_').take(MAX_FILE_NAME_LENGTH).ifBlank { "perclip_upload" }
    }

    private const val MAX_FILE_NAME_LENGTH = 120
}
