package com.sudox.perclip.recall.repository

data class MemoryPlanetWindow(
    val kind: String = "week",
    val days: Int = 7,
    val start: String = "",
    val end: String = "",
    val startDate: String = "",
    val endDate: String = "",
    val timezone: String = "",
    val knowledgeBaseId: String = "",
)

data class MemoryPlanetMemory(
    val clipId: String,
    val title: String,
    val summary: String = "",
    val capturedAt: String = "",
    val source: String = "",
)

data class MemoryPlanetTopic(
    val topicId: String,
    val displayName: String,
    val memoryCount: Int,
    val memories: List<MemoryPlanetMemory>,
)

data class MemoryPlanet(
    val contractVersion: String,
    val window: MemoryPlanetWindow,
    val topics: List<MemoryPlanetTopic>,
    val unclassifiedCount: Int,
    val unclassifiedPreview: List<MemoryPlanetMemory>,
    val hasMoreUnclassified: Boolean,
)

fun MemoryPlanetWindow.matches(requested: MemoryPlanetWindow): Boolean {
    if (kind != requested.kind) return false
    if (requested.knowledgeBaseId.isNotBlank() && knowledgeBaseId != requested.knowledgeBaseId) return false
    return if (requested.kind == "custom") {
        startDate == requested.startDate &&
            endDate == requested.endDate &&
            timezone == requested.timezone
    } else {
        true
    }
}
