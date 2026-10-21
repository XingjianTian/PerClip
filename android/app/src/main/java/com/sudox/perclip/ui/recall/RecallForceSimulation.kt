package com.sudox.perclip.ui.recall

import com.sudox.perclip.recall.RecallGraph
import kotlin.math.*

/** Android-only, deterministic small-graph force simulation; Stage 16 remains the sole graph data source. */
data class ForceNodeState(val id: String, val type: String, var x: Float, var y: Float, val homeX: Float, val homeY: Float, var vx: Float = 0f, var vy: Float = 0f, val radius: Float, val mass: Float, val topicId: String, val clipId: String, val colorSlot: Int, val isFocus: Boolean, var fixedX: Float? = null, var fixedY: Float? = null, val label: String, val shortLabel: String, val compactLabel: String)
data class ForceLink(val sourceId: String, val targetId: String, val restLength: Float, val strength: Float)

class RecallForceSimulation {
    private val nodes = ArrayList<ForceNodeState>()
    private val links = ArrayList<ForceLink>()
    private var width = 0f; private var height = 0f; private var padding = 12f; private var elapsed = 0f
    private var alpha = .8f
    private val alphaFloor = .02f
    val currentAlpha: Float get() = alpha

    fun reset(graph: RecallGraph, width: Float, height: Float, style: RecallGraphStylePx, mode: RecallGraphMode, focusTopicId: String) {
        this.width = width; this.height = height; padding = style.edgePadding; elapsed = 0f; alpha = .8f; nodes.clear(); links.clear()
        val seed = RecallGraphLayoutEngine.layout(graph, width, height, style, mode, focusTopicId)
        seed.nodes.forEach { n -> nodes += ForceNodeState(n.id, n.type, n.point.x, n.point.y, n.point.x, n.point.y, radius = n.radius, mass = if (n.isFocus) 2.2f else if (n.type == "topic") 1.6f else 1f, topicId = n.topicId, clipId = n.clipId, colorSlot = n.colorSlot, isFocus = n.isFocus, label = n.label, shortLabel = n.shortLabel, compactLabel = n.compactLabel) }
        val ids = nodes.map { it.id }.toSet()
        graph.edges.filter { it.source in ids && it.target in ids }.forEach { edge ->
            val a = nodes.first { it.id == edge.source }; val b = nodes.first { it.id == edge.target }
            val topicLink = a.type == "topic" && b.type == "topic"
            links += ForceLink(edge.source, edge.target, if (topicLink) style.topicRing else style.childDistance, if (a.isFocus || b.isFocus) .020f else .014f)
        }
    }
    fun reheat(value: Float = .40f) { alpha = max(alpha, value.coerceIn(alphaFloor, .8f)) }
    fun tick(deltaSeconds: Float) {
        if (nodes.isEmpty() || width <= 0f) return
        val dt = deltaSeconds.coerceIn(.001f, .05f); val temperature = alpha; elapsed += dt
        val ax = FloatArray(nodes.size); val ay = FloatArray(nodes.size)
        val cx = width / 2f; val cy = height / 2f
        nodes.forEachIndexed { i, n ->
            val gravity = if (n.isFocus) .0025f else if (n.type == "topic") .0018f else .0012f
            val home = if (n.isFocus) .010f else if (n.type == "topic") .018f else .013f
            ax[i] += (cx - n.x) * gravity + (n.homeX - n.x) * home
            ay[i] += (cy - n.y) * gravity + (n.homeY - n.y) * home
            val phase = (stableHash(n.id) % 628) / 100f
            val ambient = if (n.isFocus) .0005f else .0015f
            ax[i] += sin(elapsed * .55f + phase).toFloat() * ambient * temperature
            ay[i] += cos(elapsed * .46f + phase).toFloat() * ambient * temperature
        }
        for (i in nodes.indices) for (j in i + 1 until nodes.size) {
            val a = nodes[i]; val b = nodes[j]; var dx = b.x - a.x; var dy = b.y - a.y
            var d2 = dx * dx + dy * dy; if (d2 < .01f) { dx = 1f; dy = 0f; d2 = 1f }; val d = sqrt(d2)
            val kind = if (a.type == "topic" && b.type == "topic") 1800f else if (a.type == "clip" && b.type == "clip") 520f else 820f
            val repel = (kind / d2).coerceAtMost(18f) * temperature
            ax[i] -= dx / d * repel / a.mass; ay[i] -= dy / d * repel / a.mass; ax[j] += dx / d * repel / b.mass; ay[j] += dy / d * repel / b.mass
            val overlap = a.radius + b.radius + 5f - d
            if (overlap > 0f) { val push = overlap * .62f; ax[i] -= dx / d * push; ay[i] -= dy / d * push; ax[j] += dx / d * push; ay[j] += dy / d * push }
        }
        links.forEach { link -> val i = nodes.indexOfFirst { it.id == link.sourceId }; val j = nodes.indexOfFirst { it.id == link.targetId }; if (i >= 0 && j >= 0) { val a = nodes[i]; val b = nodes[j]; val dx = b.x - a.x; val dy = b.y - a.y; val d = sqrt((dx * dx + dy * dy).coerceAtLeast(.01f)); val f = ((d - link.restLength) * (link.strength * 2.5f) * temperature).coerceIn(-8f, 8f); ax[i] += dx / d * f; ay[i] += dy / d * f; ax[j] -= dx / d * f; ay[j] -= dy / d * f } }
        nodes.forEachIndexed { i, n ->
            n.fixedX?.let { n.x = it; n.y = n.fixedY ?: n.y; n.vx = 0f; n.vy = 0f; return@forEachIndexed }
            ax[i] += boundary(n.x, n.radius, width); ay[i] += boundary(n.y, n.radius, height)
            n.vx = (n.vx + ax[i] * dt * 60f) * .90f; n.vy = (n.vy + ay[i] * dt * 60f) * .90f
            n.x = (n.x + n.vx).coerceIn(n.radius + padding, width - n.radius - padding); n.y = (n.y + n.vy).coerceIn(n.radius + padding, height - n.radius - padding)
        }
        alpha = max(alphaFloor, alpha * .985f)
    }
    fun dragStart(id: String, x: Float, y: Float) { reheat(.40f); nodes.firstOrNull { it.id == id }?.apply { fixedX = x; fixedY = y } }
    fun dragMove(id: String, x: Float, y: Float) { reheat(.40f); nodes.firstOrNull { it.id == id }?.let { node -> dragStart(id, x.coerceIn(node.radius + padding, width - node.radius - padding), y.coerceIn(node.radius + padding, height - node.radius - padding)) } }
    fun dragEnd(id: String) { nodes.firstOrNull { it.id == id }?.apply { fixedX = null; fixedY = null } }
    fun snapshot(): RecallGraphLayout = RecallGraphLayout(nodes.map { n ->
        val parent = links.firstOrNull { it.targetId == n.id }?.let { link -> nodes.firstOrNull { it.id == link.sourceId } }
        val dx = n.x - (parent?.x ?: width / 2f); val dy = n.y - (parent?.y ?: height / 2f)
        val length = sqrt((dx * dx + dy * dy).coerceAtLeast(.01f)); val outwardX = dx / length; val outwardY = dy / length
        val inset = padding + n.compactLabel.length * 12f
        val lx = (n.x + outwardX * 14f).coerceIn(inset, width - inset); val ly = (n.y + outwardY * 14f).coerceIn(padding + 10f, height - padding - 10f)
        RecallGraphNodeLayout(n.id, n.type, RecallGraphPoint(n.x, n.y), n.radius, n.label, n.shortLabel, n.compactLabel, RecallGraphPoint(lx, ly), n.topicId, n.clipId, n.colorSlot, n.isFocus)
    })
    fun settled(ticks: Int = 240): RecallGraphLayout { repeat(ticks) { tick(1f / 30f) }; return snapshot() }
    fun node(id: String) = nodes.firstOrNull { it.id == id }
    private fun boundary(value: Float, radius: Float, max: Float): Float = when { value < radius + padding -> (radius + padding - value) * .20f; value > max - radius - padding -> (max - radius - padding - value) * .20f; else -> 0f }
    private fun stableHash(value: String) = value.fold(7) { acc, c -> acc * 31 + c.code }
}
