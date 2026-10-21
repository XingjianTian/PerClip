package com.sudox.perclip.recall.repository

import com.sudox.perclip.capabilities.AppFeatureAvailability

object MemoryPlanetLoadPolicy {
    fun shouldRequest(availability: AppFeatureAvailability): Boolean =
        availability == AppFeatureAvailability.AVAILABLE
}

/** Bounded compatibility projection for servers without a Planet endpoint. */
object MemoryPlanetFallback {
    fun build(
        domain: RecallDomainSnapshot,
        resurfaced: RecallResurfacePage,
        window: MemoryPlanetWindow,
    ): MemoryPlanet = buildAvailable(domain, resurfaced, window)!!

    fun buildAvailable(
        domain: RecallDomainSnapshot?,
        resurfaced: RecallResurfacePage?,
        window: MemoryPlanetWindow,
    ): MemoryPlanet? {
        if (domain == null && resurfaced == null) return null
        val safeDomain = domain ?: RecallDomainSnapshot(
            windowDays = resurfaced?.windowDays?.takeIf { it > 0 } ?: window.days,
            windowStart = resurfaced?.windowStart.orEmpty(),
            windowEnd = resurfaced?.windowEnd.orEmpty(),
        )
        val safeResurfaced = resurfaced ?: RecallResurfacePage()
        val domainByClip = safeDomain.memories.associateBy { it.clipId }
        val ordered = buildList {
            safeResurfaced.items.forEach { item ->
                val topicId = item.topicId
                    .ifBlank { domainByClip[item.clipId]?.primaryTopicId.orEmpty() }
                    .ifBlank { "unclassified" }
                add(
                    MemoryPlanetMemory(
                        clipId = item.clipId,
                        title = item.title,
                        summary = item.summary.ifBlank { item.safeExcerpt },
                        capturedAt = item.capturedAt,
                        source = item.sourceLabel.ifBlank { item.sourceType },
                    ) to topicId,
                )
            }
            safeDomain.memories.forEach { memory ->
                if (none { it.first.clipId == memory.clipId }) {
                    add(
                        MemoryPlanetMemory(
                            clipId = memory.clipId,
                            title = memory.label,
                            summary = memory.summary.ifBlank { memory.safeExcerpt },
                            capturedAt = memory.capturedAt,
                            source = memory.sourceLabel.ifBlank { memory.sourceType },
                        ) to memory.primaryTopicId,
                    )
                }
            }
        }
            .filter { it.first.clipId.isNotBlank() }
            .distinctBy { it.first.clipId }

        val topicDefinitions = if (safeDomain.topics.isNotEmpty()) {
            safeDomain.topics
        } else {
            safeResurfaced.items
                .asSequence()
                .filter { it.topicId.isNotBlank() && it.topicId != "unclassified" }
                .distinctBy { it.topicId }
                .take(5)
                .map { item ->
                    RecallDomainTopic(
                        id = item.topicId,
                        label = item.topicLabel.ifBlank { item.topicId },
                        clipCount = ordered.count { (_, topicId) -> topicId == item.topicId },
                    )
                }
                .toList()
        }
        val assignedClipIds = mutableSetOf<String>()
        val mainTopics = topicDefinitions
            .filterNot { it.id == "unclassified" }
            .take(5)
            .map { topic ->
                val memories = ordered
                    .filter { (memory, topicId) ->
                        topicId == topic.id || domainByClip[memory.clipId]?.topicIds?.contains(topic.id) == true
                    }
                    .map { it.first }
                    .filterNot { it.clipId in assignedClipIds }
                    .take(5)
                    .onEach { assignedClipIds += it.clipId }
                MemoryPlanetTopic(topic.id, topic.label, topic.clipCount, memories)
            }
            .filter { it.memories.isNotEmpty() }
        val unclassified = ordered
            .filter { (_, topicId) -> topicId == "unclassified" }
            .map { it.first }
            .filterNot { it.clipId in assignedClipIds }
            .distinctBy { it.clipId }
        return MemoryPlanet(
            contractVersion = MemoryPlanetJson.CONTRACT,
            window = window.copy(
                days = safeDomain.windowDays,
                start = safeDomain.windowStart,
                end = safeDomain.windowEnd,
            ),
            topics = mainTopics,
            unclassifiedCount = unclassified.size,
            unclassifiedPreview = unclassified.take(3),
            hasMoreUnclassified = unclassified.size > 3,
        )
    }
}
