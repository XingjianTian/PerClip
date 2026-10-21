package com.sudox.perclip.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class SourcePlatformPresentationTest {
    @Test
    fun resolvesSupportedPlatformSources() {
        assertEquals(SourcePlatform.Xiaohongshu, SourcePlatformResolver.resolve("com.xingin.xhs"))
        assertEquals(SourcePlatform.Zhihu, SourcePlatformResolver.resolve("com.zhihu.android"))
        assertEquals(SourcePlatform.WeChat, SourcePlatformResolver.resolve("com.tencent.mm"))
        assertEquals(SourcePlatform.Chrome, SourcePlatformResolver.resolve("com.android.chrome"))
        assertEquals(SourcePlatform.Bilibili, SourcePlatformResolver.resolve("tv.danmaku.bili"))
        assertEquals(SourcePlatform.Douyin, SourcePlatformResolver.resolve("com.ss.android.ugc.aweme"))
        assertEquals(SourcePlatform.Douyin, SourcePlatformResolver.resolve("抖音"))
        assertEquals(SourcePlatform.Medium, SourcePlatformResolver.resolve("com.medium.reader"))
        assertEquals(SourcePlatform.X, SourcePlatformResolver.resolve("x"))
        assertEquals(SourcePlatform.More, SourcePlatformResolver.resolve("more"))
        assertEquals(SourcePlatform.Figma, SourcePlatformResolver.resolve("com.figma.mirror"))
        assertEquals(SourcePlatform.Files, SourcePlatformResolver.resolve("com.google.android.documentsui"))
        assertEquals(SourcePlatform.Keep, SourcePlatformResolver.resolve("com.gotokeep.keep"))
        assertEquals(SourcePlatform.Douban, SourcePlatformResolver.resolve("com.douban.frodo"))
    }

    @Test
    fun usesUrlFallbackAndReadableGenericLabels() {
        assertEquals(SourcePlatform.Xiaohongshu, SourcePlatformResolver.resolve("", "https://www.xiaohongshu.com/explore/test"))
        assertEquals(SourcePlatform.Xiaohongshu, SourcePlatformResolver.resolve("", "https://xhslink.com/a/test"))
        assertEquals(SourcePlatform.Bilibili, SourcePlatformResolver.resolve("", "https://b23.tv/test"))
        assertEquals(SourcePlatform.Douyin, SourcePlatformResolver.resolve("", "https://v.douyin.com/test"))
        assertEquals(SourcePlatform.WeChat, SourcePlatformResolver.resolve("", "https://mp.weixin.qq.com/s/test"))
        assertEquals(SourcePlatform.WeChat, SourcePlatformResolver.resolve("wechat"))
        assertEquals(SourcePlatform.WeChat, SourcePlatformResolver.resolve("weixin"))
        assertEquals(SourcePlatform.WeChat, SourcePlatformResolver.resolve("微信"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("com.example.douyin.lookalike"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("", "https://douyin.com.evil.example/test"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("com.example.xhs.lookalike"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("", "https://xiaohongshu.com.evil.example/test"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("", "https://xhslink.com.evil.example/test"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("com.example.wechat.lookalike"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("com.tencent.mm.preview"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("", "https://mp.weixin.qq.com.evil.example/s/test"))
        assertEquals(SourcePlatform.Generic, SourcePlatformResolver.resolve("", "https://weixin.qq.com/s/test"))
        assertEquals(SourcePlatform.X, SourcePlatformResolver.resolve("", "https://x.com/perclip/status/1"))
        assertEquals("reader", SourcePlatformResolver.displayName("example.reader"))
        assertEquals("来源", SourcePlatformResolver.displayName(""))
    }
}
