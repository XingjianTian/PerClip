package com.sudox.perclip.screen

import android.view.accessibility.AccessibilityNodeInfo

object AccessibilityNodeTextExtractor {
    fun extract(root: AccessibilityNodeInfo?, maxNodes: Int = MAX_NODES): List<String> {
        if (root == null) return emptyList()
        val texts = mutableListOf<String>()
        var visited = 0

        fun visit(node: AccessibilityNodeInfo?, depth: Int) {
            if (node == null || visited >= maxNodes || depth > MAX_DEPTH) return
            visited += 1

            if (node.isVisibleToUser) {
                node.text?.toString()?.let(texts::add)
                node.contentDescription?.toString()?.let(texts::add)
            }

            for (index in 0 until node.childCount) {
                visit(node.getChild(index), depth + 1)
            }
        }

        visit(root, 0)
        return texts
    }

    private const val MAX_DEPTH = 12
    private const val MAX_NODES = 300
}
