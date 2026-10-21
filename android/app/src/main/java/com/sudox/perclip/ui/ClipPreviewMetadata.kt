package com.sudox.perclip.ui

import com.sudox.perclip.SharedClip

object ClipPreviewMetadata {
    fun sourceLabel(sourceApp: String): String? {
        val cleaned = sourceApp.trim()
        if (cleaned.isBlank()) return null
        return "来自 $cleaned"
    }

    fun totalSizeLabel(clip: SharedClip): String? {
        if (clip.items.isEmpty()) return null
        return totalSizeLabel(
            itemCount = clip.items.size,
            sizes = clip.items.map { it.sizeBytes },
        )
    }

    fun totalSizeLabel(itemCount: Int, sizes: List<Long?>): String? {
        if (itemCount <= 0) return null
        val knownTotal = sizes.mapNotNull { it }.sum()
        if (knownTotal <= 0L) return null
        val size = formatByteSize(knownTotal)
        return if (itemCount == 1) size else "$itemCount 个文件 · $size"
    }

    fun formatByteSize(sizeBytes: Long?): String? {
        val bytes = sizeBytes ?: return null
        if (bytes < 0L) return null
        if (bytes < 1024L) return "$bytes B"

        val units = listOf("KB", "MB", "GB")
        var value = bytes.toDouble()
        var unitIndex = -1
        while (value >= 1024.0 && unitIndex < units.lastIndex) {
            value /= 1024.0
            unitIndex += 1
        }

        val formatted = if (value >= 100 || value % 1.0 == 0.0) {
            value.toLong().toString()
        } else {
            "%.1f".format(value)
        }
        return "$formatted ${units[unitIndex.coerceAtLeast(0)]}"
    }
}
