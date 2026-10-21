package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind

fun ClipKind.toServerSourceType(): String = when (this) {
    ClipKind.Text -> "text"
    ClipKind.Url -> "url"
    ClipKind.ScreenClip -> "screen_clip"
    ClipKind.Image -> "image"
    ClipKind.File -> "file"
    ClipKind.Multiple -> "file"
    ClipKind.Unknown -> "text"
}
