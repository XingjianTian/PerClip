package com.sudox.perclip.screen

data class ScreenClipSnapshot(
    val packageName: String,
    val appLabel: String,
    val title: String,
    val text: String,
    val url: String,
    val capturedAtEpochMs: Long,
)
