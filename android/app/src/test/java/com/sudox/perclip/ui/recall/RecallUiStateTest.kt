package com.sudox.perclip.ui.recall

import com.sudox.perclip.recall.RecallEventAction
import com.sudox.perclip.recall.RecallEventResponse
import com.sudox.perclip.recall.RecallGraph
import com.sudox.perclip.recall.RecallGraphEdge
import com.sudox.perclip.recall.RecallGraphNode
import com.sudox.perclip.recall.RecallOverview
import com.sudox.perclip.recall.RecallProgress
import com.sudox.perclip.recall.RecallSession
import com.sudox.perclip.recall.RecallSessionItem
import com.sudox.perclip.recall.RecallTopicFilter
import com.sudox.perclip.recall.repository.RecallDomainMemory
import com.sudox.perclip.recall.repository.RecallDomainSnapshot
import com.sudox.perclip.recall.repository.RecallDomainTopic
import com.sudox.perclip.recall.repository.RecallResurfaceItem
import com.sudox.perclip.recall.repository.RecallResurfacePage
import com.sudox.perclip.recall.repository.MemoryPlanet
import com.sudox.perclip.recall.repository.MemoryPlanetWindow
import com.sudox.perclip.recall.repository.RecallSuppressedItem
import com.sudox.perclip.recall.repository.RecallSuppressionPage
import com.sudox.perclip.capabilities.AppFeatureAvailability
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RecallUiStateTest {
    @Test fun requestPeriodAndCustomRangeNeverReuseAnotherLastGoodPlanet() {
        val holder = RecallStateHolder()
        val weekWindow = MemoryPlanetWindow(kind = "week", days = 7, timezone = "Asia/Shanghai")
        val weekKey = RecallHomeRequestKey.create("config-a", RecallPeriod.WEEKLY, weekWindow)
        val week = MemoryPlanet("perclip.memory-planet.v1", weekWindow, emptyList(), 0, emptyList(), false)
        holder.beginHomeRequest(weekKey)
        holder.rememberPlanet(weekKey, week)

        val monthKey = RecallHomeRequestKey.create(
            "config-a",
            RecallPeriod.MONTHLY,
            MemoryPlanetWindow(kind = "month", days = 30, timezone = "Asia/Shanghai"),
        )
        holder.beginHomeRequest(monthKey)
        assertNull(holder.state.memoryPlanet.value)

        val customA = RecallHomeRequestKey.create(
            "config-a",
            RecallPeriod.CUSTOM,
            MemoryPlanetWindow(kind = "custom", startDate = "2026-07-01", endDate = "2026-07-05", timezone = "Asia/Shanghai"),
        )
        val customPlanet = week.copy(window = MemoryPlanetWindow(kind = "custom", startDate = "2026-07-01", endDate = "2026-07-05", timezone = "Asia/Shanghai"))
        holder.beginHomeRequest(customA)
        holder.rememberPlanet(customA, customPlanet)
        val customB = customA.copy(endDate = "2026-07-06")
        holder.beginHomeRequest(customB)
        assertNull(holder.state.memoryPlanet.value)
        holder.beginHomeRequest(customA)
        assertEquals(customPlanet, holder.state.memoryPlanet.value)
    }

    @Test fun customRangeRequiresTheDedicatedPlanetCapability() {
        assertTrue(RecallCustomRangePolicy.available(AppFeatureAvailability.AVAILABLE))
        assertFalse(RecallCustomRangePolicy.available(AppFeatureAvailability.UNAVAILABLE))
        assertFalse(RecallCustomRangePolicy.available(AppFeatureAvailability.CHECKING))
    }

    @Test fun dedicatedAndFallbackSourcesNeverReuseEachOthersPlanetAtTheSameConfigurationAndPeriod() {
        val holder = RecallStateHolder()
        val window = MemoryPlanetWindow(kind = "week", days = 7, timezone = "Asia/Shanghai")
        val dedicatedKey = RecallHomeRequestKey.create(
            "same-config",
            RecallPeriod.WEEKLY,
            window,
            planetSource = RecallPlanetSource.DEDICATED,
        )
        val fallbackKey = dedicatedKey.copy(planetSource = RecallPlanetSource.FALLBACK)
        val dedicated = MemoryPlanet(
            "perclip.memory-planet.v1",
            window,
            emptyList(),
            0,
            emptyList(),
            false,
        )
        holder.beginHomeRequest(dedicatedKey)
        holder.rememberPlanet(dedicatedKey, dedicated)

        holder.beginHomeRequest(fallbackKey)
        assertNull(holder.state.memoryPlanet.value)
        holder.beginHomeRequest(dedicatedKey)
        assertEquals(dedicated, holder.state.memoryPlanet.value)
        assertEquals(
            RecallPlanetSource.DEDICATED,
            RecallPlanetSourcePolicy.forAvailability(AppFeatureAvailability.AVAILABLE),
        )
        assertEquals(
            RecallPlanetSource.FALLBACK,
            RecallPlanetSourcePolicy.forAvailability(AppFeatureAvailability.UNAVAILABLE),
        )
    }

    @Test fun capabilityTransitionsClearOldDedicatedAndFallbackCachesAtTheSameApiAndPeriod() {
        val holder = RecallStateHolder()
        val window = MemoryPlanetWindow(kind = "week", days = 7, timezone = "Asia/Shanghai")
        val dedicatedKey = RecallHomeRequestKey.create(
            "same-config",
            RecallPeriod.WEEKLY,
            window,
            planetSource = RecallPlanetSource.DEDICATED,
        )
        val fallbackKey = dedicatedKey.copy(planetSource = RecallPlanetSource.FALLBACK)
        val planet = MemoryPlanet(
            "perclip.memory-planet.v1",
            window,
            emptyList(),
            0,
            emptyList(),
            false,
        )

        holder.prepareOverviewForConfiguration("same-config|AVAILABLE")
        holder.rememberPlanet(dedicatedKey, planet)
        holder.prepareOverviewForConfiguration("same-config|UNAVAILABLE")
        holder.beginHomeRequest(fallbackKey)
        assertNull(holder.state.memoryPlanet.value)

        holder.rememberPlanet(fallbackKey, planet)
        holder.prepareOverviewForConfiguration("same-config|AVAILABLE")
        holder.beginHomeRequest(dedicatedKey)
        assertNull(holder.state.memoryPlanet.value)
    }

    @Test fun freshFallbackWinsOverAnyCachedValueWhenDedicatedCapabilityIsUnavailable() {
        val cached = MemoryPlanet(
            "perclip.memory-planet.v1",
            MemoryPlanetWindow(kind = "week"),
            emptyList(),
            0,
            emptyList(),
            false,
        )
        val fresh = cached.copy(window = cached.window.copy(days = 7))
        assertEquals(
            fresh,
            RecallPlanetSourcePolicy.selectFailureValue(
                RecallPlanetSource.FALLBACK,
                cached,
                fresh,
            ),
        )
        assertEquals(
            cached,
            RecallPlanetSourcePolicy.selectFailureValue(
                RecallPlanetSource.DEDICATED,
                cached,
                fresh,
            ),
        )
    }

    @Test fun suppressionRecoverySurvivesEmptyTopicsPagesBeyondFiveAndFinalRestore() {
        val items = (1..7).map { RecallSuppressedItem("pc_${it.toString().padStart(32, '0')}", "记忆 $it") }
        var state = RecallUiState(domain = RecallResource(value = RecallDomainSnapshot(topics = emptyList())))
        state = RecallUiReducer.suppressionsLoaded(state, RecallSuppressionPage(items))
        assertEquals(7, state.suppressed.value?.items?.size)
        state = RecallUiReducer.suppressionRestored(state, items.last().clipId)
        assertEquals(6, state.suppressed.value?.items?.size)
        state.suppressed.value!!.items.map { it.clipId }.forEach { state = RecallUiReducer.suppressionRestored(state, it) }
        assertTrue(state.suppressed.value.items.isEmpty())
    }

    @Test fun suppressionPagingKeepsOnlyTheCurrentBoundedPageAndRefreshResetsCursor() {
        val first = (1..50).map { RecallSuppressedItem("pc_${it.toString().padStart(32, '0')}", "记忆 $it") }
        val second = (51..100).map { RecallSuppressedItem("pc_${it.toString().padStart(32, '0')}", "记忆 $it") }
        var state = RecallUiReducer.suppressionsLoaded(
            RecallUiState(),
            RecallSuppressionPage(first, cursor = "", nextCursor = "kc_page_2"),
        )
        state = RecallUiReducer.suppressionPageLoaded(
            state,
            RecallSuppressionPage(
                second,
                cursor = "kc_page_2",
                previousCursor = "kc_page_1",
                nextCursor = "kc_page_3",
            ),
        )
        assertEquals(50, state.suppressed.value?.items?.size)
        assertEquals(second.map { it.clipId }, state.suppressed.value?.items?.map { it.clipId })
        assertEquals("kc_page_1", state.suppressed.value?.previousCursor)

        state = RecallUiReducer.suppressionPageLoaded(
            state,
            RecallSuppressionPage(first, cursor = "kc_page_1", nextCursor = "kc_page_2"),
        )
        assertEquals(first.map { it.clipId }, state.suppressed.value?.items?.map { it.clipId })
        state = RecallUiReducer.suppressionsLoaded(state, RecallSuppressionPage(first))
        assertEquals("", state.suppressed.value?.cursor)
        assertEquals("", state.suppressed.value?.previousCursor)
    }

    @Test fun onlySuppressedMemoryRemainsRecoverableWhenPlanetHasNoTopics() {
        val item = RecallSuppressedItem("pc_${"1".padStart(32, '0')}", "唯一记忆")
        val state = RecallUiReducer.suppressionsLoaded(
            RecallUiState(
                domain = RecallResource(value = RecallDomainSnapshot()),
                memoryPlanet = RecallResource(value = MemoryPlanet("perclip.memory-planet.v1", MemoryPlanetWindow(), emptyList(), 0, emptyList(), false)),
            ),
            RecallSuppressionPage(listOf(item)),
        )
        assertEquals(item, state.suppressed.value?.items?.single())
        assertTrue(recallVisibleTopics(state).isEmpty())
        assertTrue(RecallUiReducer.suppressionRestored(state, item.clipId).suppressed.value?.items.isNullOrEmpty())
    }

    @Test fun domainLoadSelectsFirstCanonicalTopicWithoutInventingIdentity() {
        val snapshot = RecallDomainSnapshot(topics = listOf(RecallDomainTopic("topic:one", "主题一"), RecallDomainTopic("topic:two", "主题二")))
        val loaded = RecallUiReducer.domainLoaded(RecallUiState(), snapshot)
        assertEquals("topic:one", loaded.presentation.activeTopicId)
        assertEquals(snapshot, loaded.domain.value)
    }

    @Test fun domainLoadDoesNotEraseRestoredPlanetTopicWhilePlanetIsLoading() {
        val restored = RecallUiState(
            memoryPlanet = RecallResource(loading = true),
            presentation = RecallPresentationState(activeTopicId = "manual:software"),
        )
        val snapshot = RecallDomainSnapshot(topics = listOf(RecallDomainTopic("automatic:first", "自动主题")))

        val loaded = RecallUiReducer.domainLoaded(restored, snapshot)

        assertEquals("manual:software", loaded.presentation.activeTopicId)
        assertEquals(snapshot, loaded.domain.value)
    }

    @Test fun automaticRotationUsesLoadedSnapshotOnlyAndWrapsInStableOrder() {
        val snapshot = RecallDomainSnapshot(topics = listOf(RecallDomainTopic("a"), RecallDomainTopic("b"), RecallDomainTopic("c")))
        val state = RecallUiReducer.domainLoaded(RecallUiState(), snapshot)
        assertEquals("b", RecallUiReducer.rotateTopic(state).presentation.activeTopicId)
        val last = state.copy(presentation = state.presentation.copy(activeTopicId = "c"))
        assertEquals("a", RecallUiReducer.rotateTopic(last).presentation.activeTopicId)
        assertEquals(snapshot, RecallUiReducer.rotateTopic(last).domain.value)
    }

    @Test fun visibleTopicsRespectHiddenTopicsAndTheFiveNodeHardCap() {
        val snapshot = RecallDomainSnapshot(topics = (1..7).map { RecallDomainTopic("topic:$it", "主题$it") })
        val state = RecallUiState(
            domain = RecallResource(value = snapshot),
            presentation = RecallPresentationState(visibleTopicCount = 5, hiddenTopicIds = setOf("topic:2")),
        )
        assertEquals(listOf("topic:1", "topic:3", "topic:4", "topic:5", "topic:6"), recallVisibleTopics(state).map { it.id })
        assertEquals(5, recallVisibleTopics(state.copy(presentation = state.presentation.copy(visibleTopicCount = 99))).size)
    }

    @Test fun automaticRotationNeverSelectsHiddenOrCountClippedTopics() {
        val snapshot = RecallDomainSnapshot(topics = (1..5).map { RecallDomainTopic("topic:$it", "主题$it") })
        val state = RecallUiState(
            domain = RecallResource(value = snapshot),
            presentation = RecallPresentationState(activeTopicId = "topic:1", visibleTopicCount = 3, hiddenTopicIds = setOf("topic:2")),
        )
        val second = RecallUiReducer.rotateTopic(state)
        val third = RecallUiReducer.rotateTopic(second)
        assertEquals("topic:3", second.presentation.activeTopicId)
        assertEquals("topic:4", third.presentation.activeTopicId)
        assertEquals("topic:1", RecallUiReducer.rotateTopic(third).presentation.activeTopicId)
    }

    @Test fun displayPreferencesClampCountsKeepOneTopicAndRepairActiveTopic() {
        val snapshot = RecallDomainSnapshot(topics = listOf(RecallDomainTopic("a"), RecallDomainTopic("b"), RecallDomainTopic("c")))
        val loaded = RecallUiState(domain = RecallResource(value = snapshot), presentation = RecallPresentationState(activeTopicId = "b"))
        val clamped = RecallUiReducer.applyDisplayPreferences(loaded, RecallDisplayPreferences(99, 0, setOf("b")))
        assertEquals(5, clamped.presentation.visibleTopicCount)
        assertEquals(1, clamped.presentation.visibleMemoryLabels)
        assertEquals("a", clamped.presentation.activeTopicId)
        val onlyOneVisible = clamped.copy(presentation = clamped.presentation.copy(hiddenTopicIds = setOf("b", "c")))
        assertEquals(onlyOneVisible, RecallUiReducer.setTopicVisible(onlyOneVisible, "a", false))
    }

    @Test fun sharedHolderRestoresDisplayPreferencesOnceAndDomainLoadKeepsThem() {
        val holder = RecallStateHolder()
        val restored = RecallDisplayPreferences(visibleTopicCount = 3, visibleMemoryLabels = 1, hiddenTopicIds = setOf("b"))
        assertTrue(holder.applyDisplayPreferencesOnce(restored))
        assertEquals(3, holder.state.presentation.visibleTopicCount)
        assertEquals(1, holder.state.presentation.visibleMemoryLabels)
        assertEquals(setOf("b"), holder.state.presentation.hiddenTopicIds)

        holder.update { RecallUiReducer.setVisibleMemoryLabels(it, 3) }
        assertFalse(holder.applyDisplayPreferencesOnce(RecallDisplayPreferences()))
        assertEquals(3, holder.state.presentation.visibleTopicCount)
        assertEquals(3, holder.state.presentation.visibleMemoryLabels)
        assertEquals(setOf("b"), holder.state.presentation.hiddenTopicIds)

        val snapshot = RecallDomainSnapshot(topics = listOf(RecallDomainTopic("a"), RecallDomainTopic("b"), RecallDomainTopic("c")))
        holder.update { RecallUiReducer.domainLoaded(it, snapshot) }
        assertEquals(3, holder.state.presentation.visibleTopicCount)
        assertEquals(3, holder.state.presentation.visibleMemoryLabels)
        assertEquals(setOf("b"), holder.state.presentation.hiddenTopicIds)
        assertEquals(listOf("a", "c"), recallVisibleTopics(holder.state).map { it.id })
    }

    @Test fun restoringDisplayDefaultsReturnsFiveByFiveAndAllTopics() {
        val state = RecallUiState(presentation = RecallPresentationState(visibleTopicCount = 3, visibleMemoryLabels = 1, hiddenTopicIds = setOf("a")))
        val restored = RecallUiReducer.restoreDisplayDefaults(state)
        assertEquals(5, restored.presentation.visibleTopicCount)
        assertEquals(5, restored.presentation.visibleMemoryLabels)
        assertTrue(restored.presentation.hiddenTopicIds.isEmpty())
    }

    @Test fun memorySatelliteLabelsNeverExceedFourChineseCharacterWidths() {
        assertEquals("Notion", recallCompactSatelliteLabel("Notion AI 使用笔记"))
        assertEquals("提示词设", recallCompactSatelliteLabel("提示词设计心得"))
        assertEquals("AI 评测", recallCompactSatelliteLabel("AI 评测记录"))
        listOf("Notion AI 使用笔记", "提示词设计心得", "AI 评测记录", "RAGFlow 部署小记").forEach { value ->
            val compact = recallCompactSatelliteLabel(value)
            val visualWidth = compact.sumOf { if (it.code <= 0x7F) .5 else 1.0 }
            assertTrue("$compact visual width", visualWidth <= 4.0)
        }
    }

    @Test fun userInteractionPinsTopicAndRecordsPauseAnchor() {
        val selected = RecallUiReducer.selectTopic(RecallUiState(), "topic:ai", 1234L)
        assertEquals("topic:ai", selected.presentation.activeTopicId)
        assertEquals("topic:ai", selected.presentation.pinnedTopicId)
        assertEquals(1234L, selected.presentation.lastInteractionAt)
        assertTrue(selected.presentation.userInteracting)
    }

    @Test fun leavingAndReturningDoesNotMakeLoadedHomeEligibleForReload() {
        val loaded = RecallUiState(
            domain = RecallResource(value = RecallDomainSnapshot(topics = listOf(RecallDomainTopic("a")))),
            resurfaced = RecallResource(value = RecallResurfacePage()),
            memoryPlanet = RecallResource(value = MemoryPlanet("perclip.memory-planet.v1", MemoryPlanetWindow(), emptyList(), 0, emptyList(), false)),
        )
        assertFalse(RecallHomeLoadPolicy.shouldLoad(loaded))
        assertFalse(RecallHomeLoadPolicy.shouldLoad(loaded.copy(destination = RecallDestination.Topic("a"))))
    }

    @Test fun planetFailureRetainsLastSuccessfulValueAsCache() {
        val cached = MemoryPlanet(
            "perclip.memory-planet.v1",
            MemoryPlanetWindow(),
            emptyList(),
            0,
            emptyList(),
            false,
        )
        val failed = RecallUiReducer.memoryPlanetFailed(
            RecallUiState(memoryPlanet = RecallResource(value = cached, loading = true)),
            "HTTP 503",
        )
        assertEquals(cached, failed.memoryPlanet.value)
        assertEquals("HTTP 503", failed.memoryPlanet.error)
        assertFalse(failed.memoryPlanet.loading)
    }

    @Test fun visibleMemoriesDeduplicateCanonicalClipAndFollowActiveScope() {
        val domain = RecallDomainSnapshot(memories = listOf(
            RecallDomainMemory("m1", "clip:one", primaryTopicId = "topic:one", label = "一"),
            RecallDomainMemory("m2", "clip:two", primaryTopicId = "topic:two", label = "二"),
        ))
        val resurface = RecallResurfacePage(items = listOf(RecallResurfaceItem("clip:one", topicId = "topic:one", title = "远端一")))
        val state = RecallUiState(
            domain = RecallResource(value = domain),
            resurfaced = RecallResource(value = resurface),
            presentation = RecallPresentationState(activeTopicId = "topic:one", scope = RecallScope.ACTIVE_TOPIC),
        )
        assertEquals(listOf("clip:one"), recallVisibleMemories(state).map { it.clipId })
        assertEquals("远端一", recallVisibleMemories(state).single().title)
    }

    @Test fun customPeriodNeverPretendsToHaveAnExistingDayContract() {
        assertNull(RecallPeriod.CUSTOM.days)
        assertEquals(7, RecallPeriod.WEEKLY.days)
        assertEquals(30, RecallPeriod.MONTHLY.days)
    }

    @Test fun recallCardDateMatchesTheApprovedCompactChineseFormat() {
        assertEquals("5月12日 14:30", recallCardDate("2026-05-12T14:30:00Z", java.time.ZoneId.of("UTC")))
    }

    @Test fun automaticRotationStopsOnlyForSingleTopicMotionAndPinnedScope() {
        val base = RecallPresentationState()
        assertTrue(RecallAutoRotationPolicy.canRotate(base, 2, reducedMotion = false))
        assertTrue(RecallAutoRotationPolicy.canRotate(base.copy(graphExpanded = false), 2, false))
        assertFalse(RecallAutoRotationPolicy.canRotate(base, 1, false))
        assertFalse(RecallAutoRotationPolicy.canRotate(base, 2, true))
        assertFalse(RecallAutoRotationPolicy.canRotate(base.copy(scope = RecallScope.ACTIVE_TOPIC), 2, false))
        assertFalse(RecallAutoRotationPolicy.canRotate(base, 2, reducedMotion = false, menuOpen = true))
    }

    @Test fun orbitalMotionContinuesWhenTheListIsPinnedToTheActiveTopic() {
        val base = RecallPresentationState()
        assertTrue(RecallOrbitPolicy.canOrbit(base, 5, reducedMotion = false))
        assertFalse(RecallOrbitPolicy.canOrbit(base.copy(autoSurfaceEnabled = false), 5, false))
        assertFalse(RecallOrbitPolicy.canOrbit(base.copy(graphExpanded = false), 5, false))
        assertTrue(RecallOrbitPolicy.canOrbit(base.copy(scope = RecallScope.ACTIVE_TOPIC), 5, false))
        assertFalse(RecallOrbitPolicy.canOrbit(base, 5, true))
        assertEquals(2_000L, RecallOrbitPolicy.remainingPauseMillis(lastInteractionAt = 1_000L, now = 1_000L))
        assertEquals(1L, RecallOrbitPolicy.remainingPauseMillis(lastInteractionAt = 1_000L, now = 2_999L))
        assertEquals(0L, RecallOrbitPolicy.remainingPauseMillis(lastInteractionAt = 1_000L, now = 3_000L))
    }

    @Test fun fifoQueueWindowWrapsInStableOrderWithoutInventingItems() {
        val items = listOf("A", "B", "C", "D", "E")
        assertEquals(listOf("A", "B", "C"), recallQueueWindow(items, offset = 0, count = 3))
        assertEquals(listOf("D", "E", "A"), recallQueueWindow(items, offset = 3, count = 3))
        assertEquals(listOf("E", "A", "B", "C", "D"), recallQueueWindow(items, offset = -1, count = 9))
        assertTrue(recallQueueWindow(emptyList<String>(), offset = 2, count = 3).isEmpty())
    }

    @Test fun fifoListAndMemoryCircleShareTheSameQueueHeadAndNextOffset() {
        val items = listOf("A", "B", "C", "D", "E", "F", "G", "H")
        val listNow = recallQueueWindow(items, offset = 0, count = RecallQueuePolicy.VISIBLE_CARD_COUNT)
        val circleNow = recallQueueWindow(items, offset = 0, count = 5)
        val listNext = recallQueueWindow(items, offset = 1, count = RecallQueuePolicy.VISIBLE_CARD_COUNT)
        val circleNext = recallQueueWindow(items, offset = 1, count = 5)
        assertEquals("A", listNow.first())
        assertEquals(listNow.first(), circleNow.first())
        assertEquals(listOf("B", "C", "D", "E"), listNext)
        assertEquals(listNext.first(), circleNext.first())
        assertEquals("F", circleNext.last())
    }

    @Test fun fifoMotionRequiresARealTailAndHonorsAutoSurfaceCollapseAndReducedMotion() {
        assertTrue(RecallQueuePolicy.canAdvance(5, autoSurfaceEnabled = true, graphExpanded = true, reducedMotion = false))
        assertFalse(RecallQueuePolicy.canAdvance(4, true, true, false))
        assertFalse(RecallQueuePolicy.canAdvance(8, false, true, false))
        assertFalse(RecallQueuePolicy.canAdvance(8, true, false, false))
        assertFalse(RecallQueuePolicy.canAdvance(8, true, true, true))
        assertFalse(RecallQueuePolicy.canAdvance(8, true, true, false, browsingAll = true))
        assertFalse(RecallQueuePolicy.canAdvance(8, true, true, false, menuOpen = true))
        assertEquals(5_000L, RecallQueuePolicy.DWELL_MILLIS)
        assertEquals(600, RecallQueuePolicy.TRANSITION_MILLIS)
    }

    @Test fun scrollingAwayFromTheTopOpensStableBrowsingAndReturnUsesTwoSecondRecovery() {
        assertTrue(RecallQueuePolicy.shouldEnterBrowse(itemCount = 5, isAtTop = false, isScrollInProgress = true))
        assertFalse(RecallQueuePolicy.shouldEnterBrowse(itemCount = 3, isAtTop = false, isScrollInProgress = true))
        assertFalse(RecallQueuePolicy.shouldEnterBrowse(itemCount = 5, isAtTop = true, isScrollInProgress = true))
        assertFalse(RecallQueuePolicy.shouldEnterBrowse(itemCount = 5, isAtTop = false, isScrollInProgress = false))
        assertEquals(2_000L, RecallQueuePolicy.BROWSE_RESUME_DELAY_MILLIS)

        val items = listOf("A", "B", "C", "D", "E")
        assertEquals(items, recallQueueWindow(items, offset = 0, count = items.size))
        assertEquals(listOf("C", "D", "E", "A", "B"), recallQueueWindow(items, offset = 2, count = items.size))
    }

    @Test fun orbitalPathClosesAfterOneTurnAndKeepsTheEightDegreeTilt() {
        val start = recallOrbitPoint(167f, 145f, 126f, 104f, 90f)
        val completed = recallOrbitPoint(167f, 145f, 126f, 104f, 450f)
        val advanced = recallOrbitPoint(167f, 145f, 126f, 104f, 210f)
        assertEquals(start.x, completed.x, .001f)
        assertEquals(start.y, completed.y, .001f)
        assertTrue(start.x < 167f)
        assertTrue(start.y > 145f)
        assertTrue(kotlin.math.abs(start.x - advanced.x) > 20f)
        assertTrue(kotlin.math.abs(start.y - advanced.y) > 20f)
    }

    @Test fun memorySatellitesOrbitMoreSlowlyThanTopicsAndStayRelativeToTheirTopic() {
        assertTrue(RecallSatellitePolicy.CYCLE_MILLIS > RecallOrbitPolicy.CYCLE_MILLIS)
        val topic = recallOrbitPoint(167f, 100f, 126f, 75f, 30f)
        val satelliteStart = recallOrbitPoint(topic.x, topic.y, RecallSatellitePolicy.RADIUS_X, RecallSatellitePolicy.RADIUS_Y, 0f, 0f)
        val satelliteQuarter = recallOrbitPoint(topic.x, topic.y, RecallSatellitePolicy.RADIUS_X, RecallSatellitePolicy.RADIUS_Y, 90f, 0f)
        assertEquals(RecallSatellitePolicy.RADIUS_X, satelliteStart.x - topic.x, .001f)
        assertEquals(RecallSatellitePolicy.RADIUS_Y, satelliteQuarter.y - topic.y, .001f)
        assertTrue(kotlin.math.abs(satelliteStart.x - satelliteQuarter.x) > 20f)
        assertTrue(kotlin.math.abs(satelliteStart.y - satelliteQuarter.y) > 20f)
    }

    @Test fun systemReducedMotionIsPersistedInPresentationState() {
        val reduced = RecallUiReducer.setReducedMotion(RecallUiState(), true)
        assertTrue(reduced.presentation.reducedMotion)
        assertFalse(RecallUiReducer.setReducedMotion(reduced, false).presentation.reducedMotion)
    }

    @Test fun overviewRetainsStaleDataWhenRefreshFails() {
        val loaded = RecallUiReducer.overviewLoaded(RecallUiState(), RecallOverview())
        val failed = RecallUiReducer.overviewFailed(RecallUiReducer.overviewLoading(loaded), "网络暂不可用")
        assertNotNull(failed.overview.value)
        assertEquals("网络暂不可用", failed.overview.error)
        assertFalse(failed.overview.loading)
    }

    @Test fun backReturnsOnlyWithinRecall() {
        assertNull(RecallUiReducer.back(RecallUiState()))
        val returned = RecallUiReducer.back(RecallUiState(destination = RecallDestination.Weekly))
        assertEquals(RecallDestination.Overview, returned?.destination)
        assertEquals(RecallDestination.Overview, RecallUiReducer.back(RecallUiState(destination = RecallDestination.DisplaySettings))?.destination)
    }

    @Test fun holderKeepsNewerDestinationAndInvalidatesOlderGeneration() {
        val holder = RecallStateHolder()
        val old = holder.beginTopic()
        holder.update { RecallUiReducer.navigate(it, RecallDestination.Topic("B")) }
        val newer = holder.beginTopic()
        assertFalse(holder.isTopicCurrent(old))
        assertTrue(holder.isTopicCurrent(newer))
        assertEquals(RecallDestination.Topic("B"), holder.state.destination)
    }

    @Test fun holderInvalidatesEveryRequestKindIndependently() {
        val holder = RecallStateHolder()
        val overview = holder.beginOverview(); holder.beginOverview()
        val topic = holder.beginTopic(); holder.beginTopic()
        val weekly = holder.beginWeekly(); holder.beginWeekly()
        val session = holder.beginSession(); holder.beginSession()
        val action = holder.beginAction(); holder.beginAction()
        val original = holder.beginOriginal(); holder.invalidateOriginal()
        assertFalse(holder.isOverviewCurrent(overview))
        assertFalse(holder.isTopicCurrent(topic))
        assertFalse(holder.isWeeklyCurrent(weekly))
        assertFalse(holder.isSessionCurrent(session))
        assertFalse(holder.isActionCurrent(action))
        assertFalse(holder.isOriginalCurrent(original))
    }

    @Test fun originalResolveFromOverviewIsIgnoredAfterNavigatingToTopic() {
        val holder = RecallStateHolder()
        val request = holder.beginOriginalResolve()
        holder.navigate(RecallDestination.Topic("topic:a"))
        assertFalse(holder.isOriginalResolveCurrent(request))
    }

    @Test fun originalResolveFromTopicAIsIgnoredAfterNavigatingToTopicB() {
        val holder = RecallStateHolder(RecallUiState(destination = RecallDestination.Topic("topic:a")))
        val request = holder.beginOriginalResolve()
        holder.navigate(RecallDestination.Topic("topic:b"))
        assertFalse(holder.isOriginalResolveCurrent(request))
    }

    @Test fun originalResolveCanOpenOnlyOnItsCurrentDestinationAndDismissInvalidatesIt() {
        val holder = RecallStateHolder(RecallUiState(destination = RecallDestination.Weekly, pendingOriginal = RecallOriginalStrategy.SafeRemoteSheet(RecallOriginalTarget("clip"))))
        val request = holder.beginOriginalResolve()
        assertTrue(holder.isOriginalResolveCurrent(request))
        holder.dismissOriginal()
        assertFalse(holder.isOriginalResolveCurrent(request))
        assertNull(holder.state.pendingOriginal)
    }

    @Test fun topicFilterLoadingKeepsExistingList() {
        val state = RecallUiReducer.topicLoading(RecallUiState(), RecallTopicFilter.FREQUENT)
        assertEquals(RecallTopicFilter.FREQUENT, state.topicFilter)
        assertTrue(state.topic.loading)
    }

    @Test fun revealDoesNotAdvanceServerProgress() {
        val item = RecallSessionItem(id = "item", clipId = "clip", title = "标题")
        val response = RecallEventResponse(RecallSession(id = "s", status = "active"), item, progress = RecallProgress(completed = 1, total = 3), revealText = "提示")
        val before = RecallUiState(session = RecallResource(value = com.sudox.perclip.recall.RecallSessionResponse(response.session, currentItem = item, progress = response.progress)))
        val after = RecallUiReducer.actionApplied(before, RecallEventAction.REVEAL, response)
        assertEquals(before.currentProgress, after.currentProgress)
        assertEquals("item", after.revealedItemId)
        assertEquals("提示", after.revealedText)
    }

    @Test fun completedActionWithoutNextItemStillUpdatesActedSnapshotItem() {
        val pending = RecallSessionItem(id = "old", clipId = "old", title = "旧", status = "pending")
        val acted = pending.copy(status = "remembered")
        val before = RecallUiState(session = RecallResource(value = com.sudox.perclip.recall.RecallSessionResponse(RecallSession("s", status = "active"), listOf(pending), pending)))
        val response = RecallEventResponse(RecallSession(id = "s", status = "completed"), acted, currentItem = null, progress = RecallProgress(2, 2))
        val after = RecallUiReducer.actionApplied(before, RecallEventAction.REMEMBERED, response)
        assertNull(after.session.value?.currentItem)
        assertEquals("remembered", after.session.value?.items?.single()?.status)
        assertEquals("2 / 2", RecallUiReducer.progressLabel(after.currentProgress))
    }

    @Test fun openOriginalPreservesSessionSnapshotAndReveal() {
        val item = RecallSessionItem("item", "clip", title = "标题")
        val sibling = RecallSessionItem("sibling", "clip-2", title = "另一个")
        val state = RecallUiState(session = RecallResource(value = com.sudox.perclip.recall.RecallSessionResponse(RecallSession("s", status = "active"), listOf(item, sibling), item)), revealedItemId = item.id, revealedText = "已展开")
        val next = RecallUiReducer.actionApplied(state, RecallEventAction.OPEN_ORIGINAL, RecallEventResponse(state.session.value!!.session, item))
        assertEquals(listOf(item, sibling), next.session.value?.items)
        assertEquals("item", next.revealedItemId)
        assertEquals("已展开", next.revealedText)
    }

    @Test fun rememberedReplacesActedItemAndMergesCurrentItemWithoutDroppingSnapshot() {
        val old = RecallSessionItem("old", "old", title = "旧", position = 1, status = "pending")
        val acted = old.copy(status = "remembered")
        val next = RecallSessionItem("next", "next", title = "新", position = 2)
        val state = RecallUiState(session = RecallResource(value = com.sudox.perclip.recall.RecallSessionResponse(RecallSession("s", status = "active"), listOf(old), old)))
        val after = RecallUiReducer.actionApplied(state, RecallEventAction.REMEMBERED, RecallEventResponse(state.session.value!!.session, acted, next))
        assertEquals(listOf(acted, next), after.session.value?.items)
        assertEquals("next", after.session.value?.currentItem?.id)
    }

    @Test fun laterReplacesActedItemInExistingSnapshot() {
        val pending = RecallSessionItem("item", "clip", title = "稍后", status = "pending")
        val later = pending.copy(status = "later")
        val next = RecallSessionItem("next", "next", title = "下一条", position = 2)
        val state = RecallUiState(session = RecallResource(value = com.sudox.perclip.recall.RecallSessionResponse(RecallSession("s", status = "active"), listOf(pending), pending)))
        val after = RecallUiReducer.actionApplied(state, RecallEventAction.LATER, RecallEventResponse(state.session.value!!.session, later, next))
        assertEquals("later", after.session.value?.items?.first()?.status)
    }

    @Test fun originalStrategyMapsClientRequestPrefixToActualLocalClipId() {
        val local = "local-clip"
        listOf(local, "$local:", "$local:filename", "$local:2:filename").forEach { clientRequestId ->
            assertEquals(RecallOriginalStrategy.LocalDetail(local), RecallUiReducer.originalStrategy(RecallOriginalTarget("42", clientRequestId), setOf(local)))
        }
        assertTrue(RecallUiReducer.originalStrategy(RecallOriginalTarget("42"), emptySet()) is RecallOriginalStrategy.SafeRemoteSheet)
    }

    @Test fun relativeDateUsesStableHumanLabels() {
        val now = java.time.Instant.parse("2026-07-10T12:00:00Z").toEpochMilli()
        assertEquals("昨天", recallRelativeDate("2026-07-09T11:00:00Z", now))
        assertEquals("", recallRelativeDate("", now))
    }

    @Test fun graphLayoutIsDeterministicAndHitTestable() {
        val graph = RecallGraph(
            nodes = listOf(
                RecallGraphNode("topic", "topic", "主题", weight = 9),
                RecallGraphNode("clip", "clip", "内容", clipId = "clip"),
            ),
            edges = listOf(RecallGraphEdge("topic", "clip", "contains")),
        )
        val first = RecallGraphLayoutEngine.layout(graph, 300f, 200f)
        val second = RecallGraphLayoutEngine.layout(graph, 300f, 200f)
        assertEquals(first, second)
        assertEquals("topic", first.hitTest(first.nodes.first().point)?.id)
        assertTrue(RecallGraphLayoutEngine.layout(RecallGraph(), 300f, 200f).nodes.isEmpty())
    }

    @Test fun graphLabelsStayCompactWhileRetainingOriginalContractLabel() {
        val graph = RecallGraph(nodes = listOf(
            RecallGraphNode("topic", "topic", "人工智能教学应用", weight = 9),
            RecallGraphNode("clip", "clip", "RAGFlow 知识图谱可视化接入思路", clipId = "clip"),
        ), edges = listOf(RecallGraphEdge("topic", "clip", "contains")))
        val nodes = RecallGraphLayoutEngine.layout(graph, 300f, 220f).nodes
        assertEquals("人工智能教学应用", nodes.first { it.id == "topic" }.label)
        assertEquals("教学", nodes.first { it.id == "topic" }.shortLabel)
        assertTrue(nodes.first { it.id == "clip" }.compactLabel.length <= 8)
    }

    @Test fun graphClipTapWinsOverTopicAndUsesServerClipId() {
        val clip = RecallGraphNodeLayout("clip", "clip", RecallGraphPoint(10f, 10f), 8f, "内容", "", "内容", RecallGraphPoint(10f, 10f), "topic", "42")
        val topic = RecallGraphNodeLayout("topic", "topic", RecallGraphPoint(10f, 10f), 38f, "主题", "主题", "", RecallGraphPoint(10f, 10f), "topic", "")
        assertEquals(RecallGraphTapTarget.Original(RecallOriginalTarget("42")), RecallUiReducer.graphTapTarget(clip))
        assertEquals(RecallGraphTapTarget.Topic("topic"), RecallUiReducer.graphTapTarget(topic))
    }

    @Test fun graphMetricsAreExplicitlyDensityScaled() {
        val graph = RecallGraph(nodes = listOf(RecallGraphNode("topic", "topic", "主题", weight = 9)))
        val oneX = RecallGraphLayoutEngine.layout(graph, 360f, 300f, RecallGraphStylePx(38f, 8f, 76f, 72f, 14f, 12f))
        val threeX = RecallGraphLayoutEngine.layout(graph, 1080f, 900f, RecallGraphStylePx(114f, 24f, 228f, 216f, 42f, 36f))
        assertEquals(38f, oneX.nodes.single().radius)
        assertEquals(114f, threeX.nodes.single().radius)
    }

    @Test fun overviewGraphIsSparseWhileTopicGraphCentersRequestedTopic() {
        val graph = RecallGraph(
            nodes = listOf(
                RecallGraphNode("topic:ai", "topic", "AI Agent", 8, 0, "topic:ai"),
                RecallGraphNode("topic:teaching", "topic", "教学", 7, 1, "topic:teaching"),
                RecallGraphNode("topic:paper", "topic", "论文阅读", 6, 2, "topic:paper"),
                RecallGraphNode("topic:project", "topic", "工作流设计", 5, 3, "topic:project"),
            ) + (1..6).map { RecallGraphNode("clip:$it", "clip", "内容$it", clipId = "$it") },
            edges = (1..6).map { RecallGraphEdge("topic:ai", "clip:$it", "contains") },
        )
        val overview = RecallGraphLayoutEngine.layout(graph, 360f, 240f)
        assertEquals(4, overview.nodes.count { it.type == "topic" })
        assertEquals(1, overview.nodes.count { it.type == "clip" })
        val focused = RecallGraphLayoutEngine.layout(graph, 360f, 240f, mode = RecallGraphMode.TOPIC, focusTopicId = "topic:ai")
        assertTrue(focused.nodes.first { it.id == "topic:ai" }.isFocus)
        assertEquals(5, focused.nodes.count { it.type == "clip" })
    }

    @Test fun topicLabelsPreferNaturalNavigationWords() {
        assertEquals("AI", recallTopicShortLabel("AI Agent"))
        assertEquals("工作流", recallTopicShortLabel("工作流设计"))
        assertEquals("论文", recallTopicShortLabel("论文阅读"))
        assertEquals("教学", recallTopicShortLabel("AI 教学应用"))
        assertEquals("项目", recallTopicShortLabel("项目管理"))
        assertEquals("图谱", recallTopicShortLabel("知识图谱"))
    }

    @Test fun topicLabelFitUsesTheLargestSafeMeasuredSizeForRequiredLabels() {
        listOf("AI", "教学", "论文", "项目", "工作流", "知识图谱").forEach { label ->
            val size = fitTopicLabelFontSize(radius = 25f) { candidate ->
                TopicLabelMeasure(width = label.length * candidate * .72f, height = candidate)
            }
            val measured = TopicLabelMeasure(label.length * size * .72f, size)
            assertTrue("$label width", measured.width <= 25f * 1.42f)
            assertTrue("$label height", measured.height <= 25f * .78f)
        }
    }

    @Test fun graphTopicRadiiAreTightenedButKeepWeightHierarchy() {
        val graph = RecallGraph(nodes = listOf(
            RecallGraphNode("topic:big", "topic", "AI Agent", weight = 9, topicId = "topic:big"),
            RecallGraphNode("topic:small", "topic", "教学", weight = 3, topicId = "topic:small"),
        ))
        val layout = RecallGraphLayoutEngine.layout(graph, 360f, 240f, RecallGraphStylePx(75f, 21f, 200f, 186f, 36f, 36f))
        val focus = layout.nodes.first { it.id == "topic:big" }
        val small = layout.nodes.first { it.id == "topic:small" }
        assertEquals(75f, focus.radius)
        assertTrue(small.radius < focus.radius)
        assertTrue(small.radius <= 75f * .70f)
    }
}
