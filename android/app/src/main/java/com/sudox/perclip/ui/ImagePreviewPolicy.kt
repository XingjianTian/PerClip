package com.sudox.perclip.ui

import com.sudox.perclip.ClipKind

object ImagePreviewPolicy {
    fun shouldShowThumbnail(kind: ClipKind, mimeTypes: List<String>): Boolean {
        return kind == ClipKind.Image || mimeTypes.firstOrNull().orEmpty().startsWith("image/")
    }
}
