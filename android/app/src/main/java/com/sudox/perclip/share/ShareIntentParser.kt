package com.sudox.perclip.share

import android.content.Context
import android.content.Intent
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import androidx.core.net.toUri
import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.SharedClipItem
import java.util.UUID

object ShareIntentParser {
    fun parse(context: Context, intent: Intent?, clipId: String = UUID.randomUUID().toString()): SharedClip? {
        if (intent == null) return null
        return when (intent.action) {
            Intent.ACTION_SEND -> parseSingle(context, intent, clipId)
            Intent.ACTION_SEND_MULTIPLE -> parseMultiple(context, intent, clipId)
            else -> null
        }
    }

    private fun parseSingle(context: Context, intent: Intent, clipId: String): SharedClip? {
        val text = intent.getStringExtra(Intent.EXTRA_TEXT).orEmpty().trim()
        val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT).orEmpty().trim()
        val stream = intent.streamExtra()
        val mimeType = intent.type.orEmpty()
        val sourceApp = intent.sourceApp(context)

        if (stream != null) {
            val item = context.describeUri(stream, mimeType)
            val kind = when {
                item.mimeType.startsWith("image/") -> ClipKind.Image
                else -> ClipKind.File
            }
            return SharedClip(
                id = clipId,
                kind = kind,
                titleHint = subject.ifBlank { item.displayName },
                items = listOf(item),
                mimeType = item.mimeType,
                sourceApp = sourceApp,
            )
        }

        if (text.isNotBlank()) {
            val metadata = SharedTextParser.parse(text = text, subject = subject, sourceApp = sourceApp)
            return SharedClip(
                id = clipId,
                kind = if (metadata.url.isNotBlank()) ClipKind.Url else ClipKind.Text,
                titleHint = metadata.titleHint,
                text = metadata.text,
                url = metadata.url,
                mimeType = mimeType.ifBlank { "text/plain" },
                sourceApp = sourceApp,
            )
        }

        return null
    }

    private fun parseMultiple(context: Context, intent: Intent, clipId: String): SharedClip? {
        val mimeType = intent.type.orEmpty()
        val uris = intent.streamListExtra()
        if (uris.isEmpty()) return null

        val items = uris.map { context.describeUri(it, mimeType) }
        val allImages = items.all { it.mimeType.startsWith("image/") }
        return SharedClip(
            id = clipId,
            kind = if (allImages) ClipKind.Image else ClipKind.Multiple,
            titleHint = if (allImages) "图片归档" else "批量归档",
            items = items,
            mimeType = mimeType.ifBlank { "*/*" },
            sourceApp = intent.sourceApp(context),
        )
    }

    private fun Intent.sourceApp(context: Context): String {
        val referrerName = getStringExtra(Intent.EXTRA_REFERRER_NAME).orEmpty()
        if (referrerName.isNotBlank()) {
            return referrerName.removePrefix("android-app://").trim()
        }

        val referrer = referrerUri()
        val packageName = when {
            referrer?.scheme == "android-app" -> referrer.host.orEmpty()
            else -> ""
        }
        if (packageName.isBlank()) return ""

        return runCatching {
            val appInfo = context.packageManager.getApplicationInfo(packageName, 0)
            context.packageManager.getApplicationLabel(appInfo).toString()
        }.getOrDefault(packageName)
    }

    private fun Intent.referrerUri(): Uri? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(Intent.EXTRA_REFERRER, Uri::class.java)
        } else {
            @Suppress("DEPRECATION")
            getParcelableExtra(Intent.EXTRA_REFERRER)
        } ?: getStringExtra(Intent.EXTRA_REFERRER_NAME)?.toUri()
    }

    private fun Intent.streamExtra(): Uri? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
            @Suppress("DEPRECATION")
            getParcelableExtra(Intent.EXTRA_STREAM)
        }
    }

    private fun Intent.streamListExtra(): List<Uri> {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
        } else {
            @Suppress("DEPRECATION")
            getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()
        }
    }

    private fun Context.describeUri(uri: Uri, fallbackMimeType: String): SharedClipItem {
        val resolver = contentResolver
        val mimeType = resolver.getType(uri) ?: fallbackMimeType.ifBlank { "application/octet-stream" }
        var displayName = uri.lastPathSegment ?: "未命名文件"
        var sizeBytes: Long? = null

        resolver.query(uri, null, null, null, null)?.use { cursor: Cursor ->
            val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
            if (cursor.moveToFirst()) {
                if (nameIndex >= 0) {
                    displayName = cursor.getString(nameIndex).orEmpty().ifBlank { displayName }
                }
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) {
                    sizeBytes = cursor.getLong(sizeIndex)
                }
            }
        }

        return SharedClipItem(
            uri = uri,
            displayName = displayName,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
        )
    }
}
