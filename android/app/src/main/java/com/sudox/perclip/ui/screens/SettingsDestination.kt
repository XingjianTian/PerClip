package com.sudox.perclip.ui.screens

import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

sealed interface SettingsDestination {
    data object Home : SettingsDestination
    data object Connection : SettingsDestination
    data object CaptureAndIngest : SettingsDestination
    data object Appearance : SettingsDestination
    data object KnowledgeManagement : SettingsDestination
    data object RecallDisplayManagement : SettingsDestination
}

object SettingsNavigation {
    fun back(destination: SettingsDestination): SettingsDestination = SettingsDestination.Home

    fun title(destination: SettingsDestination): String = when (destination) {
        SettingsDestination.Home -> "设置"
        SettingsDestination.Connection -> "连接设置"
        SettingsDestination.CaptureAndIngest -> "记忆抓取设置"
        SettingsDestination.Appearance -> "外观"
        is SettingsDestination.KnowledgeManagement -> "知识库管理"
        SettingsDestination.RecallDisplayManagement -> "记忆星球设置"
    }
}

@Stable
class SettingsStateHolder(initial: SettingsDestination = SettingsDestination.Home) {
    var destination by mutableStateOf(initial)
        private set

    fun navigate(next: SettingsDestination) { destination = next }
    fun back() { destination = SettingsNavigation.back(destination) }
    fun showHome() { destination = SettingsDestination.Home }
}
