package com.sudox.perclip.ui.design

import androidx.compose.foundation.Image
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.res.painterResource
import com.sudox.perclip.R
import com.sudox.perclip.design.perClipAccentColor

/** Theme-aware transparent brand symbol; launcher container chrome is intentionally excluded. */
@Composable
fun PerClipBrandMark(
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
) {
    Image(
        painter = painterResource(R.drawable.ic_launcher_monochrome),
        contentDescription = contentDescription,
        modifier = modifier,
        colorFilter = ColorFilter.tint(perClipAccentColor()),
    )
}
