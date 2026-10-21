package com.sudox.perclip.share

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import java.util.UUID

object QuickNoteClipBuilder {
    fun build(text: String, id: String = UUID.randomUUID().toString()): SharedClip {
        val metadata = SharedTextParser.parse(text = text, subject = "")
        return SharedClip(
            id = id,
            kind = if (metadata.url.isNotBlank()) ClipKind.Url else ClipKind.Text,
            titleHint = metadata.titleHint.ifBlank { "快速闪记" },
            text = metadata.text,
            url = metadata.url,
            mimeType = "text/plain",
            sourceApp = "PerClip",
        )
    }
}
