package com.sudox.perclip.shortcuts

import android.content.Context
import android.content.Intent
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import com.sudox.perclip.MainActivity
import com.sudox.perclip.PerClipActions
import com.sudox.perclip.R

object PinnedShortcutRequester {
    const val QUICK_NOTE_PINNED_ID = "pinned_quick_note"

    fun isSupported(context: Context): Boolean {
        return ShortcutManagerCompat.isRequestPinShortcutSupported(context)
    }

    fun requestQuickNote(context: Context): PinShortcutResult {
        if (!isSupported(context)) return PinShortcutResult.NotSupported

        val shortcut = ShortcutInfoCompat.Builder(context, QUICK_NOTE_PINNED_ID)
            .setShortLabel(context.getString(R.string.shortcut_quick_note_short))
            .setLongLabel(context.getString(R.string.shortcut_quick_note_long))
            .setIcon(IconCompat.createWithResource(context, R.drawable.ic_shortcut_flash))
            .setIntent(
                Intent(context, MainActivity::class.java)
                    .setAction(PerClipActions.ACTION_NEW_NOTE),
            )
            .build()

        return if (ShortcutManagerCompat.requestPinShortcut(context, shortcut, null)) {
            PinShortcutResult.Requested
        } else {
            PinShortcutResult.Failed
        }
    }
}

enum class PinShortcutResult {
    Requested,
    NotSupported,
    Failed,
}
