package com.sudox.perclip.recall

import java.util.UUID

/** Server-derived Recall contract. These models deliberately have no file paths, remote IDs, or credentials. */
data class RecallWindow(val days: Int = 7, val start: String = "", val end: String = "")

data class RecallMetrics(
    val eligibleClipCount: Int = 0,
    val recallCount: Int = 0,
    val newTopicCount: Int = 0,
    val reviewedRatio: Double = 0.0,
)

data class RecallGraph(val nodes: List<RecallGraphNode> = emptyList(), val edges: List<RecallGraphEdge> = emptyList())
data class RecallGraphNode(val id: String, val type: String, val label: String, val weight: Int = 0, val colorSlot: Int = 0, val topicId: String = "", val clipId: String = "")
data class RecallGraphEdge(val source: String, val target: String, val type: String, val weight: Int = 0)

data class RecallHighlight(
    val type: String = "", val title: String, val subtitle: String = "", val topicId: String = "", val clipId: String = "", val clientRequestId: String = "", val occurredAt: String = "",
)

data class RecallOverview(
    val window: RecallWindow = RecallWindow(), val metrics: RecallMetrics = RecallMetrics(), val graph: RecallGraph = RecallGraph(), val highlights: List<RecallHighlight> = emptyList(),
) {
    val days get() = window.days
    val rangeStart get() = window.start
    val rangeEnd get() = window.end
}

data class RecallTopic(val id: String, val label: String, val weight: Int = 0, val colorSlot: Int = 0)
enum class RecallTopicFilter(val wireValue: String) { ALL("all"), FREQUENT("frequent"), UNRECALLED("unrecalled") }
data class RecallTopicMetrics(val clipCount: Int = 0, val recallCount: Int = 0, val unrecalledCount: Int = 0)
data class RecallTopicClip(
    val clipId: String, val clientRequestId: String = "", val title: String, val summary: String = "", val tags: List<String> = emptyList(),
    val sourceType: String = "", val sourceLabel: String = "", val knowledgeBaseName: String = "", val capturedAt: String = "",
    val recallCount: Int = 0, val recalledInWindow: Boolean = false, val score: Double = 0.0,
)
data class RecallTopicDetail(val window: RecallWindow = RecallWindow(), val topic: RecallTopic, val metrics: RecallTopicMetrics = RecallTopicMetrics(), val graph: RecallGraph = RecallGraph(), val items: List<RecallTopicClip> = emptyList()) {
    val days get() = window.days
    val clips get() = items
}

data class RecallSessionRequest(val days: Int = 7, val topicId: String = "", val limit: Int = 8)
data class RecallProgress(val completed: Int = 0, val total: Int = 0, val currentPosition: Int = 0)
data class RecallSession(
    val id: String, val kind: String = "general", val status: String, val topicId: String = "", val window: RecallWindow = RecallWindow(),
    val createdAt: String = "", val completedAt: String = "", val totalItems: Int = 0, val currentPosition: Int = 0,
    /** Stable, opaque server snapshot identifier. It never contains clip content or credentials. */
    val snapshotKey: String = "",
)
data class RecallSessionItem(
    val id: String, val clipId: String, val clientRequestId: String = "", val topicId: String = "", val position: Int = 0, val title: String,
    val cue: String = "", val revealText: String = "", val summary: String = "", val tags: List<String> = emptyList(), val sourceType: String = "",
    val sourceLabel: String = "", val knowledgeBaseName: String = "", val capturedAt: String = "", val recallCountBefore: Int = 0, val score: Double = 0.0, val status: String = "pending",
) { val prompt get() = cue }
data class RecallSessionResponse(val session: RecallSession, val items: List<RecallSessionItem> = emptyList(), val currentItem: RecallSessionItem? = null, val progress: RecallProgress = RecallProgress())

enum class RecallEventAction(val wireValue: String) { REVEAL("reveal"), REMEMBERED("remembered"), LATER("later"), OPEN_ORIGINAL("open_original") }
data class RecallEventRequest(val action: RecallEventAction, val clientActionId: String = UUID.randomUUID().toString())
data class RecallEventResponse(val session: RecallSession, val item: RecallSessionItem, val currentItem: RecallSessionItem? = null, val progress: RecallProgress = RecallProgress(), val revealText: String = "")

data class RecallWeeklySummary(
    val savedCount: Int = 0,
    val recallCount: Int = 0,
    val topicCount: Int = 0,
    val connectionCount: Int = 0,
    /** Optional server-authored, deterministic review copy; empty for older servers. */
    val summaryText: String = "",
)
data class RecallWeeklyTopic(val topicId: String, val label: String, val clipCount: Int = 0, val recallCount: Int = 0, val weight: Int = 0)
data class RecallWeeklyItem(val clipId: String, val title: String, val topicId: String = "", val topicLabel: String = "", val recallCount: Int = 0, val capturedAt: String = "")
data class RecallWeeklyReview(val window: RecallWindow = RecallWindow(), val summary: RecallWeeklySummary = RecallWeeklySummary(), val topTopics: List<RecallWeeklyTopic> = emptyList(), val mostRecalled: List<RecallWeeklyItem> = emptyList(), val suggestedItems: List<RecallWeeklyItem> = emptyList())

data class RecallClip(val clipId: String, val clientRequestId: String = "", val title: String = "", val summary: String = "", val safeText: String = "", val url: String = "", val filename: String = "", val sourceType: String = "", val sourceLabel: String = "", val knowledgeBaseName: String = "", val tags: List<String> = emptyList(), val capturedAt: String = "")

data class RecallApiResult<T>(val ok: Boolean, val value: T?, val message: String = "") {
    companion object { fun <T> success(value: T) = RecallApiResult(ok = true, value = value); fun <T> failure(message: String) = RecallApiResult<T>(ok = false, value = null, message = message) }
}
