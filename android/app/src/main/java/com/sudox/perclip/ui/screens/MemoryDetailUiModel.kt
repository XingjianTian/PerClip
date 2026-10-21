package com.sudox.perclip.ui.screens

import com.sudox.perclip.knowledge.KnowledgeTopicClip
import com.sudox.perclip.knowledge.ClipTopicAssignment
import com.sudox.perclip.ui.InboxRecordPresentation
import com.sudox.perclip.ui.SourcePlatform
import com.sudox.perclip.ui.SourcePlatformResolver
import com.sudox.perclip.upload.UploadRecord
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal sealed interface MemoryDetailSource {
    val stableKey: String

    data class Local(val localClipId: String) : MemoryDetailSource {
        override val stableKey: String = localClipId
    }

    data class Remote(val publicClipId: String) : MemoryDetailSource {
        override val stableKey: String = publicClipId
    }
}

internal data class MemoryDetailUiModel(
    val source: MemoryDetailSource,
    val title: String,
    val capturedAt: String = "",
    val sourceLabel: String = "",
    val topics: MemoryDetailTopics = MemoryDetailTopics(),
    val body: MemoryDetailBody = MemoryDetailBody.empty(),
)

internal enum class MemoryDetailBodyKind { ORIGINAL_TEXT, ORIGINAL_URL, EMPTY }

internal data class MemoryDetailBody(
    val kind: MemoryDetailBodyKind,
    val value: String,
) {
    companion object {
        fun text(value: String) = MemoryDetailBody(MemoryDetailBodyKind.ORIGINAL_TEXT, value.trim())
        fun url(value: String) = MemoryDetailBody(MemoryDetailBodyKind.ORIGINAL_URL, value.trim())
        fun empty() = MemoryDetailBody(MemoryDetailBodyKind.EMPTY, "")
    }
}

internal object MemoryDetailBodyPolicy {
    fun fromLocal(record: UploadRecord): MemoryDetailBody {
        val originalText = listOf(
            record.clip.text,
            record.metadata.extractedText,
        ).firstOrNull { it.isNotBlank() }
        if (originalText != null) return MemoryDetailBody.text(originalText)
        if (record.clip.url.isNotBlank()) return MemoryDetailBody.url(record.clip.url)
        val fallbackText = listOf(
            record.note,
            record.clip.items.joinToString("\n") { it.displayName },
        ).firstOrNull { it.isNotBlank() }
        if (fallbackText != null) return MemoryDetailBody.text(fallbackText)
        return MemoryDetailBody.empty()
    }

    fun fromRemote(clip: KnowledgeTopicClip): MemoryDetailBody = when {
        clip.originalText.isNotBlank() -> MemoryDetailBody.text(clip.originalText)
        clip.textPreview.isNotBlank() -> MemoryDetailBody.text(clip.textPreview)
        clip.safeDisplayUrl.isNotBlank() -> MemoryDetailBody.url(clip.safeDisplayUrl)
        else -> MemoryDetailBody.empty()
    }
}

internal enum class MemoryDetailTopicStyle { ACTIVE, DISABLED }

internal data class MemoryDetailTopics(
    val labels: List<String> = emptyList(),
    val style: MemoryDetailTopicStyle = MemoryDetailTopicStyle.ACTIVE,
    val statusLabel: String = "",
)

internal object MemoryDetailTopicPolicy {
    fun fromLocal(@Suppress("UNUSED_PARAMETER") record: UploadRecord): MemoryDetailTopics = MemoryDetailTopics()

    fun fromRemote(assignment: ClipTopicAssignment): MemoryDetailTopics {
        val labels = if (assignment.unclassified) {
            listOf("待归类")
        } else {
            assignment.cardTopics
                .map { it.displayName }
                .filter(String::isNotBlank)
                .distinct()
        }
        val disabled = assignment.topicDisabled && !assignment.unclassified && labels.isNotEmpty()
        return MemoryDetailTopics(
            labels = labels,
            style = if (disabled) MemoryDetailTopicStyle.DISABLED else MemoryDetailTopicStyle.ACTIVE,
            statusLabel = if (disabled) assignment.statusLabel else "",
        )
    }
}

