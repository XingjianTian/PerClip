package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip

data class UploadPartMetadata(
    val clientRequestId: String,
    val titleHint: String,
    val clientBatchId: String,
    val parentClientRequestId: String,
    val partIndex: Int,
    val partCount: Int,
    val partRole: String,
    val sourceIntent: String = "share",
)

object UploadPartPlanner {
    fun forClip(clip: SharedClip): UploadPartMetadata {
        return UploadPartMetadata(
            clientRequestId = "${clip.id}:",
            titleHint = clip.titleHint,
            clientBatchId = "",
            parentClientRequestId = "${clip.id}:",
            partIndex = 0,
            partCount = 1,
            partRole = partRoleFor(clip.kind, clip.mimeType),
            sourceIntent = sourceIntentFor(clip),
        )
    }

    fun forItem(
        clip: SharedClip,
        displayName: String,
        mimeType: String = "",
        itemIndex: Int?,
        totalItems: Int,
    ): UploadPartMetadata {
        require(totalItems in 1..100) { "share intent must contain between 1 and 100 items" }
        val cleanDisplayName = displayName.trim()
        val titleHint = if (totalItems > 1) {
            cleanDisplayName.ifBlank { "${clip.titleHint} #${(itemIndex ?: 0) + 1}" }
        } else {
            clip.titleHint
        }

        val safeName = sanitizePartName(cleanDisplayName.ifBlank { "item" })
        val index = itemIndex ?: 0
        val requestId = if (totalItems > 1) {
            "${clip.id}:$index:$safeName"
        } else {
            "${clip.id}:$safeName"
        }

        return UploadPartMetadata(
            clientRequestId = requestId,
            titleHint = titleHint,
            clientBatchId = if (totalItems > 1) clip.id else "",
            parentClientRequestId = "${clip.id}:",
            partIndex = index,
            partCount = totalItems,
            partRole = partRoleFor(clip.kind, mimeType),
            sourceIntent = sourceIntentFor(clip),
        )
    }

    fun toUploadPart(metadata: UploadPartMetadata): UploadPart = UploadPart(
        clientRequestId = metadata.clientRequestId,
        titleHint = metadata.titleHint,
        clientBatchId = metadata.clientBatchId,
        parentClientRequestId = metadata.parentClientRequestId,
        partIndex = metadata.partIndex,
        partCount = metadata.partCount,
        partRole = metadata.partRole,
        sourceIntent = metadata.sourceIntent,
    )

    fun toMetadata(part: UploadPart): UploadPartMetadata = UploadPartMetadata(
        clientRequestId = part.clientRequestId,
        titleHint = part.titleHint,
        clientBatchId = part.clientBatchId,
        parentClientRequestId = part.parentClientRequestId,
        partIndex = part.partIndex,
        partCount = part.partCount,
        partRole = part.partRole,
        sourceIntent = part.sourceIntent,
    )

    fun pendingParts(parts: List<UploadPart>): List<UploadPart> =
        parts.filter { it.state == UploadState.Waiting || it.state == UploadState.Uploading }

    private fun partRoleFor(kind: ClipKind, mimeType: String): String = when {
        mimeType.startsWith("image/", ignoreCase = true) -> "image"
        mimeType.isNotBlank() && kind == ClipKind.Multiple -> "file"
        else -> when (kind) {
            ClipKind.Text, ClipKind.ScreenClip, ClipKind.Unknown -> "text"
            ClipKind.Url -> "url"
            ClipKind.Image -> "image"
            ClipKind.File, ClipKind.Multiple -> "file"
        }
    }

    private fun sourceIntentFor(clip: SharedClip): String = if (clip.sourceApp == "PerClip") "manual" else "share"

    private fun sanitizePartName(name: String): String = name
        .substringAfterLast('/')
        .substringAfterLast('\\')
        .replace(Regex("[^A-Za-z0-9._-]+"), "_")
        .trim('_')
        .ifBlank { "item" }
        .take(80)
}
