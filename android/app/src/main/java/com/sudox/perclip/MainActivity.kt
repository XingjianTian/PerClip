package com.sudox.perclip

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.sudox.perclip.config.PerClipSettingsStore
import com.sudox.perclip.config.AppThemeMode
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.sudox.perclip.design.PerClipTheme
import com.sudox.perclip.notifications.NotificationPermissionPolicy
import com.sudox.perclip.notifications.QuickEntryNotificationHelper
import com.sudox.perclip.share.SharingShortcutPublisher
import com.sudox.perclip.ui.PerClipApp

class MainActivity : ComponentActivity() {
    private var startTab by mutableStateOf(StartTab.Save)
    private var navigationRevision by mutableIntStateOf(0)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val initialSettings = PerClipSettingsStore(this).load()
        var themeMode by mutableStateOf(initialSettings.themeMode)
        requestNotificationPermissionIfNeeded(initialSettings.persistentQuickEntry)
        SharingShortcutPublisher.publish(this)
        handleIncomingIntent(intent)

        setContent {
            PerClipTheme(darkTheme = themeMode.resolve(isSystemInDarkTheme())) {
                PerClipApp(
                    startTab = startTab,
                    navigationRevision = navigationRevision,
                    onRequestNotificationPermission = {
                        requestNotificationPermissionIfNeeded(persistentQuickEntryEnabled = true)
                    },
                    onThemeModeChanged = { themeMode = it },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleIncomingIntent(intent: Intent) {
        navigationRevision += 1
        startTab = StartTab.fromAction(intent.action)
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQUEST_NOTIFICATIONS) return
        val granted = grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
        if (granted && PerClipSettingsStore(this).load().persistentQuickEntry) {
            QuickEntryNotificationHelper(this).show()
        }
    }

    private fun requestNotificationPermissionIfNeeded(persistentQuickEntryEnabled: Boolean) {
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (NotificationPermissionPolicy.shouldRequestPermission(
                sdkInt = Build.VERSION.SDK_INT,
                permissionGranted = granted,
                persistentQuickEntryEnabled = persistentQuickEntryEnabled,
            )
        ) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                REQUEST_NOTIFICATIONS,
            )
        }
    }

    companion object {
        private const val REQUEST_NOTIFICATIONS = 1001
    }
}
