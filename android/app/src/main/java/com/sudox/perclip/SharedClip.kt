package com.sudox.perclip

import android.net.Uri

data class SharedClip(
    val id: String,
    val kind: ClipKind,
    val titleHint: String,
    val text: String = "",
    val url: String = "",
    val items: List<SharedClipItem> = emptyList(),
    val mimeType: String = "",
    val sourceApp: String = "",
)

data class SharedClipItem(
    val uri: Uri,
    val displayName: String,
    val mimeType: String,
    val sizeBytes: Long?,
)

enum class ClipKind {
    Text,
    Url,
    ScreenClip,
    Image,
    File,
    Multiple,
    Unknown,
}

fun ClipKind.label(): String = when (this) {
    ClipKind.Text -> "文字"
    ClipKind.Url -> "链接"
    ClipKind.ScreenClip -> "屏幕闪记"
    ClipKind.Image -> "图片"
    ClipKind.File -> "文件"
    ClipKind.Multiple -> "多文件"
    ClipKind.Unknown -> "未知"
}
