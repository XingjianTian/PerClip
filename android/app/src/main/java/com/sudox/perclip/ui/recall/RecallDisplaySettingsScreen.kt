package com.sudox.perclip.ui.recall

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Lightbulb
import androidx.compose.material.icons.rounded.School
import androidx.compose.material.icons.rounded.Workspaces
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sudox.perclip.recall.repository.RecallDomainTopic
import com.sudox.perclip.capabilities.AppFeatureAvailability
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.ui.screens.PerClipSettingsTypography

private val DisplayPurple = Color(0xFF765BFF)
private val DisplayGreen = Color(0xFF45BD8B)
private val DisplayOrange = Color(0xFFFF942F)
private val DisplayBlue = Color(0xFF58AEF4)

private data class DisplayPalette(
    val page: Color,
    val surface: Color,
    val ink: Color,
    val muted: Color,
    val line: Color,
    val soft: Color,
)

@Composable
private fun displayPalette(): DisplayPalette = if (MaterialTheme.colorScheme.background.luminance() < .5f) {
    DisplayPalette(
        ColorTokens.DarkPlumBackground,
        ColorTokens.DarkPlumSurface,
        ColorTokens.DarkPlumText,
        ColorTokens.DarkPlumSecondary,
        ColorTokens.DarkPlumBorder,
        ColorTokens.DarkPlumAccentSoft,
    )
} else {
    DisplayPalette(Color(0xFFFAF9FE), Color.White, Color(0xFF17152F), Color(0xFF69647D), Color(0xFFCFC5E6), Color(0xFFF0EBFF))
}

