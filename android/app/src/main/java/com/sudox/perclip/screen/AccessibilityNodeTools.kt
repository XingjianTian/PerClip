package com.sudox.perclip.screen

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo

data class AccessibilityNodeCandidate(
    val text: String,
    val contentDescription: String,
    val viewIdResourceName: String,
    val className: String,
    val clickable: Boolean,
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
    val rootLeft: Int,
    val rootTop: Int,
    val rootRight: Int,
    val rootBottom: Int,
)

object AccessibilityNodeTools {
    fun allNodes(root: AccessibilityNodeInfo?, maxNodes: Int = MAX_NODES): List<AccessibilityNodeInfo> {
        if (root == null) return emptyList()
        val nodes = mutableListOf<AccessibilityNodeInfo>()

        fun visit(node: AccessibilityNodeInfo?, depth: Int) {
            if (node == null || nodes.size >= maxNodes || depth > MAX_DEPTH) return
            nodes.add(node)
            for (index in 0 until node.childCount) {
                visit(node.getChild(index), depth + 1)
            }
        }

        visit(root, 0)
        return nodes
    }

    fun candidateFor(node: AccessibilityNodeInfo, root: AccessibilityNodeInfo): AccessibilityNodeCandidate {
        val bounds = Rect()
        val rootBounds = Rect()
        node.getBoundsInScreen(bounds)
        root.getBoundsInScreen(rootBounds)
        return AccessibilityNodeCandidate(
            text = node.text?.toString().orEmpty(),
            contentDescription = node.contentDescription?.toString().orEmpty(),
            viewIdResourceName = node.viewIdResourceName.orEmpty(),
            className = node.className?.toString().orEmpty(),
            clickable = node.isClickable,
            left = bounds.left,
            top = bounds.top,
            right = bounds.right,
            bottom = bounds.bottom,
            rootLeft = rootBounds.left,
            rootTop = rootBounds.top,
            rootRight = rootBounds.right,
            rootBottom = rootBounds.bottom,
        )
    }

    fun nearestClickable(node: AccessibilityNodeInfo?, maxDepth: Int = CLICKABLE_PARENT_MAX_DEPTH): AccessibilityNodeInfo? {
        var current = node
        var depth = 0
        while (current != null && depth <= maxDepth) {
            if (current.isClickable) return current
            current = current.parent
            depth += 1
        }
        return null
    }

    private const val MAX_DEPTH = 14
    private const val MAX_NODES = 420
    private const val CLICKABLE_PARENT_MAX_DEPTH = 4
}
