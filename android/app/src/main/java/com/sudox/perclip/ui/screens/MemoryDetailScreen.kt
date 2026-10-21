package com.sudox.perclip.ui.screens

import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Sell
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sudox.perclip.design.ColorTokens
import kotlinx.coroutines.launch

internal object MemoryDetailTransitionPolicy {
    const val STANDARD_DURATION_MILLIS = 200
    fun durationMillis(
        appReducedMotion: Boolean,
        systemAnimationsDisabled: Boolean,
    ): Int = if (appReducedMotion || systemAnimationsDisabled) 0 else STANDARD_DURATION_MILLIS
}

@Composable
internal fun MemoryDetailScreen(
    contentPadding: PaddingValues,
    model: MemoryDetailUiModel?,
    loading: Boolean = false,
    errorMessage: String = "",
    onBack: () -> Unit,
    onRetry: () -> Unit = {},
    actions: @Composable (() -> Unit)? = null,
    reducedMotionOverride: Boolean = false,
) {
    val context = LocalContext.current
    val systemAnimationsDisabled = remember(context) {
        runCatching {
            Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE) == 0f
        }.getOrDefault(false)
    }
    val duration = MemoryDetailTransitionPolicy.durationMillis(
        appReducedMotion = reducedMotionOverride,
        systemAnimationsDisabled = systemAnimationsDisabled,
    )
    val alpha = remember { Animatable(if (duration == 0) 1f else 0f) }
    val scope = rememberCoroutineScope()
    var closing by remember { mutableStateOf(false) }

    fun requestBack() {
        if (closing) return
        closing = true
        if (duration == 0) onBack() else scope.launch {
            alpha.animateTo(0f, tween(duration))
            onBack()
        }
    }

    LaunchedEffect(duration) { alpha.animateTo(1f, tween(duration)) }
    BackHandler { requestBack() }

    Column(
        Modifier
            .fillMaxSize()
            .background(knowledgeBackgroundColor())
            .padding(top = contentPadding.calculateTopPadding()),
    ) {
        Column(Modifier.fillMaxSize().graphicsLayer { this.alpha = alpha.value }) {
            MemoryDetailTopBar(onBack = ::requestBack)
            when {
                model == null && loading -> MemoryDetailLoading()
                model == null -> MemoryDetailError(errorMessage, onRetry)
                else -> MemoryDetailContent(
                    model = model,
                    message = errorMessage,
                    actions = actions,
                    bottomPadding = contentPadding.calculateBottomPadding(),
                )
            }
        }
    }
}

@Composable
private fun MemoryDetailTopBar(onBack: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().height(64.dp).padding(horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
            Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "返回记忆列表")
        }
        Text("记忆详情", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun MemoryDetailLoading() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
            Text("正在读取记忆…", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun MemoryDetailError(errorMessage: String, onRetry: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                errorMessage.ifBlank { "这条记忆暂时无法打开" },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            TextButton(onClick = onRetry) { Text("重试") }
        }
    }
}

