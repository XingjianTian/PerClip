package com.sudox.perclip.ui.recall

import com.sudox.perclip.recall.RecallGraph
import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

data class RecallGraphPoint(val x: Float, val y: Float)
data class RecallGraphStylePx(val topicRadius: Float, val clipRadius: Float, val topicRing: Float, val childDistance: Float, val labelGap: Float, val edgePadding: Float)
enum class RecallGraphMode { OVERVIEW, TOPIC }

data class RecallGraphNodeLayout(
    val id: String,
    val type: String,
    val point: RecallGraphPoint,
    val radius: Float,
    val label: String,
    val shortLabel: String,
    val compactLabel: String,
    val labelPoint: RecallGraphPoint,
    val topicId: String,
    val clipId: String,
    val colorSlot: Int = 0,
    val isFocus: Boolean = false,
)
data class RecallGraphLayout(val nodes: List<RecallGraphNodeLayout> = emptyList()) {
    fun hitTest(point: RecallGraphPoint): RecallGraphNodeLayout? = nodes.filter { hypot((it.point.x - point.x).toDouble(), (it.point.y - point.y).toDouble()) <= it.radius }.minByOrNull { hypot((it.point.x - point.x).toDouble(), (it.point.y - point.y).toDouble()) }
}

fun recallTopicShortLabel(value: String): String {
    val normalized = value.trim().replace("人工智能", "AI").replace("知识图谱", "图谱")
    return when {
        normalized.equals("AI Agent", true) -> "AI"
        normalized.contains("工作流") -> "工作流"
        normalized.contains("教学") -> "教学"
        normalized.contains("论文") || normalized.contains("阅读") -> "论文"
        normalized.contains("项目") -> "项目"
        normalized.contains("图谱") -> "图谱"
        normalized.length <= 4 -> normalized
        else -> normalized.take(3)
    }
}
fun recallTopicLines(value: String): List<String> = listOf(recallTopicShortLabel(value))
fun recallClipCompactLabel(value: String): String {
    val normalized = value.trim().replace("知识图谱", "图谱").replace("可视化", "视觉")
    return when {
        normalized.contains("课程设计") -> "课程笔记"
        normalized.contains("流程节点") -> "流程命名"
        normalized.length <= 7 -> normalized
        else -> normalized.take(6) + "…"
    }
}

/** Stable, intentionally sparse placement for a navigational map rather than an exhaustive engineering graph. */
object RecallGraphLayoutEngine {
    fun layout(graph: RecallGraph, width: Float, height: Float, style: RecallGraphStylePx = RecallGraphStylePx(30f, 7f, 104f, 66f, 12f, 12f), mode: RecallGraphMode = RecallGraphMode.OVERVIEW, focusTopicId: String = ""): RecallGraphLayout {
        if (width <= 0f || height <= 0f || graph.nodes.isEmpty()) return RecallGraphLayout()
        val topics = graph.nodes.filter { it.type.equals("topic", true) }.sortedWith(compareByDescending<com.sudox.perclip.recall.RecallGraphNode> { it.weight }.thenBy { it.id })
        val focus = topics.firstOrNull { it.topicId == focusTopicId || it.id == focusTopicId } ?: topics.firstOrNull()
        val shownTopics = when (mode) {
            RecallGraphMode.OVERVIEW -> topics.take(4)
            RecallGraphMode.TOPIC -> listOfNotNull(focus) + topics.filter { it.id != focus?.id }.take(1)
        }.distinctBy { it.id }
        if (shownTopics.isEmpty()) return RecallGraphLayout()
        val smallestTopicWeight = shownTopics.minOf { it.weight }
        val topicWeightRange = (shownTopics.maxOf { it.weight } - smallestTopicWeight).coerceAtLeast(1)
        val center = RecallGraphPoint(width / 2f, height / 2f)
        val ring = min(style.topicRing, min(width / 2f - style.topicRadius - style.edgePadding, height / 2f - style.topicRadius - style.edgePadding)).coerceAtLeast(0f)
        val layout = mutableListOf<RecallGraphNodeLayout>()
        val positions = linkedMapOf<String, RecallGraphPoint>()
        shownTopics.forEachIndexed { index, node ->
            val isFocus = node.id == focus?.id
            val point = if (isFocus) center else {
                val nonFocusIndex = shownTopics.take(index).count { it.id != focus?.id }
                val count = (shownTopics.size - 1).coerceAtLeast(1)
                val angle = when (mode) {
                    RecallGraphMode.OVERVIEW -> listOf(0.0, PI / 2, PI).getOrElse(nonFocusIndex) { 0.0 }
                    RecallGraphMode.TOPIC -> -PI / 2
                }
                RecallGraphPoint(center.x + cos(angle).toFloat() * ring, center.y + sin(angle).toFloat() * ring)
            }
            // Normal topics stay deliberately smaller than the focus. Weight only supplies a quiet hierarchy.
            val weightFraction = (node.weight - smallestTopicWeight).toFloat() / topicWeightRange
            val radius = if (isFocus) style.topicRadius else style.topicRadius * (.68f + weightFraction * .12f)
            val clamped = clamp(point, width, height, radius + style.edgePadding)
            positions[node.id] = clamped
            layout += RecallGraphNodeLayout(node.id, node.type, clamped, radius, node.label, recallTopicShortLabel(node.label), "", clamped, node.topicId.ifBlank { node.id }, node.clipId, node.colorSlot, isFocus)
        }
        val visibleIds = shownTopics.map { it.id }.toSet()
        val clips = graph.nodes.filterNot { it.type.equals("topic", true) }.groupBy { clip -> graph.edges.firstOrNull { it.target == clip.id }?.source ?: clip.topicId }
        shownTopics.forEach { topic ->
            val limit = if (mode == RecallGraphMode.TOPIC && topic.id == focus?.id) 5 else if (mode == RecallGraphMode.OVERVIEW) 1 else 0
            clips[topic.id].orEmpty().sortedBy { it.id }.take(limit).forEachIndexed { index, node ->
                val anchor = positions[topic.id] ?: center
                val angle = if (topic.id == focus?.id) {
                    if (mode == RecallGraphMode.TOPIC) -PI / 2 + (2 * PI * index / max(1, limit)) else listOf(-2.35, -0.8).getOrElse(index) { -2.35 }
                } else atan2((anchor.y - center.y).toDouble(), (anchor.x - center.x).toDouble())
                val raw = RecallGraphPoint(anchor.x + cos(angle).toFloat() * style.childDistance, anchor.y + sin(angle).toFloat() * style.childDistance)
                val point = clamp(raw, width, height, style.clipRadius + style.edgePadding)
                val right = cos(angle) >= 0
                val compact = recallClipCompactLabel(node.label)
                val labelInset = style.edgePadding + compact.length * 12f
                val labelPoint = RecallGraphPoint((point.x + if (right) style.labelGap else -style.labelGap).coerceIn(labelInset, width - labelInset), (point.y + if (sin(angle) >= 0) style.labelGap else -style.labelGap).coerceIn(style.edgePadding + 10f, height - style.edgePadding - 10f))
                layout += RecallGraphNodeLayout(node.id, node.type, point, style.clipRadius, node.label, "", compact, labelPoint, node.topicId, node.clipId, topic.colorSlot, false)
            }
        }
        return RecallGraphLayout(layout)
    }
    private fun clamp(point: RecallGraphPoint, width: Float, height: Float, inset: Float) = RecallGraphPoint(point.x.coerceIn(inset, width - inset), point.y.coerceIn(inset, height - inset))
}
