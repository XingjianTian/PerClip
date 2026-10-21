package com.sudox.perclip.screen

import com.sudox.perclip.ClipKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotNull
import org.junit.Test

class ScreenClipBuilderTest {
    @Test
    fun buildsSnapshotFromVisibleScreenText() {
        val snapshot = ScreenClipBuilder.buildSnapshot(
            packageName = "com.xingin.xhs",
            appLabel = "小红书",
            rawTexts = listOf(
                "返回",
                "夏天通勤穿搭公式",
                "作者 Alice",
                "https://xhslink.com/example",
                "夏天也能不费力穿得清爽。",
                "夏天也能不费力穿得清爽。",
            ),
            capturedAtEpochMs = 123L,
        )

        assertNotNull(snapshot)
        requireNotNull(snapshot)
        assertEquals("夏天通勤穿搭公式", snapshot.title)
        assertEquals("https://xhslink.com/example", snapshot.url)
        assertEquals(true, snapshot.text.contains("来源：小红书"))
        assertEquals(true, snapshot.text.contains("夏天也能不费力穿得清爽。"))
    }

    @Test
    fun convertsSnapshotToScreenClip() {
        val clip = ScreenClipBuilder.toSharedClip(
            ScreenClipSnapshot(
                packageName = "com.example.app",
                appLabel = "Example",
                title = "页面标题",
                text = "页面正文",
                url = "",
                capturedAtEpochMs = 123L,
            ),
        )

        assertEquals(ClipKind.ScreenClip, clip.kind)
        assertEquals("页面标题", clip.titleHint)
        assertEquals("Example · com.example.app", clip.sourceApp)
    }

    @Test
    fun convertsSnapshotWithUrlToUrlClip() {
        val clip = ScreenClipBuilder.toUrlClip(
            ScreenClipSnapshot(
                packageName = "com.xingin.xhs",
                appLabel = "小红书",
                title = "小红书笔记",
                text = "页面正文\n\n原始链接：https://xhslink.com/example",
                url = "https://xhslink.com/example",
                capturedAtEpochMs = 123L,
            ),
        )

        assertEquals(ClipKind.Url, clip.kind)
        assertEquals("小红书笔记", clip.titleHint)
        assertEquals("https://xhslink.com/example", clip.url)
        assertEquals(true, clip.text.contains("原始链接"))
        assertEquals("小红书 · com.xingin.xhs", clip.sourceApp)
    }

    @Test
    fun ignoresAccessibilityPermissionWarningDialogs() {
        val snapshot = ScreenClipBuilder.buildSnapshot(
            packageName = "com.oplus.safecenter",
            appLabel = "安全中心",
            rawTexts = listOf(
                "检测到“PerClip”获取无障碍权限",
                "无障碍权限允许应用查看屏幕内容并自动操作设备，可能影响您的隐私和资金安全",
                "关闭无障碍",
                "保持开启",
            ),
            capturedAtEpochMs = 123L,
        )

        assertNull(snapshot)
    }
}
