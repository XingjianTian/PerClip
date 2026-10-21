package com.sudox.perclip.design

import android.app.Activity
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

internal val PerClipLightScheme = lightColorScheme(
    primary = ColorTokens.FlashPurple,
    onPrimary = Color.White,
    primaryContainer = ColorTokens.FlashPurpleSoft,
    onPrimaryContainer = ColorTokens.FlashInk,
    secondary = ColorTokens.ActionBlue,
    onSecondary = Color.White,
    tertiary = ColorTokens.FreshGreen,
    background = ColorTokens.FlashBackground,
    onBackground = ColorTokens.InkBlack,
    surface = Color.White,
    onSurface = ColorTokens.InkBlack,
    surfaceVariant = Color(0xFFF3EFF8),
    onSurfaceVariant = ColorTokens.FlashMuted,
    outline = ColorTokens.FlashBorder,
    outlineVariant = Color(0xFFEEE8F3),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFFCFBFF),
    surfaceContainer = Color(0xFFF8F5FC),
    surfaceContainerHigh = Color(0xFFF3EFF8),
    surfaceContainerHighest = Color(0xFFEEE9F5),
    error = ColorTokens.CoralError,
)

internal val PerClipDarkScheme = darkColorScheme(
    primary = ColorTokens.DarkPlumAccent,
    onPrimary = ColorTokens.DarkPlumText,
    primaryContainer = ColorTokens.DarkPlumAccentSoft,
    onPrimaryContainer = ColorTokens.DarkPlumText,
    secondary = ColorTokens.DarkPlumPlanet,
    onSecondary = ColorTokens.DarkPlumBackground,
    tertiary = ColorTokens.DarkPlumSuccess,
    background = ColorTokens.DarkPlumBackground,
    onBackground = ColorTokens.DarkPlumText,
    surface = ColorTokens.DarkPlumSurface,
    onSurface = ColorTokens.DarkPlumText,
    surfaceVariant = ColorTokens.DarkPlumRaised,
    onSurfaceVariant = ColorTokens.DarkPlumSecondary,
    outline = ColorTokens.DarkPlumBorder,
    outlineVariant = ColorTokens.DarkPlumBorderSoft,
    surfaceContainerLowest = Color(0xFF201724),
    surfaceContainerLow = Color(0xFF251B2A),
    surfaceContainer = ColorTokens.DarkPlumSurface,
    surfaceContainerHigh = ColorTokens.DarkPlumRaised,
    surfaceContainerHighest = Color(0xFF3B2E43),
    error = ColorTokens.DarkPlumError,
)

@Composable
fun PerClipTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as? Activity)?.window ?: return@SideEffect
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !darkTheme
                isAppearanceLightNavigationBars = !darkTheme
            }
        }
    }
    MaterialTheme(
        colorScheme = if (darkTheme) PerClipDarkScheme else PerClipLightScheme,
        typography = MaterialTheme.typography,
        content = content,
    )
}
