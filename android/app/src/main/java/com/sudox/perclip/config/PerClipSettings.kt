package com.sudox.perclip.config

import android.content.Context

private val RECALL_DATE_PATTERN = Regex("""\d{4}-\d{2}-\d{2}""")

enum class AppThemeMode(val storageValue: String) {
    FOLLOW_SYSTEM("system"),
    LIGHT("light"),
    DARK("dark");

    fun resolve(systemInDarkTheme: Boolean): Boolean = when (this) {
        FOLLOW_SYSTEM -> systemInDarkTheme
        LIGHT -> false
        DARK -> true
    }

    companion object {
        fun fromStorage(value: String?): AppThemeMode =
            entries.firstOrNull { it.storageValue == value } ?: FOLLOW_SYSTEM
    }
}

data class PerClipSettings(
    val apiUrl: String,
    val ingestToken: String,
    val deviceName: String,
    val wifiOnlyLargeFiles: Boolean,
    val persistentQuickEntry: Boolean,
    val recallPeriodDays: Int = 7,
    val recallAutoSurface: Boolean = true,
    val recallGraphExpanded: Boolean = true,
    val reduceMotion: Boolean = false,
    val recallPeriodKind: String = if (recallPeriodDays == 30) "month" else "week",
    val recallCustomStartDate: String = "",
    val recallCustomEndDate: String = "",
    val recallCustomTimezone: String = "",
    val themeMode: AppThemeMode = AppThemeMode.FOLLOW_SYSTEM,
) {
    val hasUploadConfig: Boolean
        get() = apiUrl.trim().isNotBlank() && ingestToken.trim().isNotBlank()

    fun normalized(): PerClipSettings {
        return copy(
            apiUrl = apiUrl.trim().trimEnd('/'),
            ingestToken = ingestToken.trim(),
            deviceName = deviceName.trim().ifBlank { DEFAULT_DEVICE_NAME },
            recallAutoSurface = true,
            recallPeriodKind = recallPeriodKind.takeIf { it in setOf("week", "month", "custom") }
                ?: if (recallPeriodDays == 30) "month" else "week",
            recallCustomStartDate = recallCustomStartDate.takeIf(RECALL_DATE_PATTERN::matches).orEmpty(),
            recallCustomEndDate = recallCustomEndDate.takeIf(RECALL_DATE_PATTERN::matches).orEmpty(),
            recallCustomTimezone = recallCustomTimezone.trim(),
        )
    }

    companion object {
        const val DEFAULT_API_URL = ""
        const val DEFAULT_DEVICE_NAME = "Android PerClip"
    }
}

class PerClipSettingsStore(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("perclip_settings", Context.MODE_PRIVATE)

    fun load(): PerClipSettings {
        return PerClipSettings(
            apiUrl = prefs.getString(KEY_API_URL, PerClipSettings.DEFAULT_API_URL).orEmpty(),
            ingestToken = prefs.getString(KEY_TOKEN, "").orEmpty(),
            deviceName = prefs.getString(KEY_DEVICE_NAME, PerClipSettings.DEFAULT_DEVICE_NAME).orEmpty(),
            wifiOnlyLargeFiles = prefs.getBoolean(KEY_WIFI_ONLY, true),
            persistentQuickEntry = prefs.getBoolean(KEY_PERSISTENT_QUICK_ENTRY, false),
            recallPeriodDays = prefs.getInt(KEY_RECALL_PERIOD_DAYS, 7).let { if (it == 30) 30 else 7 },
            recallAutoSurface = true,
            recallGraphExpanded = prefs.getBoolean(KEY_RECALL_GRAPH_EXPANDED, true),
            reduceMotion = prefs.getBoolean(KEY_REDUCE_MOTION, false),
            recallPeriodKind = prefs.getString(KEY_RECALL_PERIOD_KIND, "").orEmpty()
                .takeIf { it in setOf("week", "month", "custom") }
                ?: if (prefs.getInt(KEY_RECALL_PERIOD_DAYS, 7) == 30) "month" else "week",
            recallCustomStartDate = prefs.getString(KEY_RECALL_CUSTOM_START_DATE, "").orEmpty(),
            recallCustomEndDate = prefs.getString(KEY_RECALL_CUSTOM_END_DATE, "").orEmpty(),
            recallCustomTimezone = prefs.getString(KEY_RECALL_CUSTOM_TIMEZONE, "").orEmpty(),
            themeMode = AppThemeMode.fromStorage(prefs.getString(KEY_THEME_MODE, null)),
        )
    }

    fun save(settings: PerClipSettings) {
        val normalized = settings.normalized()
        prefs.edit()
            .putString(KEY_API_URL, normalized.apiUrl)
            .putString(KEY_TOKEN, normalized.ingestToken)
            .putString(KEY_DEVICE_NAME, normalized.deviceName)
            .putBoolean(KEY_WIFI_ONLY, normalized.wifiOnlyLargeFiles)
            .putBoolean(KEY_PERSISTENT_QUICK_ENTRY, normalized.persistentQuickEntry)
            .putInt(KEY_RECALL_PERIOD_DAYS, normalized.recallPeriodDays.let { if (it == 30) 30 else 7 })
            .putBoolean(KEY_RECALL_AUTO_SURFACE, true)
            .putBoolean(KEY_RECALL_GRAPH_EXPANDED, normalized.recallGraphExpanded)
            .putBoolean(KEY_REDUCE_MOTION, normalized.reduceMotion)
            .putString(KEY_RECALL_PERIOD_KIND, normalized.recallPeriodKind)
            .putString(KEY_RECALL_CUSTOM_START_DATE, normalized.recallCustomStartDate)
            .putString(KEY_RECALL_CUSTOM_END_DATE, normalized.recallCustomEndDate)
            .putString(KEY_RECALL_CUSTOM_TIMEZONE, normalized.recallCustomTimezone)
            .putString(KEY_THEME_MODE, normalized.themeMode.storageValue)
            .apply()
    }

    companion object {
        private const val KEY_API_URL = "api_url"
        private const val KEY_TOKEN = "ingest_token"
        private const val KEY_DEVICE_NAME = "device_name"
        private const val KEY_WIFI_ONLY = "wifi_only_large_files"
        private const val KEY_PERSISTENT_QUICK_ENTRY = "persistent_quick_entry"
        private const val KEY_RECALL_PERIOD_DAYS = "recall_period_days"
        private const val KEY_RECALL_AUTO_SURFACE = "recall_auto_surface"
        private const val KEY_RECALL_GRAPH_EXPANDED = "recall_graph_expanded"
        private const val KEY_REDUCE_MOTION = "reduce_motion"
        private const val KEY_RECALL_PERIOD_KIND = "recall_period_kind"
        private const val KEY_RECALL_CUSTOM_START_DATE = "recall_custom_start_date"
        private const val KEY_RECALL_CUSTOM_END_DATE = "recall_custom_end_date"
        private const val KEY_RECALL_CUSTOM_TIMEZONE = "recall_custom_timezone"
        private const val KEY_THEME_MODE = "theme_mode"
    }
}
