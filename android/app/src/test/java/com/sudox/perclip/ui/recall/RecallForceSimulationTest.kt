package com.sudox.perclip.ui.recall

import com.sudox.perclip.recall.RecallGraph
import com.sudox.perclip.recall.RecallGraphEdge
import com.sudox.perclip.recall.RecallGraphNode
import kotlin.math.hypot
import org.junit.Assert.*
import org.junit.Test

class RecallForceSimulationTest {
    private val style = RecallGraphStylePx(30f, 7f, 104f, 62f, 12f, 12f)
    private val graph = RecallGraph(listOf(
        RecallGraphNode("topic", "topic", "AI Agent", 9, topicId = "topic"),
        RecallGraphNode("clip:a", "clip", "内容 A", clipId = "a"),
        RecallGraphNode("clip:b", "clip", "内容 B", clipId = "b"),
    ), listOf(RecallGraphEdge("topic", "clip:a", "contains"), RecallGraphEdge("topic", "clip:b", "contains")))
    private fun simulation() = RecallForceSimulation().also { it.reset(graph, 360f, 220f, style, RecallGraphMode.TOPIC, "topic") }
    private fun distance(a: ForceNodeState, b: ForceNodeState) = hypot((a.x - b.x).toDouble(), (a.y - b.y).toDouble()).toFloat()

    @Test fun deterministicReset() { assertEquals(simulation().snapshot(), simulation().snapshot()) }
    @Test fun deterministicReducedMotionSettle() { assertEquals(simulation().settled(), simulation().settled()) }
    @Test fun threeHundredTicksStayFinite() { val s = simulation(); repeat(300) { s.tick(1f / 30f) }; assertTrue(s.snapshot().nodes.all { it.point.x.isFinite() && it.point.y.isFinite() }) }
    @Test fun ticksKeepXYWithinBounds() { val s = simulation(); repeat(300) { s.tick(1f / 30f) }; s.snapshot().nodes.forEach { assertTrue(it.point.x in it.radius..360f - it.radius && it.point.y in it.radius..220f - it.radius) } }
    @Test fun connectedNodeReturnsTowardRestLength() { val s = simulation(); val topic = s.node("topic")!!; s.dragStart("clip:a", 340f, 200f); s.dragEnd("clip:a"); val before = distance(topic, s.node("clip:a")!!); repeat(120) { s.tick(1f / 30f) }; assertTrue(distance(topic, s.node("clip:a")!!) < before) }
    @Test fun unconnectedNodesAreSeparatedByRepulsion() { val s = simulation(); s.dragStart("clip:a", 180f, 110f); s.dragEnd("clip:a"); s.dragStart("clip:b", 181f, 110f); s.dragEnd("clip:b"); repeat(60) { s.tick(1f / 30f) }; assertTrue(distance(s.node("clip:a")!!, s.node("clip:b")!!) > 14f) }
    @Test fun overlapSeparates() { val s = simulation(); s.dragStart("clip:a", 180f, 110f); s.dragStart("clip:b", 180f, 110f); s.dragEnd("clip:a"); s.dragEnd("clip:b"); repeat(30) { s.tick(1f / 30f) }; assertTrue(distance(s.node("clip:a")!!, s.node("clip:b")!!) > 10f) }
    @Test fun focusStartsCloserToCenter() { val s = simulation(); val focus = s.node("topic")!!; assertTrue(distanceToCenter(focus) < distanceToCenter(s.node("clip:a")!!)) }
    @Test fun alphaDecaysWithTicks() { val s = simulation(); val before = s.currentAlpha; repeat(20) { s.tick(1f / 30f) }; assertTrue(s.currentAlpha < before) }
    @Test fun alphaHasFloor() { val s = simulation(); repeat(2000) { s.tick(1f / 30f) }; assertEquals(.02f, s.currentAlpha, .0001f) }
    @Test fun resetStartsAlphaHigh() { assertEquals(.8f, simulation().currentAlpha, .0001f) }
    @Test fun reheatRaisesAlpha() { val s = simulation(); repeat(300) { s.tick(1f / 30f) }; val cool = s.currentAlpha; s.reheat(.4f); assertTrue(s.currentAlpha > cool) }
    @Test fun dragStartPinsNode() { val s = simulation(); s.dragStart("clip:a", 40f, 40f); s.tick(1f / 30f); assertEquals(40f, s.node("clip:a")!!.x, .01f) }
    @Test fun dragMoveFollowsPointer() { val s = simulation(); s.dragMove("clip:a", 260f, 120f); s.tick(1f / 30f); assertEquals(260f, s.node("clip:a")!!.x, .01f) }
    @Test fun dragEndUnpinsNode() { val s = simulation(); s.dragStart("clip:a", 40f, 40f); s.dragEnd("clip:a"); assertNull(s.node("clip:a")!!.fixedX) }
    @Test fun dragReheatsSimulation() { val s = simulation(); repeat(300) { s.tick(1f / 30f) }; s.dragStart("clip:a", 100f, 100f); assertTrue(s.currentAlpha >= .4f) }
    @Test fun resetClearsPreviousGraph() { val s = simulation(); s.reset(RecallGraph(), 360f, 220f, style, RecallGraphMode.OVERVIEW, ""); assertTrue(s.snapshot().nodes.isEmpty()) }
    @Test fun emptyGraphIsSafe() { val s = RecallForceSimulation(); s.reset(RecallGraph(), 360f, 220f, style, RecallGraphMode.OVERVIEW, ""); s.tick(1f / 30f); assertTrue(s.snapshot().nodes.isEmpty()) }
    @Test fun visibleNodesAreBoundedToTwelve() { val many = RecallGraph(nodes = (1..20).map { RecallGraphNode("topic:$it", "topic", "主题$it", it, topicId = "topic:$it") }); val s = RecallForceSimulation(); s.reset(many, 360f, 220f, style, RecallGraphMode.OVERVIEW, ""); assertTrue(s.snapshot().nodes.size <= 12) }
    private fun distanceToCenter(node: ForceNodeState) = hypot((node.x - 180f).toDouble(), (node.y - 110f).toDouble()).toFloat()
}
