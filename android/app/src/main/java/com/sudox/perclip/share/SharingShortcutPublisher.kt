package com.sudox.perclip.share

import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import com.sudox.perclip.MainActivity
import com.sudox.perclip.PerClipActions
import com.sudox.perclip.R

object SharingShortcutPublisher {
    const val SAVE_TO_PERSONALCLIPS_ID = "save_to_personalclips"
    const val SAVE_TO_PERSONALCLIPS_CATEGORY = "com.sudox.perclip.category.SAVE_TO_PERSONALCLIPS"

    fun publish(context: Context) {
        val shortcut = ShortcutInfoCompat.Builder(context, SAVE_TO_PERSONALCLIPS_ID)
            .setShortLabel(context.getString(R.string.share_shortcut_short))
            .setLongLabel(context.getString(R.string.share_shortcut_long))
            .setIcon(IconCompat.createWithResource(context, R.drawable.ic_shortcut_flash))
            .setIntent(
                Intent(context, MainActivity::class.java)
                    .setAction(PerClipActions.ACTION_NEW_NOTE),
            )
            .setLongLived(true)
            .setCategories(setOf(SAVE_TO_PERSONALCLIPS_CATEGORY))
            .build()

        runCatching {
            ShortcutManagerCompat.addDynamicShortcuts(context, listOf(shortcut))
        }.onFailure { error ->
            Log.w("PerClipShortcuts", "Unable to publish sharing shortcut", error)
        }
    }
}
