package com.sudox.perclip.screen

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import java.time.Instant
import java.util.UUID

object ScreenClipBuilder {
    private val urlRegex = Regex("""https?://[^\s，。；、）)]+""", RegexOption.IGNORE_CASE)
    private val whitespaceRegex = Regex("\\s+")
    private val noisyLines = setOf(
        "返回",
        "更多",
        "分享",
        "评论",
        "点赞",
        "收藏",
        "关注",
        "搜索",
        "首页",
        "消息",
        "我",
    )

    fun buildSnapshot(
        packageName: String,
        appLabel: String,
        rawTexts: List<String>,
        capturedAtEpochMs: Long = System.currentTimeMillis(),
    ): ScreenClipSnapshot? {
        val lines = normalizeLines(rawTexts)
        if (lines.isEmpty()) return null
        if (looksLikePermissionWarning(lines)) return null

        val url = lines.firstNotNullOfOrNull { line -> urlRegex.find(line)?.value }.orEmpty()
        val title = chooseTitle(lines, fallback = appLabel)
        val body = buildBody(
            appLabel = appLabel,
            packageName = packageName,
            capturedAtEpochMs = capturedAtEpochMs,
            lines = lines,
        )

        return ScreenClipSnapshot(
            packageName = packageName,
            appLabel = appLabel.ifBlank { packageName },
            title = title,
            text = body,
            url = url,
            capturedAtEpochMs = capturedAtEpochMs,
        )
    }

    fun toSharedClip(snapshot: ScreenClipSnapshot): SharedClip {
        return SharedClip(
            id = "screen-${snapshot.capturedAtEpochMs}-${UUID.randomUUID()}",
            kind = ClipKind.ScreenClip,
            titleHint = snapshot.title,
            text = snapshot.text,
            url = snapshot.url,
            mimeType = "text/plain",
            sourceApp = sourceAppLabel(snapshot),
        )
    }

    fun toUrlClip(snapshot: ScreenClipSnapshot): SharedClip {
        return SharedClip(
            id = "url-${snapshot.capturedAtEpochMs}-${UUID.randomUUID()}",
            kind = ClipKind.Url,
            titleHint = snapshot.title,
            text = snapshot.text,
            url = snapshot.url,
            mimeType = "text/plain",
            sourceApp = sourceAppLabel(snapshot),
        )
    }

    fun normalizeLines(rawTexts: List<String>): List<String> {
        val seen = linkedSetOf<String>()
        rawTexts.mapNotNullTo(seen) { raw ->
            val line = raw
                .replace('\n', ' ')
                .replace('\r', ' ')
                .replace(whitespaceRegex, " ")
                .trim()
            line.takeIf { isMeaningfulLine(it) }
        }
        return seen.take(MAX_LINES)
    }

    private fun chooseTitle(lines: List<String>, fallback: String): String {
        return lines.firstOrNull { line ->
            val normalized = line.trim()
            normalized.length in 4..80 &&
                normalized !in noisyLines &&
                !urlRegex.containsMatchIn(normalized)
        }?.trimEnd('。', '，', ',', '.', ' ') ?: fallback.ifBlank { "当前屏幕闪记" }
    }

    private fun buildBody(
        appLabel: String,
        packageName: String,
        capturedAtEpochMs: Long,
        lines: List<String>,
    ): String {
        val header = buildList {
            add("来源：${appLabel.ifBlank { packageName }}")
            if (packageName.isNotBlank()) add("包名：$packageName")
            add("捕获时间：${Instant.ofEpochMilli(capturedAtEpochMs)}")
        }
        return (header + "" + lines.take(MAX_BODY_LINES)).joinToString("\n")
    }

    private fun sourceAppLabel(snapshot: ScreenClipSnapshot): String {
        return buildList {
            if (snapshot.appLabel.isNotBlank()) add(snapshot.appLabel)
            if (snapshot.packageName.isNotBlank() && snapshot.packageName != snapshot.appLabel) add(snapshot.packageName)
        }.joinToString(" · ")
    }

    private fun isMeaningfulLine(line: String): Boolean {
        if (line.length < 2) return false
        if (line.length <= 4 && line in noisyLines) return false
        if (line.all { it.isWhitespace() || it in "·•-_|/" }) return false
        return true
    }

    private fun looksLikePermissionWarning(lines: List<String>): Boolean {
        val joined = lines.take(8).joinToString(" ")
        return joined.contains("获取无障碍权限") ||
            joined.contains("无障碍权限允许应用查看屏幕内容") ||
            joined.contains("关闭无障碍") && joined.contains("保持开启")
    }

    private const val MAX_LINES = 80
    private const val MAX_BODY_LINES = 50
}
