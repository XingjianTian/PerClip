package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.upload.UploadRecord

object InboxRecordPresentation {
    private val urlRegex = Regex("""https?://[^\s<>"']+""")
    private val whitespaceRegex = Regex("""\s+""")
    private val genericTitles = setOf(
        "perclip smoke",
        "perclip entrypoint smoke",
        "perclip local e2e",
        "文字闪记",
        "链接收藏",
        "未命名收藏",
    )
    private val boilerplateFragments = listOf(
        "戳进【小红书】看看这篇好文！",
        "戳进【小红书】看看这篇好文!",
        "复制这条信息，打开【小红书】App 查看精彩内容！",
        "复制这条信息，打开【小红书】App 查看精彩内容!",
    )

    fun title(record: UploadRecord): String {
        val clip = record.clip
        val titleHint = clip.titleHint.trim()
        val inferred = titleFromContent(clip)
        return when {
            shouldPreferInferredTitle(titleHint, inferred) -> inferred
            titleHint.isNotBlank() -> titleHint
            inferred.isNotBlank() -> inferred
            clip.items.isNotEmpty() -> clip.items.first().displayName.ifBlank { clip.kind.fallbackTitle() }
            else -> clip.kind.fallbackTitle()
        }.limitTitle()
    }

    fun summary(record: UploadRecord): String {
        val clip = record.clip
        val title = title(record)
        val enrichmentSummary = record.metadata.enrichmentSummary
            .ifBlank { record.metadata.summary }
            .trim()
            .takeIf { it.isNotBlank() }
        if (enrichmentSummary != null) {
            return enrichmentSummary.limitSummary()
        }
        val noteSummary = cleanedText(record.note).takeIf { it.isNotBlank() }
        if (noteSummary != null) {
            return noteSummary.limitSummary()
        }
        val textSummary = cleanedText(clip.text)
            .removePrefix(title)
            .trim(' ', '-', '—', '|', ':', '：')
            .takeIf { it.isNotBlank() && it != title }
        return when {
            textSummary != null -> textSummary.limitSummary()
            clip.url.isNotBlank() -> clip.url.limitSummary()
            clip.items.isNotEmpty() -> clip.items.joinToString("、") { item ->
                val size = ClipPreviewMetadata.formatByteSize(item.sizeBytes)
                if (size == null) item.displayName else "${item.displayName} · $size"
            }.limitSummary()
            record.message.isNotBlank() -> record.message.limitSummary()
            else -> "暂无内容摘要"
        }
    }

    fun detailLines(record: UploadRecord): List<Pair<String, String>> {
        val clip = record.clip
        return buildList {
            cleanedText(clip.text).takeIf { it.isNotBlank() }?.let { add("内容" to it) }
            clip.url.trim().takeIf { it.isNotBlank() }?.let { add("链接" to it) }
            clip.items.takeIf { it.isNotEmpty() }?.let { items ->
                add(
                    "文件" to items.joinToString("\n") { item ->
                        val size = ClipPreviewMetadata.formatByteSize(item.sizeBytes)
                        listOfNotNull(item.displayName, item.mimeType.takeIf { it.isNotBlank() }, size)
                            .joinToString(" · ")
                    },
                )
            }
            clip.sourceApp.trim().takeIf { it.isNotBlank() }?.let { add("来源" to it) }
            record.message.trim().takeIf { it.isNotBlank() }?.let { add("状态" to it) }
            record.remotePath.trim().takeIf { it.isNotBlank() }?.let { add("存放地址" to it) }
        }
    }

    private fun shouldPreferInferredTitle(titleHint: String, inferred: String): Boolean {
        if (inferred.isBlank()) return false
        val normalized = titleHint.trim().lowercase()
        return titleHint.isBlank() ||
            genericTitles.contains(normalized) ||
            normalized.startsWith("perclip smoke") ||
            normalized.startsWith("perclip entrypoint")
    }

    private fun titleFromContent(clip: SharedClip): String {
        val textTitle = cleanedText(clip.text)
            .lineSequence()
            .map { it.trim(' ', '-', '—', '|', ':', '：') }
            .firstOrNull { it.isNotBlank() }
            .orEmpty()
        return when {
            textTitle.isNotBlank() -> textTitle
            clip.items.isNotEmpty() -> clip.items.first().displayName
            clip.url.isNotBlank() -> clip.url
            else -> ""
        }
    }

    private fun cleanedText(text: String): String {
        if (text.isBlank()) return ""
        var value = text.trim()
        urlRegex.findAll(value).forEach { match ->
            value = value.replace(match.value, " ")
        }
        boilerplateFragments.forEach { fragment ->
            value = value.replace(fragment, " ")
        }
        return value
            .replace(whitespaceRegex, " ")
            .trim(' ', '-', '—', '|', ':', '：', '。', '，', ',', '.', '！', '!', '？', '?')
    }

    private fun String.limitTitle(): String = trim().let { value ->
        if (value.length <= 42) value else value.take(41).trimEnd() + "…"
    }

    private fun String.limitSummary(): String = trim().let { value ->
        if (value.length <= 110) value else value.take(109).trimEnd() + "…"
    }

    private fun ClipKind.fallbackTitle(): String = when (this) {
        ClipKind.Url -> "链接收藏"
        ClipKind.Text -> "文字闪记"
        ClipKind.ScreenClip -> "屏幕闪记"
        ClipKind.Image -> "图片归档"
        ClipKind.File -> "文件归档"
        ClipKind.Multiple -> "批量归档"
        ClipKind.Unknown -> "未命名收藏"
    }
}
