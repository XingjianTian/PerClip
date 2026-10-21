package com.sudox.perclip.recall.repository

import java.util.UUID
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

data class RecallDomainRequest(
    val days: Int? = null, val topicLimit: Int = 12, val memoryLimit: Int = 80, val topicId: String = "", val includeMemories: Boolean = true,
    val startDate: String = "", val endDate: String = "", val timezone: String = "",
    val knowledgeBaseId: String = "",
)
data class RecallDomainPresentationDefaults(
    val visibleLabelCount: Int = 3,
    val labelRotationSeconds: Int = 8,
    val defaultDays: Int = 30,
    val includeMemoryLabels: Boolean = true,
    val clientOwnsLayout: Boolean = true,
    val clientOwnsAnimation: Boolean = true,
)
data class RecallDomainTopic(
    val id: String, val label: String = "", val shortLabel: String = "", val clipCount: Int = 0,
    val weight: Double = 0.0, val sizeWeight: Double = 0.0, val colorSlot: Int = 0, val iconSlot: String = "topic",
    val labelPriority: Double = 0.0, val rotationSeed: Int = 0, val lastActivityAt: String = "", val newInWindow: Boolean = false,
    val viewedCount: Int = 0, val deferredCount: Int = 0, val openedOriginalCount: Int = 0, val lastRecalledAt: String = "",
)
data class RecallDomainMemory(
    val id: String, val clipId: String = "", val clientRequestId: String = "", val primaryTopicId: String = "", val topicIds: List<String> = emptyList(),
    val label: String = "", val shortLabel: String = "", val summary: String = "", val safeExcerpt: String = "", val sourceType: String = "",
    val sourceLabel: String = "", val knowledgeBaseName: String = "", val tags: List<String> = emptyList(), val capturedAt: String = "",
    val recallCount: Int = 0, val lastRecalledAt: String = "", val weight: Double = 0.0, val sizeWeight: Double = 0.0,
    val colorSlot: Int = 0, val iconSlot: String = "note", val labelPriority: Double = 0.0, val rotationSeed: Int = 0,
    val viewCount: Int = 0, val deferCount: Int = 0, val openedOriginalCount: Int = 0,
    val lastViewedAt: String = "", val lastDeferredAt: String = "",
)
data class RecallDomainRelation(val source: String, val target: String, val type: String, val weight: Double = 0.0)
data class RecallDomainSnapshot(
    val windowDays: Int = 30, val windowStart: String = "", val windowEnd: String = "", val snapshotKey: String = "",
    val topics: List<RecallDomainTopic> = emptyList(), val memories: List<RecallDomainMemory> = emptyList(), val relations: List<RecallDomainRelation> = emptyList(),
    val presentationDefaults: RecallDomainPresentationDefaults = RecallDomainPresentationDefaults(),
    /** Stable identity of the canonical source snapshot; [snapshotKey] also includes projection inputs. */
    val canonicalSnapshotKey: String = "",
)

data class RecallResurfaceRequest(
    val days: Int? = null, val limit: Int = 8, val cursor: String = "", val topicId: String = "", val excludeClipIds: List<String> = emptyList(),
    val startDate: String = "", val endDate: String = "", val timezone: String = "",
    val knowledgeBaseId: String = "",
)
data class RecallResurfaceItem(
    val clipId: String, val clientRequestId: String = "", val topicId: String = "", val topicLabel: String = "", val title: String = "",
    val summary: String = "", val safeExcerpt: String = "", val sourceType: String = "", val sourceLabel: String = "", val knowledgeBaseName: String = "",
    val tags: List<String> = emptyList(), val capturedAt: String = "", val lastViewedAt: String = "", val viewCount: Int = 0, val deferCount: Int = 0,
    val score: Double = 0.0, val reasonCodes: List<String> = emptyList(),
)
data class RecallResurfacePage(
    val snapshotKey: String = "", val cursor: String = "", val nextCursor: String = "", val items: List<RecallResurfaceItem> = emptyList(),
    val windowDays: Int = 0, val windowStart: String = "", val windowEnd: String = "",
)

data class RecallInteractionRequest(
    val surface: String, val action: String, val nodeId: String = "", val topicId: String = "", val clipId: String = "", val sessionId: String = "",
    val metadata: RecallInteractionMetadata = RecallInteractionMetadata(), val clientEventId: String = UUID.randomUUID().toString(), val occurredAt: String = "",
)
data class RecallInteractionMetadata(
    val visibleLabelCount: Int? = null,
    val rotationIndex: Int? = null,
    val dwellMs: Int? = null,
    val position: Int? = null,
    val source: String? = null,
)
data class RecallInteractionTarget(val nodeId: String = "", val topicId: String = "", val clipId: String = "")
data class RecallInteractionResult(
    val accepted: Boolean = true,
    val eventId: String = "",
    val replayed: Boolean = false,
    val target: RecallInteractionTarget = RecallInteractionTarget(),
)
data class RecallSuppressedItem(
    val clipId: String,
    val title: String = "",
    val summary: String = "",
    val suppressedAt: String = "",
)
data class RecallSuppressionPage(
    val items: List<RecallSuppressedItem> = emptyList(),
    val cursor: String = "",
    val previousCursor: String = "",
    val nextCursor: String = "",
    val limit: Int = 50,
)

private fun windowMatches(
    days: Int,
    start: String,
    end: String,
    requested: MemoryPlanetWindow,
): Boolean {
    if (days != requested.days) return false
    if (requested.kind != "custom") return true
    return runCatching {
        val zone = ZoneId.of(requested.timezone)
        val actualStart = Instant.parse(start).atZone(zone).toLocalDate()
        val actualEnd = Instant.parse(end).atZone(zone).toLocalDate().minusDays(1)
        actualStart == LocalDate.parse(requested.startDate) &&
            actualEnd == LocalDate.parse(requested.endDate)
    }.getOrDefault(false)
}

fun RecallDomainSnapshot.matches(requested: MemoryPlanetWindow) =
    windowMatches(windowDays, windowStart, windowEnd, requested)

fun RecallResurfacePage.matches(requested: MemoryPlanetWindow) =
    windowMatches(windowDays, windowStart, windowEnd, requested)
data class RecallPreferences(
    val visibleLabelCount: Int = 3, val labelRotationSeconds: Int = 8, val defaultDays: Int = 30,
    val preferredTopicIds: List<String> = emptyList(), val mutedTopicIds: List<String> = emptyList(), val includeMemoryLabels: Boolean = true,
)
data class RecallPreferencesPatch(
    val visibleLabelCount: Int? = null, val labelRotationSeconds: Int? = null, val defaultDays: Int? = null,
    val preferredTopicIds: List<String>? = null, val mutedTopicIds: List<String>? = null, val includeMemoryLabels: Boolean? = null,
)
