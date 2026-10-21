package com.sudox.perclip.ui.design

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.sudox.perclip.design.ColorTokens

enum class PerClipStatusTone {
    Pending,
    Success,
    Danger,
    Planned,
    Neutral,
}

object PerClipStatusColors {
    fun colorFor(tone: PerClipStatusTone): Color = when (tone) {
        PerClipStatusTone.Pending -> ColorTokens.PrimaryYellow
        PerClipStatusTone.Success -> ColorTokens.FreshGreen.copy(alpha = 0.18f)
        PerClipStatusTone.Danger -> ColorTokens.CoralError.copy(alpha = 0.16f)
        PerClipStatusTone.Planned -> ColorTokens.ActionBlue.copy(alpha = 0.14f)
        PerClipStatusTone.Neutral -> MaterialGray
    }

    fun contentFor(tone: PerClipStatusTone): Color = when (tone) {
        PerClipStatusTone.Pending -> ColorTokens.InkBlack
        PerClipStatusTone.Success -> ColorTokens.FreshGreen
        PerClipStatusTone.Danger -> ColorTokens.CoralError
        PerClipStatusTone.Planned -> ColorTokens.ActionBlue
        PerClipStatusTone.Neutral -> Color(0xFF6B7280)
    }

    private val MaterialGray = ColorTokens.LineGray.copy(alpha = 0.72f)
}

@Composable
fun PerClipBadge(
    label: String,
    tone: PerClipStatusTone,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = PerClipStatusColors.colorFor(tone),
        shape = PerClipShape.Small,
    ) {
        Text(
            text = label,
            modifier = Modifier.padding(
                horizontal = PerClipSpacing.PillHorizontal,
                vertical = PerClipSpacing.PillVertical,
            ),
            style = MaterialTheme.typography.labelMedium,
            color = PerClipStatusColors.contentFor(tone),
        )
    }
}
