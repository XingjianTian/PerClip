package com.sudox.perclip.recall.repository

/** Deterministic, presentation-only label selection. It owns neither layout nor animation state. */
object RecallLabelRotationSelector {
    fun select(
        topics: List<RecallDomainTopic>, memories: List<RecallDomainMemory>, visibleCount: Int? = null, rotationIndex: Int = 0,
        previousNodeIds: Set<String> = emptySet(), preferences: RecallPreferences = RecallPreferences(),
    ): List<String> {
        val limit = (visibleCount ?: preferences.visibleLabelCount).coerceIn(1, 5)
        val muted = preferences.mutedTopicIds.toSet()
        val preferred = preferences.preferredTopicIds.toSet()
        val nodes = buildList<LabelNode> {
            topics.filter { it.id.isNotBlank() && it.id !in muted }.forEach { add(LabelNode(it.id, it.id, it.labelPriority, it.rotationSeed)) }
            if (preferences.includeMemoryLabels) memories.filter { it.id.isNotBlank() && it.topicIds.none(muted::contains) && it.primaryTopicId !in muted }.forEach { add(LabelNode(it.id, it.primaryTopicId.ifBlank { it.topicIds.firstOrNull().orEmpty() }, it.labelPriority, it.rotationSeed)) }
        }
        val baseRanked = nodes.sortedWith(compareByDescending<LabelNode> { it.priority + if (it.topicId in preferred) 0.05 else 0.0 }
            .thenBy { it.seed }.thenBy { it.id })
        // Rotate the ranked ring so rotation changes labels even when priorities are distinct.
        val shift = if (baseRanked.isEmpty()) 0 else Math.floorMod(rotationIndex, baseRanked.size)
        val ranked = baseRanked.drop(shift) + baseRanked.take(shift)
        val candidates = ranked
        val chosen = mutableListOf<LabelNode>()
        // First pass deliberately spreads labels across topics whenever possible.
        candidates.forEach { node -> if (chosen.size < limit && chosen.none { it.topicId == node.topicId }) chosen += node }
        candidates.forEach { node -> if (chosen.size < limit && node !in chosen) chosen += node }
        if (chosen.map { it.id }.toSet() == previousNodeIds) {
            candidates.firstOrNull { it !in chosen }?.let { replacement ->
                if (chosen.isNotEmpty()) chosen[chosen.lastIndex] = replacement
            }
        }
        return chosen.map { it.id }
    }
    private data class LabelNode(val id: String, val topicId: String, val priority: Double, val seed: Int)
}
