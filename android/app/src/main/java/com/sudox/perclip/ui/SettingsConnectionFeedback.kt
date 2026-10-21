package com.sudox.perclip.ui

object SettingsConnectionFeedback {
    fun successMessage(baseMessage: String, requeuedCount: Int): String {
        if (requeuedCount <= 0) return baseMessage
        return "$baseMessage 已重新排队 $requeuedCount 条待同步记录。"
    }
}
