package com.sudox.perclip

object PerClipActions {
    const val ACTION_NEW_NOTE = "com.sudox.perclip.action.NEW_NOTE"
    const val ACTION_CAPTURE_SCREEN = "com.sudox.perclip.action.CAPTURE_SCREEN"
    const val ACTION_COMPLETE_AUTO_CAPTURE = "com.sudox.perclip.action.COMPLETE_AUTO_CAPTURE"
    const val ACTION_RECENTS = "com.sudox.perclip.action.RECENTS"
    const val ACTION_SETTINGS = "com.sudox.perclip.action.SETTINGS"
}

object LaunchNavigationPolicy {
    fun shouldApply(navigationRevision: Int, appliedNavigationRevision: Int): Boolean {
        return navigationRevision != appliedNavigationRevision
    }
}

enum class StartTab(val index: Int) {
    Save(0),
    Recents(1),
    Recall(2),
    Settings(3),
    ;

    companion object {
        fun fromAction(action: String?): StartTab = when (action) {
            PerClipActions.ACTION_RECENTS -> Recents
            PerClipActions.ACTION_SETTINGS -> Settings
            else -> Save
        }
    }
}
