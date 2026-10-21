package com.sudox.perclip.quicksettings

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import com.sudox.perclip.PerClipActions
import com.sudox.perclip.screen.CaptureTriggerReceiver

class QuickCaptureTileService : TileService() {
    override fun onStartListening() {
        super.onStartListening()
        qsTile?.apply {
            state = Tile.STATE_ACTIVE
            label = "PerClip"
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                subtitle = "当前屏幕"
            }
            updateTile()
        }
    }

    override fun onClick() {
        super.onClick()
        val intent = Intent(this, CaptureTriggerReceiver::class.java)
            .setAction(PerClipActions.ACTION_CAPTURE_SCREEN)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            val pendingIntent = PendingIntent.getBroadcast(
                this,
                REQUEST_QUICK_NOTE,
                intent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            startActivityAndCollapse(pendingIntent)
        } else {
            sendBroadcast(intent)
        }
    }

    companion object {
        private const val REQUEST_QUICK_NOTE = 2001
    }
}
