package com.sudox.perclip.design

import androidx.compose.ui.graphics.Color
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.luminance

object ColorTokens {
    val PrimaryYellow = Color(0xFFFFD43B)
    val SunlitYellow = Color(0xFFFFE873)
    val InkBlack = Color(0xFF18181B)
    val WarmWhite = Color(0xFFFFFDF5)
    val NightInk = Color(0xFF111113)
    val NightSurface = Color(0xFF1D1D20)
    val NightLine = Color(0xFF34343A)
    val CloudGray = Color(0xFFF3F4F6)
    val LineGray = Color(0xFFE5E7EB)
    val ActionBlue = Color(0xFF2563EB)
    val FreshGreen = Color(0xFF22C55E)
    val CoralError = Color(0xFFF97316)

    // Flash Note round-one visual tokens.
    val FlashPurple = Color(0xFF7862F2)
    val FlashPurpleSoft = Color(0xFFEDE9FF)
    val FlashBackground = Color(0xFFFAF9FF)
    val FlashInk = Color(0xFF18172D)
    val FlashMuted = Color(0xFF747187)
    val FlashBorder = Color(0xFFE3DFEE)
    val FlashSuccess = Color(0xFF2FA66A)

    // Selected dark direction: C · Soft Plum.
    val DarkPlumBackground = Color(0xFF1A141E)
    val DarkPlumSurface = Color(0xFF281F2C)
    val DarkPlumRaised = Color(0xFF33283A)
    val DarkPlumInput = Color(0xFF231A28)
    val DarkPlumBorder = Color(0xFF4D3D56)
    val DarkPlumBorderSoft = Color(0xFF3D3046)
    val DarkPlumText = Color(0xFFF8F1FA)
    val DarkPlumSecondary = Color(0xFFC4B7CA)
    val DarkPlumMuted = Color(0xFF99899F)
    val DarkPlumAccent = Color(0xFF917AFF)
    val DarkPlumAccentSoft = Color(0xFF49345D)
    val DarkPlumPlanet = Color(0xFFD2C5FF)
    val DarkPlumSuccess = Color(0xFF67C7A0)
    val DarkPlumError = Color(0xFFE18193)
    val DarkPlumInfo = Color(0xFF6BBFF0)
    val DarkPlumGold = Color(0xFFF2BD64)
    val DarkPlumOrange = Color(0xFFF1A166)
}

@Composable
fun perClipIsDarkTheme(): Boolean = MaterialTheme.colorScheme.background.luminance() < .5f

@Composable
internal fun perClipAccentColor(): Color =
    if (perClipIsDarkTheme()) ColorTokens.DarkPlumAccent else ColorTokens.FlashPurple

@Composable
internal fun perClipAccentSoftColor(): Color =
    if (perClipIsDarkTheme()) ColorTokens.DarkPlumAccentSoft else ColorTokens.FlashPurpleSoft
