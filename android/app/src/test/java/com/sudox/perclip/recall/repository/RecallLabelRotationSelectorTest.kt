package com.sudox.perclip.recall.repository

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecallLabelRotationSelectorTest {
    private val topics = listOf(
        RecallDomainTopic("topic:a", labelPriority = 0.9, rotationSeed = 1),
        RecallDomainTopic("topic:b", labelPriority = 0.8, rotationSeed = 2),
    )
    private val memories = listOf(
        RecallDomainMemory("clip:1", primaryTopicId = "topic:a", topicIds = listOf("topic:a"), labelPriority = 0.7, rotationSeed = 3),
        RecallDomainMemory("clip:2", primaryTopicId = "topic:b", topicIds = listOf("topic:b"), labelPriority = 0.6, rotationSeed = 4),
    )

    @Test fun defaultsToThreeAndBoundsVisibleCount() {
        assertEquals(3, RecallLabelRotationSelector.select(topics, memories).size)
        assertEquals(1, RecallLabelRotationSelector.select(topics, memories, visibleCount = 0).size)
        assertEquals(4, RecallLabelRotationSelector.select(topics, memories, visibleCount = 99).size)
    }

    @Test fun presentationPreferencesControlMemoryLabelsAndDefaultCount() {
        val preferences = RecallPreferences(visibleLabelCount = 1, includeMemoryLabels = false)
        val selected = RecallLabelRotationSelector.select(topics, memories, preferences = preferences)
        assertEquals(1, selected.size)
        assertTrue(selected.single().startsWith("topic:"))
    }

    @Test fun rotationChangesCandidatesWhenMoreLabelsExist() {
        val first = RecallLabelRotationSelector.select(topics, memories, visibleCount = 1, rotationIndex = 0)
        val next = RecallLabelRotationSelector.select(topics, memories, visibleCount = 1, rotationIndex = 1)
        assertFalse(first == next)
    }

    @Test fun selectionIsDeterministicDiverseAndAvoidsMutedTopics() {
        val first = RecallLabelRotationSelector.select(topics, memories, rotationIndex = 2)
        assertEquals(first, RecallLabelRotationSelector.select(topics, memories, rotationIndex = 2))
        assertTrue(first.any { it == "topic:a" || it == "clip:1" }); assertTrue(first.any { it == "topic:b" || it == "clip:2" })
        val muted = RecallLabelRotationSelector.select(topics, memories, preferences = RecallPreferences(mutedTopicIds = listOf("topic:b")))
        assertFalse(muted.any { it == "topic:b" || it == "clip:2" })
    }

    @Test fun preferredTopicsReceivePriorityAndPreviousSetCanRotate() {
        val closeTopics = listOf(topics[0].copy(labelPriority = 0.81), topics[1])
        val preferred = RecallLabelRotationSelector.select(closeTopics, memories, visibleCount = 1, preferences = RecallPreferences(preferredTopicIds = listOf("topic:b")))
        assertEquals("topic:b", preferred.single())
        val next = RecallLabelRotationSelector.select(topics, memories, visibleCount = 3, previousNodeIds = setOf("topic:a", "topic:b", "clip:1"))
        assertFalse(next.toSet() == setOf("topic:a", "topic:b", "clip:1"))
    }

    @Test fun aSingleTopicRemainsSafeAcrossRotations() {
        val onlyTopic = listOf(RecallDomainTopic("topic:only", labelPriority = 0.5, rotationSeed = 7))
        assertEquals(listOf("topic:only"), RecallLabelRotationSelector.select(onlyTopic, emptyList(), rotationIndex = 0))
        assertEquals(listOf("topic:only"), RecallLabelRotationSelector.select(onlyTopic, emptyList(), rotationIndex = 99))
    }
}
