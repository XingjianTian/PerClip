package com.sudox.perclip.screen

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import com.sudox.perclip.MainActivity
import com.sudox.perclip.PerClipActions

class CaptureTriggerReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != PerClipActions.ACTION_CAPTURE_SCREEN) return
        val handled = PerClipAccessibilityService.requestTriggeredCapture()
        Log.d(TAG, "capture trigger received handledByAccessibility=$handled")
        if (!handled) {
            Toast.makeText(context, "请先开启 PerClip 当前屏幕闪记服务。", Toast.LENGTH_LONG).show()
            context.startActivity(
                Intent(context, MainActivity::class.java)
                    .setAction(PerClipActions.ACTION_SETTINGS)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            )
        }
    }

    companion object {
        private const val TAG = "PerClipCapture"
    }
}
