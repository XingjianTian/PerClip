package com.sudox.perclip.screen.adapters

import com.sudox.perclip.screen.AccessibilityNodeCandidate

object XhsNodeMatcher {
    fun shareScore(candidate: AccessibilityNodeCandidate): Int? {
        val label = candidate.labelText()
        if (label.containsAny(blockedShareLabels)) return null
        if (candidate.viewIdResourceName.contains("moreOperateIV", ignoreCase = true) && isTopBarCandidate(candidate)) {
            return 110
        }
        if ((label.contains("分享") || candidate.viewIdResourceName.contains("share", ignoreCase = true)) &&
            isTopBarCandidate(candidate)
        ) {
            return 100
        }
        return if (isTopRightClickable(candidate)) 25 else null
    }

    fun isCopyLinkButton(candidate: AccessibilityNodeCandidate): Boolean {
        val semanticLabel = candidate.semanticLabelText()
        val fullLabel = candidate.labelText()
        return semanticLabel.contains("复制链接") ||
            semanticLabel.contains("复制 链接") ||
            semanticLabel == "链接" ||
            candidate.viewIdResourceName.contains("copy", ignoreCase = true) && fullLabel.contains("链接")
    }

    private fun isTopRightClickable(candidate: AccessibilityNodeCandidate): Boolean {
        val rootWidth = (candidate.rootRight - candidate.rootLeft).coerceAtLeast(1)
        val rootHeight = (candidate.rootBottom - candidate.rootTop).coerceAtLeast(1)
        val nodeWidth = candidate.right - candidate.left
        val nodeHeight = candidate.bottom - candidate.top
        val centerX = candidate.left + nodeWidth / 2
        val centerY = candidate.top + nodeHeight / 2
        val nearRight = centerX > candidate.rootLeft + (rootWidth * 0.78f)
        val nearTop = isTopBarCandidate(candidate)
        val iconSized = nodeWidth in 32..220 && nodeHeight in 32..220
        return nearRight && nearTop && iconSized
    }

    private fun isTopBarCandidate(candidate: AccessibilityNodeCandidate): Boolean {
        val nodeHeight = candidate.bottom - candidate.top
        val centerY = candidate.top + nodeHeight / 2
        return centerY < TOP_BAR_MAX_CENTER_Y_PX
    }

    private fun AccessibilityNodeCandidate.labelText(): String {
        return listOf(text, contentDescription, viewIdResourceName, className)
            .joinToString(" ")
            .trim()
    }

    private fun AccessibilityNodeCandidate.semanticLabelText(): String {
        return listOf(text, contentDescription)
            .filter { it.isNotBlank() }
            .joinToString(" ")
            .trim()
    }

    private fun String.containsAny(values: Set<String>): Boolean {
        return values.any { contains(it, ignoreCase = true) }
    }

    private val blockedShareLabels = setOf(
        "关注",
        "评论",
        "收藏",
        "点赞",
        "不喜欢",
        "返回",
        "更多评论",
        "留下你的想法",
    )

    private const val TOP_BAR_MAX_CENTER_Y_PX = 520
}
