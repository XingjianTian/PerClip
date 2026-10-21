package com.sudox.perclip.notifications

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.widget.RemoteViews
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.sudox.perclip.PerClipActions
import com.sudox.perclip.R
import com.sudox.perclip.screen.CaptureTriggerReceiver

class QuickEntryNotificationHelper(context: Context) {
    private val appContext = context.applicationContext

    fun sync(enabled: Boolean): QuickEntryNotificationState {
        return if (enabled) show() else {
            cancel()
            QuickEntryNotificationState.Cancelled
        }
    }

    fun show(): QuickEntryNotificationState {
        if (!canPostNotifications()) return QuickEntryNotificationState.PermissionRequired
        ensureChannel()
        postNotification(buildNotification())
        return QuickEntryNotificationState.Visible
    }

    fun cancel() {
        NotificationManagerCompat.from(appContext).cancel(QUICK_ENTRY_NOTIFICATION_ID)
    }

    private fun buildNotification(): Notification {
        val contentPendingIntent = PendingIntent.getActivity(
            appContext,
            QUICK_ENTRY_CONTENT_REQUEST_CODE,
            openAppIntent(),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val actionPendingIntent = PendingIntent.getBroadcast(
            appContext,
            QUICK_ENTRY_ACTION_REQUEST_CODE,
            captureIntent(),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val quickEntryView = quickEntryRemoteViews(
            contentPendingIntent = contentPendingIntent,
            actionPendingIntent = actionPendingIntent,
        )

        return NotificationCompat.Builder(appContext, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(appContext, R.color.perclip_notification_accent))
            .setContentTitle("PerClip 闪记")
            .setContentIntent(contentPendingIntent)
            .setCustomContentView(quickEntryView)
            .setCustomBigContentView(quickEntryView)
            .setStyle(NotificationCompat.DecoratedCustomViewStyle())
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setShowWhen(false)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun quickEntryRemoteViews(
        contentPendingIntent: PendingIntent,
        actionPendingIntent: PendingIntent,
    ): RemoteViews {
        return RemoteViews(appContext.packageName, R.layout.notification_quick_entry).apply {
            setOnClickPendingIntent(R.id.notification_quick_entry_root, contentPendingIntent)
            setOnClickPendingIntent(R.id.notification_quick_entry_title, contentPendingIntent)
            setOnClickPendingIntent(R.id.notification_quick_entry_capture, actionPendingIntent)
        }
    }

    @SuppressLint("MissingPermission")
    private fun postNotification(notification: Notification) {
        if (!canPostNotifications()) return
        try {
            NotificationManagerCompat.from(appContext).notify(QUICK_ENTRY_NOTIFICATION_ID, notification)
        } catch (_: SecurityException) {
            // Notification permission may be revoked between the permission check and notify call.
        }
    }

    private fun canPostNotifications(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(
            appContext,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun captureIntent(): Intent {
        return Intent(appContext, CaptureTriggerReceiver::class.java)
            .setAction(PerClipActions.ACTION_CAPTURE_SCREEN)
    }

    private fun openAppIntent(): Intent {
        return Intent(appContext, com.sudox.perclip.MainActivity::class.java)
            .setAction(Intent.ACTION_MAIN)
            .addCategory(Intent.CATEGORY_LAUNCHER)
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = appContext.getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            "PerClip 快速入口",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "常驻的 PerClip 闪记按钮"
            setSound(null, null)
            enableVibration(false)
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
        manager.deleteNotificationChannel(OLD_V2_QUICK_ENTRY_CHANNEL_ID)
        manager.deleteNotificationChannel(OLD_QUICK_ENTRY_CHANNEL_ID)
        manager.deleteNotificationChannel(OBSOLETE_UPLOAD_CHANNEL_ID)
    }

    companion object {
        const val QUICK_ENTRY_NOTIFICATION_ID = 10_001
        const val CHANNEL_ID = "perclip_quick_entry_v3"
        private const val QUICK_ENTRY_CONTENT_REQUEST_CODE = 10_101
        private const val QUICK_ENTRY_ACTION_REQUEST_CODE = 10_102
        private const val OLD_V2_QUICK_ENTRY_CHANNEL_ID = "perclip_quick_entry_v2"
        private const val OLD_QUICK_ENTRY_CHANNEL_ID = "perclip_quick_entry"
        private const val OBSOLETE_UPLOAD_CHANNEL_ID = "perclip_uploads"
    }
}

enum class QuickEntryNotificationState {
    Visible,
    PermissionRequired,
    Cancelled,
}
