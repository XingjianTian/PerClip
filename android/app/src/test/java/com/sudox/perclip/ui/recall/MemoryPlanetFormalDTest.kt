package com.sudox.perclip.ui.recall

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MemoryPlanetFormalDTest {
    @Test
    fun `vnext card keeps its one-viewport sections fixed`() {
        assertEquals(561f, MemoryPlanetVNextLayoutPolicy.CARD_HEIGHT_DP)
        assertEquals(48f, MemoryPlanetVNextLayoutPolicy.CONTROL_HEIGHT_DP)
        assertEquals(1f, MemoryPlanetVNextLayoutPolicy.CONTROL_DIVIDER_HEIGHT_DP)
        assertEquals(270f, MemoryPlanetVNextLayoutPolicy.GRAPH_HEIGHT_DP)
        assertEquals(6f, MemoryPlanetVNextLayoutPolicy.DIVIDER_HEIGHT_DP)
        assertEquals(236f, MemoryPlanetVNextLayoutPolicy.INSIGHT_HEIGHT_DP)
        assertEquals(
            MemoryPlanetVNextLayoutPolicy.CARD_HEIGHT_DP,
            MemoryPlanetVNextLayoutPolicy.CONTROL_HEIGHT_DP +
                MemoryPlanetVNextLayoutPolicy.CONTROL_DIVIDER_HEIGHT_DP +
                MemoryPlanetVNextLayoutPolicy.GRAPH_HEIGHT_DP +
                MemoryPlanetVNextLayoutPolicy.DIVIDER_HEIGHT_DP +
                MemoryPlanetVNextLayoutPolicy.INSIGHT_HEIGHT_DP,
            .001f,
        )
    }

    @Test
    fun `viewport policy spends extra height on the orbit section`() {
        assertEquals(
            MemoryPlanetVNextLayoutPolicy.CARD_HEIGHT_DP,
            MemoryPlanetVNextLayoutPolicy.cardHeightForViewport(643f),
            .001f,
        )
        assertEquals(642f, MemoryPlanetVNextLayoutPolicy.cardHeightForViewport(724f), .001f)
        assertEquals(270f, MemoryPlanetVNextLayoutPolicy.graphHeightForCard(561f), .001f)
        assertEquals(351f, MemoryPlanetVNextLayoutPolicy.graphHeightForCard(642f), .001f)
        assertEquals(
            MemoryPlanetVNextLayoutPolicy.GRAPH_HEIGHT_DP,
            MemoryPlanetVNextLayoutPolicy.graphHeightForCard(642f, hasControls = false),
            .001f,
        )
    }

    @Test
    fun `surfaced count starts at visible labels and grows with each orbit rotation`() {
        assertEquals(5, recallSurfacedMemoryCount(9, 5, 0, 24))
        assertEquals(6, recallSurfacedMemoryCount(9, 5, 1, 24))
        assertEquals(24, recallSurfacedMemoryCount(24, 5, 30, 24))
        assertEquals(0, recallSurfacedMemoryCount(0, 5, 3, 24))
    }

    @Test
    fun `topic keyword fallback remains compact and deterministic`() {
        assertEquals(
            listOf("课程设计", "教学方法", "互动策略", "作业优化"),
            recallTopicKeywordFallback(listOf("课程设计，教学方法；互动策略 / 作业优化")),
        )
        assertEquals(listOf("无"), recallTopicKeywordDisplay(emptyList()))
        assertEquals(listOf("部署"), recallTopicKeywordDisplay(listOf("部署")))
    }

    @Test fun domainFailureIsNotMisreportedAsAnEmptyPlanet() {
        assertEquals(
            MemoryPlanetContentState.API_UNAVAILABLE,
            memoryPlanetContentState(false, "", "服务不可用", 0),
        )
        assertEquals(
            MemoryPlanetContentState.EMPTY,
            memoryPlanetContentState(false, "", "", 0),
        )
    }

    @Test fun customDateLabelFitsTheFixedControlAtLargeType() {
        assertEquals("7/25–26", recallPeriodLabel(RecallPeriod.CUSTOM, "2026-07-25", "2026-07-26"))
        assertEquals("7/31–8/1", recallPeriodLabel(RecallPeriod.CUSTOM, "2026-07-31", "2026-08-01"))
        assertEquals("自定义", recallPeriodLabel(RecallPeriod.CUSTOM, "", ""))
    }
    @Test
    fun `formal d full star counts and period pools are fixed`() {
        val light = MemoryPlanetStarfieldSpecs.full(dark = false)
        val dark = MemoryPlanetStarfieldSpecs.full(dark = true)

        assertEquals(22, light.size)
        assertEquals(5, light.count { it.major })
        assertEquals(18, dark.size)
        assertEquals(4, dark.count { it.major })
        assertTrue((light + dark).filter { it.major }.all { it.periodMillis in MemoryPlanetStarfieldSpecs.majorPeriods })
        assertTrue((light + dark).filterNot { it.major }.all { it.periodMillis in MemoryPlanetStarfieldSpecs.minorPeriods })
        assertTrue((light + dark).all { it.peakPosition in 0.42f..0.68f })
        assertTrue((light + dark).filter { it.major }.all(MemoryPlanetStarExclusions::majorAllowed))
    }

    @Test
    fun `lite reduced and unavailable states use bounded static density`() {
        assertEquals(10, MemoryPlanetStarfieldSpecs.select(false, MemoryPlanetQuality.LITE, MemoryPlanetContentState.NORMAL).size)
        assertEquals(10, MemoryPlanetStarfieldSpecs.select(false, MemoryPlanetQuality.FULL, MemoryPlanetContentState.LOADING).size)
        assertEquals(8, MemoryPlanetStarfieldSpecs.select(true, MemoryPlanetQuality.FULL, MemoryPlanetContentState.API_UNAVAILABLE).size)

        val reducedLight = MemoryPlanetStarfieldSpecs.frame(
            MemoryPlanetStarfieldSpecs.full(false), 99_999L, dark = false, static = true, reducedMotion = true,
        )
        assertTrue(reducedLight.filter { it.spec.major }.all { it.alpha == .30f })
        assertTrue(reducedLight.filterNot { it.spec.major }.all { it.alpha == .14f })
        assertTrue(reducedLight.all { it.driftX == 0f && it.driftY == 0f })
    }

    @Test
    fun `dynamic frame never peaks more than two major stars`() {
        val specs = MemoryPlanetStarfieldSpecs.full(false)
        for (millis in 0L..20_000L step 100L) {
            val frame = MemoryPlanetStarfieldSpecs.frame(specs, millis, dark = false, static = false, reducedMotion = false)
            assertTrue(MemoryPlanetStarfieldSpecs.peakMajorCount(frame) <= 2)
        }
    }

    @Test
    fun `shared clock freezes and resumes from preserved phase`() {
        val clock = MemoryPlanetMotionClock(700L)
        clock.advance(300L, running = false)
        assertEquals(700L, clock.elapsedMillis)
        clock.advance(300L)
        assertEquals(1_000L, clock.elapsedMillis)
    }

    @Test
    fun `clock policy stops for every formal inactive condition`() {
        fun running(
            visible: Boolean = true,
            expanded: Boolean = true,
            content: MemoryPlanetContentState = MemoryPlanetContentState.NORMAL,
            quality: MemoryPlanetQuality = MemoryPlanetQuality.FULL,
            lifecycle: Boolean = true,
            reduced: Boolean = false,
            browsing: Boolean = false,
            menu: Boolean = false,
            filterOverlay: Boolean = false,
            snackbar: Boolean = false,
            suppressionSheet: Boolean = false,
        ) = MemoryPlanetClockPolicy.shouldRun(
            lifecycleActive = lifecycle,
            planetVisible = visible,
            graphExpanded = expanded,
            contentState = content,
            quality = quality,
            reducedMotion = reduced,
            browsingAll = browsing,
            menuOpen = menu,
            filterOverlayOpen = filterOverlay,
            snackbarOpen = snackbar,
            suppressionSheetOpen = suppressionSheet,
        )

        assertTrue(running())
        assertFalse(running(visible = false))
        assertFalse(running(expanded = false))
        assertFalse(running(content = MemoryPlanetContentState.LOADING))
        assertFalse(running(content = MemoryPlanetContentState.EMPTY))
        assertFalse(running(content = MemoryPlanetContentState.API_UNAVAILABLE))
        assertFalse(running(quality = MemoryPlanetQuality.STATIC))
        assertFalse(running(lifecycle = false))
        assertFalse(running(reduced = true))
        assertFalse(running(browsing = true))
        assertFalse(running(menu = true))
        assertFalse(running(filterOverlay = true))
        assertFalse(running(snackbar = true))
        assertFalse(running(suppressionSheet = true))
    }

    @Test
    fun `period menu keeps clock stopped while visible`() {
        assertOverlayStopsClock(RecallFilterOverlay.PERIOD_MENU)
    }

    @Test
    fun `knowledge base menu keeps clock stopped while visible`() {
        assertOverlayStopsClock(RecallFilterOverlay.KNOWLEDGE_BASE_MENU)
    }

    @Test
    fun `date picker keeps clock stopped while visible`() {
        assertOverlayStopsClock(RecallFilterOverlay.DATE_PICKER)
    }

    @Test
    fun `period menu bridges to date picker without an open state gap`() {
        val period = RecallFilterOverlayPolicy.reduce(
            RecallFilterOverlay.NONE,
            RecallFilterOverlayEvent.OPEN_PERIOD_MENU,
        )
        val date = RecallFilterOverlayPolicy.reduce(
            period.overlay,
            RecallFilterOverlayEvent.OPEN_DATE_PICKER,
        )

        assertEquals(RecallFilterOverlay.PERIOD_MENU, period.overlay)
        assertTrue(period.interactionRequired)
        assertEquals(RecallFilterOverlay.DATE_PICKER, date.overlay)
        assertTrue(period.overlay.isOpen)
        assertTrue(date.overlay.isOpen)
        assertFalse(date.interactionRequired)
    }

    @Test
    fun `date picker dismiss restarts the formal two second pause`() {
        assertOverlayCloseRestartsPause(RecallFilterOverlayEvent.DISMISS)
    }

    @Test
    fun `date picker confirm restarts the formal two second pause`() {
        assertOverlayCloseRestartsPause(RecallFilterOverlayEvent.CONFIRM)
    }

    @Test
    fun `date picker cancel restarts the formal two second pause`() {
        assertOverlayCloseRestartsPause(RecallFilterOverlayEvent.CANCEL)
    }

    @Test
    fun `overlay close resumes elapsed clock from its frozen phase`() {
        val clock = MemoryPlanetMotionClock(1_250L)
        clock.advance(4_000L, running = false)
        clock.advance(1_999L, running = false)
        assertEquals(1_250L, clock.elapsedMillis)
        clock.advance(16L, running = true)
        assertEquals(1_266L, clock.elapsedMillis)
    }

    @Test
    fun `filter overlays block automatic topic rotation and fifo`() {
        val presentation = RecallPresentationState()
        assertFalse(
            RecallAutoRotationPolicy.canRotate(
                presentation = presentation,
                topicCount = 5,
                reducedMotion = false,
                menuOpen = false,
                filterOverlayOpen = true,
            ),
        )
        assertFalse(
            RecallQueuePolicy.canAdvance(
                itemCount = 9,
                autoSurfaceEnabled = true,
                graphExpanded = true,
                reducedMotion = false,
                browsingAll = false,
                menuOpen = false,
                filterOverlayOpen = true,
            ),
        )
    }

    @Test
    fun `quality degradation prioritizes accessibility then device constraints`() {
        assertEquals(MemoryPlanetQuality.FULL, MemoryPlanetQualityPolicy.select(MemoryPlanetPerformanceInputs()))
        assertEquals(MemoryPlanetQuality.LITE, MemoryPlanetQualityPolicy.select(MemoryPlanetPerformanceInputs(lowRamDevice = true)))
        assertEquals(MemoryPlanetQuality.LITE, MemoryPlanetQualityPolicy.select(MemoryPlanetPerformanceInputs(powerSaveMode = true)))
        assertEquals(MemoryPlanetQuality.STATIC, MemoryPlanetQualityPolicy.select(MemoryPlanetPerformanceInputs(reducedMotion = true)))
        assertEquals(
            MemoryPlanetQuality.STATIC,
            MemoryPlanetQualityPolicy.select(
                MemoryPlanetPerformanceInputs(reducedMotion = true, debugOverride = MemoryPlanetQuality.FULL),
            ),
        )
    }

    @Test
    fun `standard and large type windows retain a 66 dp next card preview`() {
        val standard = MemoryPlanetListWindowPolicy.calculate(1f)
        assertEquals(3, standard.fullCardCount)
        assertEquals(108f, standard.cardHeightDp)
        assertEquals(66f, standard.previewDp)
        assertEquals(420f, standard.windowHeightDp)

        val large = MemoryPlanetListWindowPolicy.calculate(1.3f)
        assertEquals(2, large.fullCardCount)
        assertEquals(140.4f, large.cardHeightDp, .001f)
        assertEquals(66f, large.previewDp)
        assertEquals(366.8f, large.windowHeightDp, .001f)
        assertEquals(106f, MemoryPlanetListWindowPolicy.bottomPaddingDp(66f, 24f))
    }

    private fun assertOverlayStopsClock(overlay: RecallFilterOverlay) {
        assertTrue(overlay.isOpen)
        assertFalse(
            MemoryPlanetClockPolicy.shouldRun(
                lifecycleActive = true,
                planetVisible = true,
                graphExpanded = true,
                contentState = MemoryPlanetContentState.NORMAL,
                quality = MemoryPlanetQuality.FULL,
                reducedMotion = false,
                browsingAll = false,
                menuOpen = false,
                filterOverlayOpen = overlay.isOpen,
                snackbarOpen = false,
                suppressionSheetOpen = false,
            ),
        )
    }

    private fun assertOverlayCloseRestartsPause(event: RecallFilterOverlayEvent) {
        val transition = RecallFilterOverlayPolicy.reduce(RecallFilterOverlay.DATE_PICKER, event)
        assertEquals(RecallFilterOverlay.NONE, transition.overlay)
        assertTrue(transition.interactionRequired)
        val closedAt = 10_000L
        assertEquals(1L, RecallOrbitPolicy.remainingPauseMillis(closedAt, closedAt + 1_999L))
        assertEquals(0L, RecallOrbitPolicy.remainingPauseMillis(closedAt, closedAt + 2_000L))
    }
}
