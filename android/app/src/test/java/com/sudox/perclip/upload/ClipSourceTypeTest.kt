package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import org.junit.Assert.assertEquals
import org.junit.Test

class ClipSourceTypeTest {
    @Test
    fun mapsClipKindsToServerSourceTypes() {
        assertEquals("text", ClipKind.Text.toServerSourceType())
        assertEquals("url", ClipKind.Url.toServerSourceType())
        assertEquals("screen_clip", ClipKind.ScreenClip.toServerSourceType())
        assertEquals("image", ClipKind.Image.toServerSourceType())
        assertEquals("file", ClipKind.File.toServerSourceType())
        assertEquals("file", ClipKind.Multiple.toServerSourceType())
        assertEquals("text", ClipKind.Unknown.toServerSourceType())
    }
}
