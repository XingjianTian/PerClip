package com.sudox.perclip.ui.design

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.unit.dp
import com.sudox.perclip.design.ColorTokens

object PerClipShape {
    val Card = RoundedCornerShape(18.dp)
    val Small = RoundedCornerShape(6.dp)
}

@Composable
fun PerClipCard(
    modifier: Modifier = Modifier,
    containerColor: Color = if (MaterialTheme.colorScheme.background.luminance() < .5f) {
        MaterialTheme.colorScheme.surface
    } else {
        Color.White
    },
    borderColor: Color = if (MaterialTheme.colorScheme.background.luminance() < .5f) {
        MaterialTheme.colorScheme.outline.copy(alpha = 0.72f)
    } else {
        ColorTokens.FlashBorder
    },
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = PerClipShape.Card,
        colors = CardDefaults.cardColors(containerColor = containerColor),
        border = BorderStroke(1.dp, borderColor),
    ) {
        Column(
            modifier = Modifier.padding(PerClipSpacing.CardPadding),
            content = content,
        )
    }
}
