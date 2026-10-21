package com.sudox.perclip.knowledge

import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.ui.KnowledgeAttachmentFilter
import com.sudox.perclip.ui.KnowledgeTimeFilter
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import java.security.MessageDigest
import java.time.Instant
import java.time.ZoneId
import java.time.temporal.ChronoUnit

enum class KnowledgeReadMode {
    V2_LOCAL_FIRST,
    LEGACY_QUALITY_READ,
    LOCAL_ONLY,
}

object KnowledgeReadModeResolver {
    fun resolve(configured: Boolean, capability: AppCapabilityResult?, cachedV2: Boolean = false): KnowledgeReadMode = when {
        !configured -> KnowledgeReadMode.LOCAL_ONLY
        capability?.supportsKnowledgeListV2 == true -> KnowledgeReadMode.V2_LOCAL_FIRST
        capability?.contractValid == true && capability.supportsTopicReadModel -> KnowledgeReadMode.LEGACY_QUALITY_READ
        capability?.contractValid == true -> KnowledgeReadMode.LOCAL_ONLY
        cachedV2 -> KnowledgeReadMode.V2_LOCAL_FIRST
        else -> KnowledgeReadMode.LOCAL_ONLY
    }
}

data class KnowledgeListQuery(
    val knowledgeBaseIds: List<String> = emptyList(),
    val text: String = "",
    val source: String = "",
    val sourceType: String = "",
    val attachment: String = "",
    val capturedAfter: String = "",
    val capturedBefore: String = "",
) {
    fun normalized(): KnowledgeListQuery = copy(
        knowledgeBaseIds = knowledgeBaseIds.map(String::trim).filter(String::isNotBlank).distinct().sorted(),
        text = text.trim(),
        source = source.trim(),
        sourceType = sourceType.trim(),
        attachment = attachment.trim(),
        capturedAfter = capturedAfter.trim(),
        capturedBefore = capturedBefore.trim(),
    )

    val key: String
        get() {
            val value = normalized().run {
                listOf(knowledgeBaseIds.joinToString("\u0001"), text, source, sourceType, attachment, capturedAfter, capturedBefore)
                    .joinToString("\u0000")
            }
            return MessageDigest.getInstance("SHA-256").digest(value.toByteArray())
                .joinToString("") { "%02x".format(it) }
        }

    val baseQuery: Boolean
        get() = text.isBlank() && source.isBlank() && sourceType.isBlank() &&
            attachment.isBlank() && capturedAfter.isBlank() && capturedBefore.isBlank()
}

fun knowledgeRemoteQuery(
    knowledgeBaseIds: List<String>,
    text: String,
    source: String,
    type: ClipLibraryTypeFilter,
    attachment: KnowledgeAttachmentFilter,
    time: KnowledgeTimeFilter,
    now: Instant = Instant.now(),
): KnowledgeListQuery = KnowledgeListQuery(
    knowledgeBaseIds = knowledgeBaseIds,
    text = text,
    source = source,
    sourceType = if (type == ClipLibraryTypeFilter.All) "" else type.label,
    attachment = when (attachment) {
        KnowledgeAttachmentFilter.All -> ""
        KnowledgeAttachmentFilter.WithAttachment -> "with"
        KnowledgeAttachmentFilter.WithoutAttachment -> "without"
    },
    capturedAfter = when (time) {
        KnowledgeTimeFilter.All -> ""
        KnowledgeTimeFilter.Today -> now.atZone(ZoneId.systemDefault()).toLocalDate()
            .atStartOfDay(ZoneId.systemDefault()).toInstant().toString()
        else -> time.windowMs?.let { now.minus(it, ChronoUnit.MILLIS).toString() }.orEmpty()
    },
).normalized()

data class KnowledgeListSummary(
    val totalCount: Int? = null,
    val matchingCount: Int? = null,
    val revision: Long = 0,
    val generatedAt: String = "",
)

data class KnowledgeListItem(
    val clip: KnowledgeTopicClip,
    val knowledgeBaseIds: List<String> = emptyList(),
    val knowledgeBaseId: String = knowledgeBaseIds.firstOrNull().orEmpty(),
    val knowledgeBaseName: String = "",
    val sourceType: String = "",
    val hasAttachment: Boolean = false,
    val itemRevision: Long = 0,
    val updatedAt: String = "",
    val correlationIdentity: String = "",
)

data class KnowledgeListPage(
    val scopeKnowledgeBaseIds: List<String>,
    val summary: KnowledgeListSummary,
    val items: List<KnowledgeListItem>,
    val nextCursor: String,
    val hasMore: Boolean,
)

data class KnowledgeChange(
    val revision: Long,
    val publicClipId: String,
    val knowledgeBaseId: String,
    val knowledgeBaseIds: List<String>,
    val operation: String,
    val sourceOperation: String,
    val reason: String,
    val changedAt: String,
    val item: KnowledgeListItem?,
)

data class KnowledgeChangePage(
    val changes: List<KnowledgeChange>,
    val nextRevision: Long,
    val hasMore: Boolean,
    val currentRevision: Long,
)

data class KnowledgeCacheSnapshot(
    val queryKey: String,
    val initialized: Boolean = false,
    val items: List<KnowledgeListItem> = emptyList(),
    val summary: KnowledgeListSummary = KnowledgeListSummary(),
    val nextCursor: String = "",
    val complete: Boolean = false,
    val lastSuccessAt: String = "",
    val lastError: String = "",
    val dirty: Boolean = false,
)

data class KnowledgeRepositoryState(
    val mode: KnowledgeReadMode,
    val snapshot: KnowledgeCacheSnapshot,
    val loading: Boolean = false,
    val refreshing: Boolean = false,
    val offline: Boolean = false,
    val partialSyncFailure: Boolean = false,
    val syncError: String = "",
    val loadingNextPage: Boolean = false,
    val pageLoadFailure: Boolean = false,
    val newContentCount: Int = 0,
    val generation: Long = 0,
)

data class PendingKey(
    val configuration: String,
    val queryKey: String,
)

object KnowledgeIdentityMerge {
    fun remoteIdentity(item: KnowledgeListItem): Set<String> = buildSet {
        add("public:${item.clip.clipId}")
        item.correlationIdentity.takeIf(String::isNotBlank)?.let { add("correlation:$it") }
    }

    fun localCorrelationIdentities(clientRequestIds: List<String>): Set<String> = clientRequestIds
        .filter(String::isNotBlank)
        .mapTo(linkedSetOf()) { "correlation:$it" }
}

object KnowledgeEmptyStatePolicy {
    fun shouldShow(
        cacheReadComplete: Boolean,
        loading: Boolean,
        offline: Boolean,
        partialSyncFailure: Boolean,
        authoritativeCount: Int?,
        remoteItemCount: Int,
        pendingCount: Int,
        failedCount: Int,
        unconfirmedUploadedCount: Int,
        dirty: Boolean,
    ): Boolean = cacheReadComplete && !loading && !offline && !partialSyncFailure && !dirty &&
        authoritativeCount == 0 && remoteItemCount == 0 && pendingCount == 0 && failedCount == 0 &&
        unconfirmedUploadedCount == 0
}
