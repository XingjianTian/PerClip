package com.sudox.perclip.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.sudox.perclip.design.ColorTokens

internal object BottomNavigationSpec {
    const val NAVIGATION_HEIGHT_DP = 80
    const val ICON_SLOT_DP = 30
    const val STANDARD_ICON_DP = 24
    const val FLASH_ICON_DP = 28
    const val MEMORY_PLANET_ICON_DP = 30
    const val SELECTED_UNDERLINE_WIDTH_DP = 30
    const val SELECTED_UNDERLINE_HEIGHT_DP = 3
    const val SELECTED_UNDERLINE_BOTTOM_INSET_DP = 4
}

internal fun Modifier.bottomNavigationSelection(
    selectedIndex: Int,
    selectionColor: Color = ColorTokens.FlashPurple,
    itemCount: Int = 4,
): Modifier =
    drawWithContent {
        drawContent()
        if (selectedIndex in 0 until itemCount) {
            val width = BottomNavigationSpec.SELECTED_UNDERLINE_WIDTH_DP.dp.toPx()
            val height = BottomNavigationSpec.SELECTED_UNDERLINE_HEIGHT_DP.dp.toPx()
            val bottomInset = BottomNavigationSpec.SELECTED_UNDERLINE_BOTTOM_INSET_DP.dp.toPx()
            val itemCenter = size.width * (selectedIndex + 0.5f) / itemCount
            drawRoundRect(
                color = selectionColor,
                topLeft = Offset(itemCenter - width / 2f, size.height - bottomInset - height),
                size = Size(width, height),
                cornerRadius = CornerRadius(height / 2f),
            )
        }
    }

@Composable
internal fun BottomNavigationIconSlot(content: @Composable () -> Unit) {
    Box(
        modifier = Modifier.size(BottomNavigationSpec.ICON_SLOT_DP.dp),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}
