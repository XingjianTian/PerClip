package com.sudox.perclip.notifications

object NotificationPermissionPolicy {
    const val ANDROID_13_API = 33

    fun shouldRequestPermission(
        sdkInt: Int,
        permissionGranted: Boolean,
        persistentQuickEntryEnabled: Boolean,
    ): Boolean {
        return sdkInt >= ANDROID_13_API && !permissionGranted && persistentQuickEntryEnabled
    }
}
