package com.sudox.perclip.screen.adapters

import java.net.URI

object XhsLinkValidator {
    private val urlRegex = Regex("""https?://[^\s，。；、）)]+""", RegexOption.IGNORE_CASE)

    fun extractXhsUrl(text: String): String {
        return urlRegex.findAll(text)
            .map { it.value.trimEnd('.', ',', '，', '。', ';', '；') }
            .firstOrNull(::isXhsUrl)
            .orEmpty()
    }

    fun isXhsUrl(url: String): Boolean {
        val host = runCatching { URI(url).host.orEmpty().lowercase() }.getOrDefault("")
        return host == "xhslink.com" ||
            host.endsWith(".xhslink.com") ||
            host == "xiaohongshu.com" ||
            host.endsWith(".xiaohongshu.com")
    }
}
