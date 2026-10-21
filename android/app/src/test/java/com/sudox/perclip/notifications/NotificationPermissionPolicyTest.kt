package com.sudox.perclip.notifications

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NotificationPermissionPolicyTest {
    @Test
    fun doesNotRequestBeforeAndroid13() {
        assertFalse(
            NotificationPermissionPolicy.shouldRequestPermission(
                sdkInt = 32,
                permissionGranted = false,
                persistentQuickEntryEnabled = true,
            ),
        )
    }

    @Test
    fun requestsOnlyForOptInQuickEntryWhenPermissionMissing() {
        assertTrue(
            NotificationPermissionPolicy.shouldRequestPermission(
                sdkInt = 33,
                permissionGranted = false,
                persistentQuickEntryEnabled = true,
            ),
        )
        assertFalse(
            NotificationPermissionPolicy.shouldRequestPermission(
                sdkInt = 33,
                permissionGranted = false,
                persistentQuickEntryEnabled = false,
            ),
        )
        assertFalse(
            NotificationPermissionPolicy.shouldRequestPermission(
                sdkInt = 33,
                permissionGranted = true,
                persistentQuickEntryEnabled = true,
            ),
        )
    }
}