internal object MemoryDetailSourceLabelPolicy {
    fun fromLocal(record: UploadRecord): String {
        val sourceApp = record.clip.sourceApp.trim()
        if (sourceApp.isBlank()) return ""
        val platform = SourcePlatformResolver.resolve(sourceApp, record.clip.url)
        return if (platform == SourcePlatform.Generic || platform == SourcePlatform.Files) "" else platform.displayName
    }
}

internal enum class MemoryDetailMetadataLayout { NONE, DATE_ONLY, SOURCE_ONLY, BOTH }

internal object MemoryDetailMetadataPolicy {
    fun resolve(capturedAt: String, sourceLabel: String): MemoryDetailMetadataLayout = when {
        capturedAt.isBlank() && sourceLabel.isBlank() -> MemoryDetailMetadataLayout.NONE
        capturedAt.isNotBlank() && sourceLabel.isBlank() -> MemoryDetailMetadataLayout.DATE_ONLY
        capturedAt.isBlank() -> MemoryDetailMetadataLayout.SOURCE_ONLY
        else -> MemoryDetailMetadataLayout.BOTH
    }
}

internal object MemoryDetailDatePolicy {
    private val formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm", Locale.CHINA)

    fun fromEpochMillis(epochMillis: Long, zoneId: ZoneId): String =
        epochMillis.takeIf { it > 0L }
            ?.let { Instant.ofEpochMilli(it).atZone(zoneId).format(formatter) }
            .orEmpty()

    fun fromRemote(value: String, zoneId: ZoneId): String {
        val raw = value.trim()
        if (raw.isBlank()) return ""
        val instant = runCatching { Instant.parse(raw) }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(raw).toInstant() }.getOrNull()
        if (instant != null) return instant.atZone(zoneId).format(formatter)
        val local = runCatching { LocalDateTime.parse(raw) }.getOrNull()
        if (local != null) return local.format(formatter)

        // Malformed legacy values still must not leak raw ISO separators or precision.
        return raw
            .replace('T', ' ')
            .substringBefore('.')
            .removeSuffix("Z")
            .take(16)
            .trim()
    }
}

internal object MemoryDetailActionsPolicy {
    fun shouldShow(source: MemoryDetailSource, actionsAvailable: Boolean): Boolean =
        actionsAvailable && source is MemoryDetailSource.Local
}

internal object MemoryDetailUiModelFactory {
    fun fromLocal(record: UploadRecord, zoneId: ZoneId = ZoneId.systemDefault()): MemoryDetailUiModel {
        return MemoryDetailUiModel(
            source = MemoryDetailSource.Local(record.clip.id),
            title = InboxRecordPresentation.title(record),
            capturedAt = MemoryDetailDatePolicy.fromEpochMillis(record.createdAtEpochMs, zoneId),
            sourceLabel = MemoryDetailSourceLabelPolicy.fromLocal(record),
            topics = MemoryDetailTopicPolicy.fromLocal(record),
            body = MemoryDetailBodyPolicy.fromLocal(record),
        )
    }

    fun fromRemote(
        clip: KnowledgeTopicClip,
        zoneId: ZoneId = ZoneId.systemDefault(),
    ): MemoryDetailUiModel = MemoryDetailUiModel(
        source = MemoryDetailSource.Remote(clip.clipId),
        title = clip.title,
        capturedAt = MemoryDetailDatePolicy.fromRemote(clip.capturedAt, zoneId),
        sourceLabel = clip.source.trim(),
        topics = MemoryDetailTopicPolicy.fromRemote(clip.topicAssignment),
        body = MemoryDetailBodyPolicy.fromRemote(clip),
    )
}

internal data class MemoryListAnchor(
    val stableKey: String = "",
    val fallbackIndex: Int = 0,
    val offset: Int = 0,
)

internal object MemoryDetailAnchorPolicy {
    fun resolve(anchor: MemoryListAnchor, currentKeys: List<String>): Int {
        if (currentKeys.isEmpty()) return 0
        val exact = currentKeys.indexOf(anchor.stableKey)
        if (exact >= 0) return exact
        return anchor.fallbackIndex.coerceIn(0, currentKeys.lastIndex)
    }
}

internal enum class MemoryCardClickTarget { DETAIL, MENU }

internal object MemoryCardClickPolicy {
    fun target(menuHit: Boolean): MemoryCardClickTarget =
        if (menuHit) MemoryCardClickTarget.MENU else MemoryCardClickTarget.DETAIL
}
