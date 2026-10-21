package com.sudox.perclip.ui.screens

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import com.sudox.perclip.design.ColorTokens

@Composable
internal fun isKnowledgeDarkTheme() = MaterialTheme.colorScheme.background.luminance() < 0.5f

@Composable
internal fun knowledgeBackgroundColor() =
    if (isKnowledgeDarkTheme()) MaterialTheme.colorScheme.background else ColorTokens.FlashBackground

@Composable
internal fun knowledgeSurfaceColor() =
    if (isKnowledgeDarkTheme()) MaterialTheme.colorScheme.surface else Color.White

@Composable
internal fun knowledgeBorderColor() =
    if (isKnowledgeDarkTheme()) MaterialTheme.colorScheme.outline else ColorTokens.FlashBorder
