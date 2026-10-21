package com.sudox.perclip.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@Composable
internal fun SettingsPageScaffold(
    contentPadding: PaddingValues,
    title: String,
    subtitle: String = "",
    onBack: () -> Unit,
    content: @Composable () -> Unit,
) {
    Column(
        Modifier.fillMaxSize().background(settingsPageBackgroundColor()).padding(contentPadding).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        androidx.compose.foundation.layout.Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "返回")
            }
            androidx.compose.foundation.layout.Column {
                Text(title, style = PerClipSettingsTypography.PageTitle, color = settingsPrimaryTextColor())
                if (subtitle.isNotBlank()) Text(subtitle, style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor())
            }
        }
        content()
    }
}
