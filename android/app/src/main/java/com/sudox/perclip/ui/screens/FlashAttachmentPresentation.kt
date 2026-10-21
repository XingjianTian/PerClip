package com.sudox.perclip.ui.screens

import com.sudox.perclip.ui.ClipPreviewMetadata

internal data class FlashAttachmentPresentation(
    val typeLabel: String,
    val headline: String?,
    val fileName: String,
    val metadata: String,
    val isAudio: Boolean,
)

internal object FlashAttachmentPresentationPolicy {
    fun forSingleAttachment(
        titleHint: String,
        text: String,
        sourceApp: String,
        displayName: String,
        mimeType: String,
        sizeBytes: Long?,
    ): FlashAttachmentPresentation {
        val isAudio = mimeType.startsWith("audio/", ignoreCase = true)
        val isImage = mimeType.startsWith("image/", ignoreCase = true)
        val fallbackName = if (isAudio) "未命名录音" else "未命名文件"
        val fileName = displayName.trim().ifBlank { fallbackName }
        val cleanedTitle = titleHint.trim()
        val headline = cleanedTitle.takeIf {
            it.isNotBlank() && (text.isNotBlank() || !it.equals(fileName, ignoreCase = true))
        }
        val typeLabel = when {
            isAudio -> "录音"
            isImage -> "图片"
            else -> "文件"
        }
        val metadata = listOfNotNull(
            ClipPreviewMetadata.sourceLabel(sourceApp),
            readableFileType(fileName, mimeType, isAudio, isImage),
            ClipPreviewMetadata.formatByteSize(sizeBytes),
        ).joinToString(" · ")

        return FlashAttachmentPresentation(
            typeLabel = typeLabel,
            headline = headline,
            fileName = fileName,
            metadata = metadata,
            isAudio = isAudio,
        )
    }

    private fun readableFileType(
        fileName: String,
        mimeType: String,
        isAudio: Boolean,
        isImage: Boolean,
    ): String? {
        val extension = fileName.substringAfterLast('.', missingDelimiterValue = "")
            .trim()
            .uppercase()
            .takeIf { it.isNotBlank() && it.length <= 8 }
        return when {
            isAudio -> extension?.let { "$it 音频" } ?: "音频文件"
            isImage -> extension?.let { "$it 图片" } ?: "图片文件"
            extension != null -> "$extension 文件"
            mimeType.isNotBlank() -> mimeType
            else -> null
        }
    }
}
