package com.sudox.perclip.ui

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.material3.LocalContentColor
import com.sudox.perclip.design.perClipAccentColor

/** Approved D geometry from Navigation/MemoryPlanetTabIcon (142:4863), in a 24-unit view box. */
@Composable
internal fun MemoryPlanetTabIcon(
    selected: Boolean,
    modifier: Modifier = Modifier,
) {
    val navigationTint = LocalContentColor.current
    val tint = if (selected) perClipAccentColor() else navigationTint
    Canvas(modifier.clearAndSetSemantics { }) {
        val sx = size.width / 24f
        val sy = size.height / 24f
        val scale = minOf(sx, sy)
        val center = Offset(12f * sx, 12f * sy)

        rotate(degrees = -18f, pivot = center) {
            drawOval(
                color = tint,
                topLeft = Offset(3.2f * sx, 10.2f * sy),
                size = Size(17.6f * sx, 3.6f * sy),
                style = Stroke(width = 1.55f * scale),
            )
        }
        drawCircle(
            color = tint,
            radius = 6f * scale,
            center = center,
            style = Stroke(width = 1.9f * scale),
        )
    }
}
