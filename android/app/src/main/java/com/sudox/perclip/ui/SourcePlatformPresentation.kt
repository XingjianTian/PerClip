package com.sudox.perclip.ui

import androidx.annotation.DrawableRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sudox.perclip.R
import com.sudox.perclip.design.ColorTokens

enum class SourcePlatform(val displayName: String) {
    Xiaohongshu("小红书"),
    Zhihu("知乎"),
    WeChat("微信"),
    Chrome("Chrome"),
    Bilibili("哔哩哔哩"),
    Douyin("抖音"),
    X("X"),
    Medium("Medium"),
    Figma("Figma"),
    Files("文件"),
    Keep("Keep"),
    Douban("豆瓣"),
    PerClip("PerClip"),
    More("更多"),
    Generic("来源"),
}

object SourcePlatformResolver {
    fun resolve(sourceApp: String, url: String = ""): SourcePlatform {
        val raw = sourceApp.trim().lowercase()
        val normalizedUrl = url.trim().lowercase()
        return when {
            raw == "com.xingin.xhs" ||
                raw == "xiaohongshu" || raw == "xhs" || sourceApp.trim() == "小红书" ||
                normalizedUrl.hasExactHost("xiaohongshu.com") || normalizedUrl.hasExactHost("xhslink.com") -> SourcePlatform.Xiaohongshu
            "zhihu" in raw || "zhihu.com" in normalizedUrl -> SourcePlatform.Zhihu
            raw == "com.tencent.mm" || raw == "wechat" || raw == "weixin" ||
                sourceApp.trim() == "微信" || normalizedUrl.hasExactHost("mp.weixin.qq.com") -> SourcePlatform.WeChat
            "bilibili" in raw || "danmaku.bili" in raw || "b23.tv" in normalizedUrl || "bilibili.com" in normalizedUrl -> SourcePlatform.Bilibili
            raw == "com.ss.android.ugc.aweme" || raw == "com.ss.android.ugc.aweme.lite" ||
                raw == "douyin" || sourceApp.trim() == "抖音" || normalizedUrl.hasExactHost("douyin.com") -> SourcePlatform.Douyin
            raw == "x" || "twitter" in raw || "x.com" in normalizedUrl || "twitter.com" in normalizedUrl -> SourcePlatform.X
            "medium" in raw || "medium.com" in normalizedUrl -> SourcePlatform.Medium
            "figma" in raw -> SourcePlatform.Figma
            "documentsui" in raw || raw == "files" || raw.endsWith(".files") -> SourcePlatform.Files
            "gotokeep" in raw || raw == "keep" || raw.endsWith(".keep") -> SourcePlatform.Keep
            "douban" in raw || "frodo" in raw || "豆瓣" in sourceApp -> SourcePlatform.Douban
            "chrome" in raw || "googlechrome" in raw || raw == "com.android.chrome" -> SourcePlatform.Chrome
            "perclip" in raw -> SourcePlatform.PerClip
            raw == "more" -> SourcePlatform.More
            else -> SourcePlatform.Generic
        }
    }

    private fun String.hasExactHost(domain: String): Boolean {
        val host = runCatching { java.net.URI(this).host.orEmpty().lowercase() }.getOrDefault("")
        return host == domain || host.endsWith(".$domain")
    }

    fun displayName(sourceApp: String, url: String = ""): String {
        val platform = resolve(sourceApp, url)
        if (platform != SourcePlatform.Generic) return platform.displayName
        return sourceApp.substringAfterLast('.').trim().take(12).ifBlank { "来源" }
    }
}

@Composable
fun PerClipSourceIcon(
    sourceApp: String,
    modifier: Modifier = Modifier,
    url: String = "",
    compact: Boolean = false,
) {
    val platform = SourcePlatformResolver.resolve(sourceApp, url)
    val color = when (platform) {
        SourcePlatform.Xiaohongshu -> Color(0xFFFF2442)
        SourcePlatform.Zhihu -> Color(0xFF0084FF)
        SourcePlatform.WeChat -> Color(0xFF07C160)
        SourcePlatform.Chrome -> Color(0xFF4285F4)
        SourcePlatform.Bilibili -> Color(0xFF00A1D6)
        SourcePlatform.Douyin -> Color(0xFF161823)
        SourcePlatform.X -> Color.Black
        SourcePlatform.Medium -> Color.Black
        SourcePlatform.Figma -> Color(0xFFA259FF)
        SourcePlatform.Files -> Color(0xFF5F6B7A)
        SourcePlatform.Keep -> Color(0xFF24C789)
        SourcePlatform.Douban -> Color(0xFF2E963D)
        SourcePlatform.PerClip, SourcePlatform.More, SourcePlatform.Generic -> ColorTokens.FlashPurple
    }
    val mark = when (platform) {
        SourcePlatform.Xiaohongshu -> if (compact) "红" else "小红书"
        SourcePlatform.Zhihu -> "知"
        SourcePlatform.Medium -> "M"
        SourcePlatform.Figma -> "F"
        SourcePlatform.Files -> "文"
        SourcePlatform.Keep -> "K"
        SourcePlatform.Douban -> "豆"
        SourcePlatform.Douyin -> "抖"
        SourcePlatform.PerClip -> "P"
        SourcePlatform.X, SourcePlatform.More -> ""
        SourcePlatform.Generic -> sourceApp.substringAfterLast('.').trim().take(1).uppercase().ifBlank { "•" }
        else -> ""
    }
    @DrawableRes val iconRes = when (platform) {
        SourcePlatform.WeChat -> R.drawable.ic_brand_wechat
        SourcePlatform.Chrome -> R.drawable.ic_brand_chrome
        SourcePlatform.Bilibili -> R.drawable.ic_brand_bilibili
        SourcePlatform.X -> R.drawable.ic_brand_x
        SourcePlatform.More -> R.drawable.ic_brand_more
        else -> 0
    }
    Surface(modifier, color = color, shape = CircleShape) {
        Box(contentAlignment = Alignment.Center) {
            if (iconRes != 0) {
                Icon(
                    painter = painterResource(iconRes),
                    contentDescription = platform.displayName,
                    tint = Color.Unspecified,
                    modifier = Modifier.fillMaxSize().padding(if (compact) 3.dp else 8.dp),
                )
            } else {
                Text(
                    text = mark,
                    color = Color.White,
                    fontWeight = FontWeight.Black,
                    fontSize = if (compact) 7.sp else if (mark.length > 1) 9.sp else 17.sp,
                    style = if (compact) MaterialTheme.typography.labelSmall else MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                )
            }
        }
    }
}
