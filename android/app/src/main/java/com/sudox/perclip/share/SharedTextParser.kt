package com.sudox.perclip.share

object SharedTextParser {
    private val urlRegex = Regex("""https?://[^\s<>"']+""")
    private val trailingUrlPunctuation = setOf(
        '.', ',', ';', ':', '!', '?',
        '。', '，', '；', '：', '！', '？',
        ')', '）', ']', '】', '}', '》',
    )

    fun parse(text: String, subject: String, sourceApp: String = ""): SharedTextMetadata {
        val trimmedText = text.trim()
        val trimmedSubject = subject.trim()
        val url = urlRegex.find(trimmedText)?.value.orEmpty().trimTrailingUrlPunctuation()
        val isXiaohongshuShare = isXiaohongshuShare(sourceApp, url)
        val isDouyinShare = isDouyinShare(sourceApp, url)
        val title = when {
            trimmedSubject.isNotBlank() && !isGenericSubject(trimmedSubject) -> trimmedSubject
            url.isNotBlank() -> titleFromSharedText(
                text = trimmedText,
                url = url,
                isXiaohongshuShare = isXiaohongshuShare,
                isDouyinShare = isDouyinShare,
            ).ifBlank { "链接收藏" }
            else -> "文字闪记"
        }
        return SharedTextMetadata(
            text = trimmedText,
            url = url,
            titleHint = title,
        )
    }

    private fun titleFromSharedText(
        text: String,
        url: String,
        isXiaohongshuShare: Boolean,
        isDouyinShare: Boolean,
    ): String {
        return text
            .lineSequence()
            .map { line ->
                line.replace(url, "")
                    .replace(url.trimEnd('/'), "")
                    .let { value -> if (isXiaohongshuShare) value.removeXiaohongshuShareWrapper() else value }
                    .let { value -> if (isDouyinShare) value.removeDouyinShareWrapper() else value }
                    .trim()
                    .trim('-', '—', '|')
                    .trimTrailingSharedTextPunctuation()
                    .trim()
            }
            .firstOrNull { it.isNotBlank() }
            .orEmpty()
            .take(MAX_TITLE_LENGTH)
    }

    private fun String.trimTrailingUrlPunctuation(): String {
        var value = this
        while (value.isNotEmpty() && trailingUrlPunctuation.contains(value.last())) {
            value = value.dropLast(1)
        }
        return value
    }

    private fun String.trimTrailingSharedTextPunctuation(): String {
        var value = this
        while (value.isNotEmpty() && trailingSharedTextPunctuation.contains(value.last())) {
            value = value.dropLast(1)
        }
        return value
    }

    private fun String.removeXiaohongshuShareWrapper(): String {
        var value = this
        xiaohongshuShareBoilerplate.forEach { fragment ->
            value = value.replace(fragment, " ")
        }
        return value
    }

    private fun isXiaohongshuShare(sourceApp: String, url: String): Boolean {
        val normalizedSource = sourceApp.trim().lowercase()
        if (normalizedSource in xiaohongshuPackages || normalizedSource == "xiaohongshu" ||
            normalizedSource == "xhs" || sourceApp.trim() == "小红书"
        ) return true
        val host = runCatching { java.net.URI(url).host.orEmpty().lowercase() }.getOrDefault("")
        return host == "xiaohongshu.com" || host.endsWith(".xiaohongshu.com") ||
            host == "xhslink.com" || host.endsWith(".xhslink.com")
    }

    private fun String.removeDouyinShareWrapper(): String {
        return replace(douyinLeadingToken, "")
            .replace(douyinCopyOpenPrefix, " ")
            .replace(douyinAuthorWork, " ")
            .replace(douyinShareSuffix, " ")
    }

    private fun isDouyinShare(sourceApp: String, url: String): Boolean {
        val normalizedSource = sourceApp.trim().lowercase()
        if (normalizedSource in douyinPackages || normalizedSource == "douyin" || sourceApp.trim() == "抖音") return true
        val host = runCatching { java.net.URI(url).host.orEmpty().lowercase() }.getOrDefault("")
        return host == "douyin.com" || host.endsWith(".douyin.com")
    }

    private const val MAX_TITLE_LENGTH = 80
    private val trailingSharedTextPunctuation = trailingUrlPunctuation + setOf('-', '—', '|')
    private val xiaohongshuShareBoilerplate = listOf(
        "戳进【小红书】看看这篇好文！",
        "戳进【小红书】看看这篇好文!",
        "复制这条信息，打开【小红书】App 查看精彩内容！",
        "复制这条信息，打开【小红书】App 查看精彩内容!",
    )
    private val xiaohongshuPackages = setOf(
        "com.xingin.xhs",
    )
    private val douyinPackages = setOf(
        "com.ss.android.ugc.aweme",
        "com.ss.android.ugc.aweme.lite",
    )
    private val douyinCopyOpenPrefix = Regex("""(?:复制|長按複製|长按复制)?\s*打开抖音[，,]?\s*看看""")
    private val douyinAuthorWork = Regex("""【[^】]{1,40}的作品】""")
    private val douyinLeadingToken = Regex("""^\s*\d{1,2}(?:\.\d{1,2})?\s+(?=(?:复制|長按複製|长按复制)?\s*打开抖音)""")
    private val douyinShareSuffix = Regex(
        """\s+(?:(?:[A-Za-z0-9]{2,12}:/\s*)?\d{1,2}/\d{1,2}(?:\s*[A-Za-z0-9]{2,12}:/)?|[A-Za-z0-9]{2,12}:/)\s*$""",
    )

    private fun isGenericSubject(subject: String): Boolean {
        val normalized = subject.trim().lowercase()
        return normalized == "perclip smoke" ||
            normalized.startsWith("perclip smoke ") ||
            normalized == "perclip entrypoint smoke" ||
            normalized.startsWith("perclip entrypoint ") ||
            normalized == "perclip local e2e" ||
            normalized.startsWith("perclip local ")
    }
}

data class SharedTextMetadata(
    val text: String,
    val url: String,
    val titleHint: String,
)