@Composable
internal fun RecallDisplaySettingsContent(
    state: RecallUiState,
    padding: PaddingValues,
    onBack: () -> Unit,
    onVisibleTopicCount: (Int) -> Unit,
    onVisibleMemoryLabels: (Int) -> Unit,
    onTopicVisible: (String, Boolean) -> Unit,
    onRestoreDefaults: () -> Unit,
    featureAvailability: AppFeatureAvailability = AppFeatureAvailability.AVAILABLE,
    unavailableMessage: String = "",
    onRetry: () -> Unit = {},
) {
    val palette = displayPalette()
    val topics = state.domain.value?.topics.orEmpty()
    val visibleIds = topics.map { it.id }.toSet() - state.presentation.hiddenTopicIds
    LazyColumn(
        modifier = Modifier.fillMaxSize().background(palette.page).padding(padding),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item("header") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.AutoMirrored.Rounded.ArrowBack, "返回", tint = DisplayPurple)
                }
                Spacer(Modifier.width(6.dp))
                Column {
                    Text("星球显示", color = palette.ink, style = PerClipSettingsTypography.PageTitle)
                    Text("控制记忆星球的密度与主题", color = palette.muted, style = PerClipSettingsTypography.Supporting)
                }
            }
        }
        item("summary") {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                color = Color.Transparent,
                border = BorderStroke(1.dp, palette.line),
            ) {
                Row(
                    Modifier.background(Brush.horizontalGradient(listOf(palette.soft, DisplayPurple.copy(alpha = .10f)))).padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("✦", color = DisplayPurple, fontSize = 20.sp, fontWeight = FontWeight.Black)
                    Spacer(Modifier.width(12.dp))
                    Column {
                        Text("默认清晰密度", color = palette.ink, style = PerClipSettingsTypography.RowTitle)
                        Text("最多 ${state.presentation.visibleTopicCount} 个主题 · 每主题 ${state.presentation.visibleMemoryLabels} 条记忆", color = palette.muted, style = PerClipSettingsTypography.Supporting)
                    }
                }
            }
        }
        item("counts") {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = palette.surface,
                border = BorderStroke(1.dp, palette.line),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text("显示数量", color = palette.ink, style = PerClipSettingsTypography.RowTitle)
                    Text("超出上限的内容仍保留，只是不在星球中显示", color = palette.muted, style = PerClipSettingsTypography.Supporting)
                    DisplayCountRow("主题节点", "最多 5 个", state.presentation.visibleTopicCount, listOf(3, 4, 5), palette, onVisibleTopicCount)
                    DisplayCountRow("记忆圈标签", "每个主题最多 5 条", state.presentation.visibleMemoryLabels, listOf(1, 3, 5), palette, onVisibleMemoryLabels)
                    Text("硬上限均为 5，避免节点与标签互相遮挡", Modifier.padding(top = 8.dp), color = if (MaterialTheme.colorScheme.background.luminance() < .5f) ColorTokens.DarkPlumPlanet else DisplayPurple, style = PerClipSettingsTypography.Supporting)
                }
            }
        }
        item("topic-heading") {
            Column {
                Text("显示主题", color = palette.ink, style = PerClipSettingsTypography.RowTitle)
                Text("开启的主题按最近活跃度排序，最多显示 ${state.presentation.visibleTopicCount} 个", color = palette.muted, style = PerClipSettingsTypography.Supporting)
            }
        }
        if (state.domain.value == null) {
            item("domain-state") {
                RecallDisplayDomainState(
                    loading = state.domain.loading || featureAvailability == AppFeatureAvailability.CHECKING,
                    unavailable = featureAvailability == AppFeatureAvailability.UNAVAILABLE,
                    message = when {
                        featureAvailability == AppFeatureAvailability.UNAVAILABLE -> unavailableMessage.ifBlank { "当前服务未提供记忆星球数据。" }
                        state.domain.error.isNotBlank() -> state.domain.error
                        else -> "正在加载主题数据…"
                    },
                    palette = palette,
                    onRetry = onRetry,
                )
            }
        } else if (topics.isEmpty()) {
            item("domain-empty") {
                RecallDisplayDomainState(
                    loading = false,
                    unavailable = false,
                    message = "当前还没有可管理的主题。",
                    palette = palette,
                    onRetry = onRetry,
                )
            }
        }
        items(topics, key = { it.id }) { topic ->
            val checked = topic.id in visibleIds
            val enabled = !checked || visibleIds.size > 1
            DisplayTopicRow(topic, checked, enabled, palette) { onTopicVisible(topic.id, it) }
        }
        item("local-note") {
            Text(
                "仅影响本机显示，不会删除主题、记忆或修改知识库",
                Modifier.fillMaxWidth(),
                color = palette.muted,
                style = PerClipSettingsTypography.Supporting,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
        item("restore") {
            Surface(
                modifier = Modifier.fillMaxWidth().height(48.dp).clickable(onClick = onRestoreDefaults),
                shape = RoundedCornerShape(13.dp),
                color = palette.surface,
                border = BorderStroke(1.dp, palette.line),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("恢复默认显示", color = DisplayPurple, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@Composable
private fun RecallDisplayDomainState(
    loading: Boolean,
    unavailable: Boolean,
    message: String,
    palette: DisplayPalette,
    onRetry: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = palette.surface,
        border = BorderStroke(1.dp, palette.line),
    ) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (loading) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = DisplayPurple)
            Column(Modifier.weight(1f)) {
                Text(
                    when {
                        loading -> "正在加载主题"
                        unavailable -> "功能暂不可用"
                        else -> "主题数据未就绪"
                    },
                    color = palette.ink,
                    style = PerClipSettingsTypography.RowTitle,
                )
                Text(message, color = palette.muted, style = PerClipSettingsTypography.Supporting)
            }
            if (!loading) {
                Surface(
                    modifier = Modifier.height(48.dp).clickable(onClick = onRetry),
                    shape = RoundedCornerShape(12.dp),
                    color = palette.soft,
                ) {
                    Box(Modifier.padding(horizontal = 14.dp), contentAlignment = Alignment.Center) {
                        Text("重试", color = DisplayPurple, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Composable
private fun DisplayCountRow(
    title: String,
    subtitle: String,
    selected: Int,
    options: List<Int>,
    palette: DisplayPalette,
    onSelected: (Int) -> Unit,
) {
    Row(Modifier.fillMaxWidth().padding(top = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, color = palette.ink, style = PerClipSettingsTypography.RowTitle)
            Text(subtitle, color = palette.muted, style = PerClipSettingsTypography.Supporting)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            options.forEach { value ->
                val active = value == selected
                Box(
                    modifier = Modifier.size(48.dp).clickable { onSelected(value) },
                    contentAlignment = Alignment.Center,
                ) {
                    Surface(
                        modifier = Modifier.size(width = 42.dp, height = 32.dp),
                        shape = RoundedCornerShape(9.dp),
                        color = if (active) DisplayPurple else palette.soft,
                        border = BorderStroke(1.dp, if (active) DisplayPurple else palette.line),
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            Text(value.toString(), color = if (active) Color.White else palette.muted, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DisplayTopicRow(
    topic: RecallDomainTopic,
    checked: Boolean,
    enabled: Boolean,
    palette: DisplayPalette,
    onChecked: (Boolean) -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = palette.surface,
        border = BorderStroke(1.dp, palette.line.copy(alpha = .72f)),
    ) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            val slot = topic.colorSlot.mod(5)
            Surface(Modifier.size(32.dp), CircleShape, color = topicDisplayColor(slot).copy(alpha = .14f)) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(topicDisplayIcon(slot), null, Modifier.size(17.dp), tint = topicDisplayColor(slot))
                }
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(topic.label.ifBlank { topic.shortLabel.ifBlank { "未命名主题" } }, color = palette.ink, style = PerClipSettingsTypography.RowTitle)
                Text("${topic.clipCount} 条记忆", color = palette.muted, style = PerClipSettingsTypography.Supporting)
            }
            Switch(
                checked = checked,
                onCheckedChange = onChecked,
                enabled = enabled,
                colors = SwitchDefaults.colors(
                    checkedThumbColor = Color.White,
                    checkedTrackColor = DisplayPurple,
                    uncheckedThumbColor = palette.surface,
                    uncheckedTrackColor = palette.line,
                ),
            )
        }
    }
}

private fun topicDisplayIcon(slot: Int) = when (slot) {
    0 -> Icons.Rounded.School
    1, 2 -> Icons.Rounded.Description
    3 -> Icons.Rounded.Lightbulb
    else -> Icons.Rounded.Workspaces
}

private fun topicDisplayColor(slot: Int) = when (slot) {
    0 -> DisplayGreen
    1 -> DisplayBlue
    2 -> Color(0xFFF4B000)
    3 -> DisplayOrange
    else -> DisplayPurple
}