@Composable
private fun MemoryDetailContent(
    model: MemoryDetailUiModel,
    message: String,
    actions: @Composable (() -> Unit)?,
    bottomPadding: androidx.compose.ui.unit.Dp,
) {
    val metadataLayout = MemoryDetailMetadataPolicy.resolve(model.capturedAt, model.sourceLabel)
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            start = 20.dp,
            end = 20.dp,
            top = 24.dp,
            bottom = bottomPadding + 32.dp,
        ),
    ) {
        item("title-and-metadata") {
            Text(
                text = model.title,
                color = MaterialTheme.colorScheme.onSurface,
                fontSize = 32.sp,
                lineHeight = 42.sp,
                fontWeight = FontWeight.Black,
            )
            if (metadataLayout != MemoryDetailMetadataLayout.NONE) {
                Spacer(Modifier.height(18.dp))
                MemoryDetailMetadata(model.capturedAt, model.sourceLabel, metadataLayout)
            }
        }
        if (model.topics.labels.isNotEmpty()) {
            item("formal-topics") {
                Spacer(Modifier.height(20.dp))
                Text("主题", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(10.dp))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    model.topics.labels.forEach { label ->
                        MemoryDetailTopicChip(label, model.topics.style)
                    }
                }
                if (model.topics.statusLabel.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        model.topics.statusLabel,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        item("original-content") {
            Spacer(Modifier.height(if (model.topics.labels.isEmpty()) 26.dp else 24.dp))
            MemoryDetailOriginalContent(model.body.value)
        }
        if (actions != null && MemoryDetailActionsPolicy.shouldShow(model.source, actionsAvailable = true)) {
            item("actions") {
                Spacer(Modifier.height(22.dp))
                actions()
            }
        }
        if (message.isNotBlank()) {
            item("message") {
                Spacer(Modifier.height(14.dp))
                Text(
                    message,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun MemoryDetailMetadata(
    capturedAt: String,
    sourceLabel: String,
    layout: MemoryDetailMetadataLayout,
) {
    Column {
        FlowRow(
            Modifier.fillMaxWidth().heightIn(min = 25.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (layout == MemoryDetailMetadataLayout.DATE_ONLY || layout == MemoryDetailMetadataLayout.BOTH) {
                MemoryDetailMetadataItem(Icons.Rounded.CalendarMonth, capturedAt, "记忆日期")
            }
            if (layout == MemoryDetailMetadataLayout.SOURCE_ONLY || layout == MemoryDetailMetadataLayout.BOTH) {
                MemoryDetailMetadataItem(Icons.Rounded.Sell, sourceLabel, "记忆来源")
            }
        }
        Spacer(Modifier.height(11.dp))
        Box(Modifier.fillMaxWidth().height(1.dp).background(MaterialTheme.colorScheme.outline))
    }
}

@Composable
private fun MemoryDetailMetadataItem(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    value: String,
    description: String,
) {
    Row(
        modifier = Modifier.widthIn(max = 350.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            icon,
            contentDescription = description,
            modifier = Modifier.size(20.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            value,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun MemoryDetailTopicChip(label: String, style: MemoryDetailTopicStyle) {
    val disabled = style == MemoryDetailTopicStyle.DISABLED
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = when {
            disabled && isKnowledgeDarkTheme() -> MaterialTheme.colorScheme.surfaceVariant
            disabled -> Color(0xFFF2F0F5)
            isKnowledgeDarkTheme() -> MaterialTheme.colorScheme.surface
            else -> MaterialTheme.colorScheme.primaryContainer.copy(alpha = .55f)
        },
        border = BorderStroke(
            1.dp,
            when {
                disabled && isKnowledgeDarkTheme() -> MaterialTheme.colorScheme.outline
                disabled -> Color(0xFFCFCAD8)
                else -> memoryDetailBorderColor()
            },
        ),
    ) {
        Text(
            label,
            Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
            color = when {
                disabled && isKnowledgeDarkTheme() -> MaterialTheme.colorScheme.onSurfaceVariant
                disabled -> Color(0xFF747187)
                else -> MaterialTheme.colorScheme.primary
            },
            style = MaterialTheme.typography.labelMedium,
            maxLines = 1,
        )
    }
}

@Composable
private fun MemoryDetailOriginalContent(content: String) {
    Surface(
        modifier = Modifier.fillMaxWidth().heightIn(min = 196.dp),
        shape = RoundedCornerShape(20.dp),
        color = knowledgeSurfaceColor(),
        border = BorderStroke(1.dp, memoryDetailBorderColor()),
    ) {
        Column(
            Modifier.padding(start = 16.dp, top = 16.dp, end = 16.dp, bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Surface(
                    modifier = Modifier.size(38.dp),
                    shape = RoundedCornerShape(10.dp),
                    color = if (isKnowledgeDarkTheme()) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.primaryContainer,
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            Icons.Rounded.Description,
                            contentDescription = null,
                            modifier = Modifier.size(22.dp),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
                Text("原始内容", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            }
            SelectionContainer {
                Text(
                    content.ifBlank { "暂无可展示的原始内容" },
                    style = MaterialTheme.typography.bodyLarge,
                    lineHeight = 25.sp,
                )
            }
        }
    }
}

@Composable
private fun memoryDetailBorderColor() =
    if (isKnowledgeDarkTheme()) MaterialTheme.colorScheme.outline else ColorTokens.FlashBorder
