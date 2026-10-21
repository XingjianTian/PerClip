package com.sudox.perclip.screen.adapters

import com.sudox.perclip.screen.AccessibilityNodeCandidate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class XhsNodeMatcherTest {
    @Test
    fun explicitShareLabelWins() {
        val candidate = candidate(text = "分享", clickable = true)

        assertEquals(100, XhsNodeMatcher.shareScore(candidate))
    }

    @Test
    fun shareContentDescriptionWins() {
        val candidate = candidate(contentDescription = "分享给朋友", clickable = true)

        assertEquals(100, XhsNodeMatcher.shareScore(candidate))
    }

    @Test
    fun xhsMoreOperateViewIdWinsAsTopShareEntry() {
        val candidate = candidate(
            viewIdResourceName = "com.xingin.xhs:id/moreOperateIV",
            clickable = true,
            left = 1109,
            top = 192,
            right = 1200,
            bottom = 283,
        )

        assertEquals(110, XhsNodeMatcher.shareScore(candidate))
    }

    @Test
    fun topRightClickableIconIsConservativeFallback() {
        val candidate = candidate(
            clickable = true,
            left = 875,
            top = 96,
            right = 945,
            bottom = 166,
        )

        assertEquals(25, XhsNodeMatcher.shareScore(candidate))
    }

    @Test
    fun contentAreaRightSideClickableIsNotShareFallback() {
        val candidate = candidate(
            clickable = true,
            left = 1102,
            top = 1521,
            right = 1256,
            bottom = 1675,
        )

        assertNull(XhsNodeMatcher.shareScore(candidate))
    }

    @Test
    fun contentAreaShareLabelIsNotTopShareEntry() {
        val candidate = candidate(
            text = "分享",
            clickable = true,
            left = 544,
            top = 1521,
            right = 712,
            bottom = 1675,
        )

        assertNull(XhsNodeMatcher.shareScore(candidate))
    }

    @Test
    fun blockedShareLabelsAreNeverClicked() {
        val candidate = candidate(
            text = "关注",
            clickable = true,
            left = 800,
            top = 90,
            right = 940,
            bottom = 160,
        )

        assertNull(XhsNodeMatcher.shareScore(candidate))
    }

    @Test
    fun copyLinkButtonMatchesExpectedLabel() {
        assertTrue(XhsNodeMatcher.isCopyLinkButton(candidate(text = "复制链接", clickable = true)))
        assertTrue(XhsNodeMatcher.isCopyLinkButton(candidate(text = "复制 链接", clickable = true)))
        assertTrue(XhsNodeMatcher.isCopyLinkButton(candidate(text = "链接", clickable = false)))
    }

    @Test
    fun copyLinkButtonRequiresLinkMeaning() {
        assertFalse(XhsNodeMatcher.isCopyLinkButton(candidate(text = "复制文字", clickable = true)))
    }

    private fun candidate(
        text: String = "",
        contentDescription: String = "",
        viewIdResourceName: String = "",
        className: String = "",
        clickable: Boolean = false,
        left: Int = 0,
        top: Int = 0,
        right: Int = 100,
        bottom: Int = 100,
        rootLeft: Int = 0,
        rootTop: Int = 0,
        rootRight: Int = 1000,
        rootBottom: Int = 2200,
    ): AccessibilityNodeCandidate {
        return AccessibilityNodeCandidate(
            text = text,
            contentDescription = contentDescription,
            viewIdResourceName = viewIdResourceName,
            className = className,
            clickable = clickable,
            left = left,
            top = top,
            right = right,
            bottom = bottom,
            rootLeft = rootLeft,
            rootTop = rootTop,
            rootRight = rootRight,
            rootBottom = rootBottom,
        )
    }
}
