package com.sudox.perclip.share

import org.junit.Assert.assertEquals
import org.junit.Test

class SharedTextParserTest {
    @Test
    fun infersTitleFromTextLineBeforeUrl() {
        val metadata = SharedTextParser.parse(
            text = """
                一篇值得保存的文章
                https://example.com/posts/1
            """.trimIndent(),
            subject = "",
        )

        assertEquals("一篇值得保存的文章", metadata.titleHint)
        assertEquals("https://example.com/posts/1", metadata.url)
    }

    @Test
    fun trimsTrailingPunctuationFromSharedUrl() {
        val metadata = SharedTextParser.parse(
            text = "推荐这个链接：https://example.com/read/42。",
            subject = "",
        )

        assertEquals("推荐这个链接", metadata.titleHint)
        assertEquals("https://example.com/read/42", metadata.url)
    }

    @Test
    fun subjectWinsOverInferredTitle() {
        val metadata = SharedTextParser.parse(
            text = "正文标题\nhttps://example.com",
            subject = "浏览器标题",
        )

        assertEquals("浏览器标题", metadata.titleHint)
        assertEquals("https://example.com", metadata.url)
    }

    @Test
    fun preservesWeChatSubjectOfficialAccountUrlAndOriginalText() {
        val shared = "https://mp.weixin.qq.com/s/syntheticArticle123"

        val metadata = SharedTextParser.parse(
            text = shared,
            subject = "公众号 payload 内已有的文章标题",
            sourceApp = "com.tencent.mm",
        )

        assertEquals("公众号 payload 内已有的文章标题", metadata.titleHint)
        assertEquals("https://mp.weixin.qq.com/s/syntheticArticle123", metadata.url)
        assertEquals(shared, metadata.text)
    }

    @Test
    fun genericPerClipSmokeSubjectDoesNotHideSharedTextTitle() {
        val metadata = SharedTextParser.parse(
            text = "外网域名入库测试 https://xhslink.com/o/perclip-public-domain-test 戳进【小红书】看看这篇好文！",
            subject = "PerClip smoke",
        )

        assertEquals("外网域名入库测试", metadata.titleHint)
        assertEquals("https://xhslink.com/o/perclip-public-domain-test", metadata.url)
    }

    @Test
    fun parsesStandardXiaohongshuShareTitleAndShortUrl() {
        val shared = "一份 payload 里已有的露营清单 #周末去哪里 https://xhslink.com/a/AbC123 戳进【小红书】看看这篇好文！"

        val metadata = SharedTextParser.parse(
            text = shared,
            subject = "",
            sourceApp = "com.xingin.xhs",
        )

        assertEquals("一份 payload 里已有的露营清单 #周末去哪里", metadata.titleHint)
        assertEquals("https://xhslink.com/a/AbC123", metadata.url)
        assertEquals(shared, metadata.text)
    }

    @Test
    fun parsesCanonicalXiaohongshuUrlAndKeepsLookalikeWrapper() {
        val canonical = SharedTextParser.parse(
            text = "一篇图文笔记 https://www.xiaohongshu.com/explore/abc123。",
            subject = "",
        )
        val lookalike = SharedTextParser.parse(
            text = "一段普通文本 https://xiaohongshu.com.evil.example/note 戳进【小红书】看看这篇好文！",
            subject = "",
            sourceApp = "com.example.xhs.lookalike",
        )

        assertEquals("一篇图文笔记", canonical.titleHint)
        assertEquals("https://www.xiaohongshu.com/explore/abc123", canonical.url)
        assertEquals("一段普通文本  戳进【小红书】看看这篇好文", lookalike.titleHint)
    }

    @Test
    fun removesXiaohongshuCopyOpenSuffixOnlyForConfirmedSource() {
        val shared = "一条图片笔记 https://xhslink.com/m/xyz 复制这条信息，打开【小红书】App 查看精彩内容！"

        val metadata = SharedTextParser.parse(text = shared, subject = "")

        assertEquals("一条图片笔记", metadata.titleHint)
        assertEquals(shared, metadata.text)
    }

    @Test
    fun plainTextUsesManualNoteTitle() {
        val metadata = SharedTextParser.parse(
            text = "这是一段没有链接的文字",
            subject = "",
        )

        assertEquals("文字闪记", metadata.titleHint)
        assertEquals("", metadata.url)
        assertEquals("这是一段没有链接的文字", metadata.text)
    }

    @Test
    fun urlOnlyTextUsesFallbackLinkTitle() {
        val metadata = SharedTextParser.parse(
            text = "https://example.com/",
            subject = "",
        )

        assertEquals("链接收藏", metadata.titleHint)
        assertEquals("https://example.com/", metadata.url)
    }

    @Test
    fun parsesStandardDouyinShareCaptionAndShortUrl() {
        val shared = "复制打开抖音，看看【示例作者的作品】 这是 payload 里已有的视频简介 #科普 https://v.douyin.com/AbC123/ Xy9:/ 08/12"

        val metadata = SharedTextParser.parse(
            text = shared,
            subject = "",
            sourceApp = "com.ss.android.ugc.aweme",
        )

        assertEquals("这是 payload 里已有的视频简介 #科普", metadata.titleHint)
        assertEquals("https://v.douyin.com/AbC123/", metadata.url)
        assertEquals(shared, metadata.text)
    }

    @Test
    fun parsesCanonicalDouyinUrlAndLeavesLookalikeWrapperUntouched() {
        val canonical = SharedTextParser.parse(
            text = "一条图文说明 https://www.douyin.com/note/12345。",
            subject = "",
        )
        val lookalike = SharedTextParser.parse(
            text = "复制打开抖音，看看【示例作者的作品】 https://douyin.com.evil.example/note/1",
            subject = "",
        )

        assertEquals("一条图文说明", canonical.titleHint)
        assertEquals("https://www.douyin.com/note/12345", canonical.url)
        assertEquals("复制打开抖音，看看【示例作者的作品", lookalike.titleHint)
    }

    @Test
    fun removesDouyinNumericTokenAndAlternateDateCodeSuffix() {
        val shared = "7.58 复制打开抖音，看看【示例作者的作品】 另一条 payload caption https://v.douyin.com/Z9x8/ 08/12 Ab3:/"

        val metadata = SharedTextParser.parse(text = shared, subject = "")

        assertEquals("另一条 payload caption", metadata.titleHint)
        assertEquals("https://v.douyin.com/Z9x8/", metadata.url)
        assertEquals(shared, metadata.text)
    }
}
