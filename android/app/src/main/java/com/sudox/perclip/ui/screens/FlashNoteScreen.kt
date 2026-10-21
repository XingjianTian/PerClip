package com.sudox.perclip.ui.screens

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.graphics.BitmapFactory
import android.media.MediaRecorder
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AttachFile
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.DeleteOutline
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.Link
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.ScreenshotMonitor
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.TextButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sudox.perclip.ClipKind
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.design.perClipIsDarkTheme
import com.sudox.perclip.label
import com.sudox.perclip.SharedClip
import com.sudox.perclip.SharedClipItem
import com.sudox.perclip.share.QuickNoteClipBuilder
import com.sudox.perclip.ui.ClipPreviewMetadata
import com.sudox.perclip.ui.ImagePreviewPolicy
import com.sudox.perclip.ui.design.PerClipBrandMark
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

@Composable
fun FlashNoteScreen(
    contentPadding: PaddingValues,
    clip: SharedClip?,
    quickText: String,
    isSaving: Boolean,
    uploadMessage: String,
    defaultKnowledgeBaseName: String,
    onChangeDefaultKnowledgeBase: () -> Unit,
    onClearClip: () -> Unit,
    onQuickTextChange: (String) -> Unit,
    onClipSelected: (SharedClip) -> Unit,
    onSaved: (SharedClip, String) -> Unit,
) {
    val scrollState = rememberScrollState()
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding)
            .then(if (clip == null) Modifier else Modifier.verticalScroll(scrollState))
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Header()
        Spacer(Modifier.height(12.dp))
        DefaultKnowledgeBaseEntry(
            name = defaultKnowledgeBaseName,
            onClick = onChangeDefaultKnowledgeBase,
        )
        Spacer(Modifier.height(12.dp))

        if (clip == null) {
            EmptyShareState(
                modifier = Modifier.weight(1f),
                isSaving = isSaving,
                quickText = quickText,
                onQuickTextChange = onQuickTextChange,
                onClipSelected = onClipSelected,
                onSaved = onSaved,
            )
        } else {
            ClipPreview(
                clip = clip,
                isSaving = isSaving,
                onClearClip = onClearClip,
                onClipSelected = onClipSelected,
                onSaved = onSaved,
            )
        }
        if (uploadMessage.isNotBlank()) {
            Spacer(Modifier.height(12.dp))
            FlashSaveFeedback(uploadMessage)
        }
    }
}

@Composable
private fun FlashSaveFeedback(message: String) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = ColorTokens.FlashSuccess.copy(alpha = 0.1f),
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, ColorTokens.FlashSuccess.copy(alpha = 0.28f)),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Rounded.CheckCircle,
                contentDescription = null,
                tint = ColorTokens.FlashSuccess,
            )
            Spacer(Modifier.width(8.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                color = ColorTokens.FlashSuccess,
            )
        }
    }
}

@Composable
private fun Header() {
    val headerGlow = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.9f)
    val headerOrbit = MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .shadow(6.dp, RoundedCornerShape(20.dp)),
        color = flashSurfaceColor(),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Box(modifier = Modifier.height(96.dp)) {
            Canvas(Modifier.fillMaxSize()) {
                val radius = 62.dp.toPx()
                val center = Offset(size.width - 24.dp.toPx(), 18.dp.toPx())
                drawCircle(
                    color = headerGlow,
                    radius = radius,
                    center = center,
                )
                rotate(degrees = -14f, pivot = center) {
                    drawOval(
                        color = headerOrbit,
                        topLeft = Offset(center.x - radius * 1.45f, center.y - radius * 0.42f),
                        size = Size(radius * 2.9f, radius * 0.84f),
                        style = Stroke(width = 3.dp.toPx()),
                    )
                }
            }
            Row(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PerClipBrandMark(
                    modifier = Modifier.size(48.dp),
                    contentDescription = "PerClip",
                )
                Spacer(Modifier.width(14.dp))
                Column {
                    Text(
                        text = "PerClip",
                        style = MaterialTheme.typography.headlineLarge,
                        fontWeight = FontWeight.Black,
                        color = flashInkColor(),
                    )
                    Text(
                        text = "一键保存至私有云",
                        style = MaterialTheme.typography.bodyLarge,
                        color = flashMutedColor(),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
private fun DefaultKnowledgeBaseEntry(
    name: String,
    onClick: () -> Unit,
) {
    Surface(
        onClick = onClick,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp),
        color = flashSurfaceColor(),
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 3.dp,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "默认保存至",
                    style = MaterialTheme.typography.bodySmall,
                    color = flashMutedColor(),
                )
                Text(
                    text = name.ifBlank { "尚未设置" },
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = "更改",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.primary,
            )
            Spacer(Modifier.width(8.dp))
            Icon(
                Icons.Rounded.ChevronRight,
                contentDescription = null,
                tint = flashMutedColor(),
            )
        }
    }
}

@Composable
private fun EmptyShareState(
    modifier: Modifier = Modifier,
    isSaving: Boolean,
    quickText: String,
    onQuickTextChange: (String) -> Unit,
    onClipSelected: (SharedClip) -> Unit,
    onSaved: (SharedClip, String) -> Unit,
) {
    val context = LocalContext.current
    val trimmedText = quickText.trim()
    val recordingUi = rememberRecordingUiState { item ->
        val clip = if (quickText.trim().isBlank()) {
            buildSingleAttachmentClip(item, titleHint = item.displayName.ifBlank { "录音闪记" })
        } else {
            QuickNoteClipBuilder.build(quickText.trim()).withAddedItems(listOf(item))
        }
        onClipSelected(clip)
        onQuickTextChange("")
    }
    val attachmentPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.GetMultipleContents(),
    ) { uris ->
        val attachmentClip = context.buildAttachmentClip(uris)
        if (attachmentClip == null) {
            Toast.makeText(context, "没有选择可保存的附件。", Toast.LENGTH_SHORT).show()
        } else {
            val clip = if (quickText.trim().isBlank()) {
                attachmentClip
            } else {
                QuickNoteClipBuilder.build(quickText.trim()).withAddedItems(attachmentClip.items)
            }
            onClipSelected(clip)
            onQuickTextChange("")
        }
    }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .shadow(3.dp, RoundedCornerShape(20.dp)),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = flashSurfaceColor()),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Rounded.Edit,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(30.dp),
                )
                Spacer(Modifier.width(10.dp))
                Column {
                    Text(
                        text = "新建闪记",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Black,
                        color = flashInkColor(),
                    )
                }
            }

            MinimalComposer(
                modifier = Modifier.weight(1f),
                value = quickText,
                onValueChange = onQuickTextChange,
                placeholder = "今天要记住什么？",
                minHeight = 224.dp,
                expandToParent = true,
                onAttachmentClick = { attachmentPicker.launch("*/*") },
                isRecording = recordingUi.isRecording,
                onRecordClick = recordingUi.onRecordClick,
            )

            Button(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
                enabled = !isSaving && FlashNoteUiLogic.emptyPrimaryActionEnabled(recordingUi.isRecording),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = Color.White,
                    disabledContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.4f),
                    disabledContentColor = Color.White.copy(alpha = 0.8f),
                ),
                shape = RoundedCornerShape(14.dp),
                onClick = {
                    if (!FlashNoteUiLogic.canSaveText(trimmedText)) {
                        Toast.makeText(context, "请输入内容，或先添加附件、录音。", Toast.LENGTH_SHORT).show()
                    } else {
                        onSaved(
                            QuickNoteClipBuilder.build(trimmedText),
                            "",
                        )
                    }
                },
            ) {
                Icon(Icons.AutoMirrored.Rounded.Send, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(
                    text = if (isSaving) "正在保存..." else FlashNoteUiLogic.primaryActionLabel(),
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

@Composable
private fun ClipPreview(
    clip: SharedClip,
    isSaving: Boolean,
    onClearClip: () -> Unit,
    onClipSelected: (SharedClip) -> Unit,
    onSaved: (SharedClip, String) -> Unit,
) {
    val context = LocalContext.current
    var note by remember(clip.id) { mutableStateOf("") }
    val singleAttachment = remember(clip) {
        clip.items.singleOrNull()?.let { item ->
            FlashAttachmentPresentationPolicy.forSingleAttachment(
                titleHint = clip.titleHint,
                text = clip.text,
                sourceApp = clip.sourceApp,
                displayName = item.displayName,
                mimeType = item.mimeType,
                sizeBytes = item.sizeBytes,
            )
        }
    }
    val recordingUi = rememberRecordingUiState { item ->
        onClipSelected(clip.withAddedItems(listOf(item)))
    }
    val attachmentPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.GetMultipleContents(),
    ) { uris ->
        val attachmentClip = context.buildAttachmentClip(uris)
        if (attachmentClip == null) {
            Toast.makeText(context, "没有选择可保存的附件。", Toast.LENGTH_SHORT).show()
        } else {
            onClipSelected(clip.withAddedItems(attachmentClip.items))
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Card(
            modifier = Modifier.shadow(3.dp, RoundedCornerShape(20.dp)),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = flashSurfaceColor()),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Row(
                        modifier = Modifier.weight(1f),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            if (singleAttachment?.isAudio == true) Icons.Rounded.Mic else iconFor(clip.kind),
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Spacer(Modifier.width(10.dp))
                        Text(
                            text = singleAttachment?.typeLabel ?: clip.kind.label(),
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                    TextButton(onClick = onClearClip) {
                        Icon(
                            Icons.Rounded.DeleteOutline,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.error,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.width(4.dp))
                        Text(
                            text = "移除",
                            color = MaterialTheme.colorScheme.error,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
                val headline = singleAttachment?.headline
                    ?: clip.titleHint.ifBlank { "未命名收藏" }.takeIf { singleAttachment == null }
                headline?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                if (singleAttachment == null) {
                    ClipMetadataLine(clip)
                }
                PreviewBody(clip, singleAttachment)
            }
        }

        MinimalComposer(
            value = note,
            onValueChange = { note = it },
            placeholder = "补充备注...",
            minHeight = 104.dp,
            onAttachmentClick = { attachmentPicker.launch("*/*") },
            isRecording = recordingUi.isRecording,
            onRecordClick = recordingUi.onRecordClick,
        )

        Button(
            modifier = Modifier
                .fillMaxWidth()
                .height(54.dp),
            enabled = !isSaving && !recordingUi.isRecording,
            colors = ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = Color.White,
                disabledContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.4f),
                disabledContentColor = Color.White.copy(alpha = 0.8f),
            ),
            shape = RoundedCornerShape(14.dp),
            onClick = { onSaved(clip, note) },
        ) {
            Icon(Icons.Rounded.CheckCircle, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text(
                text = if (isSaving) {
                    "正在保存..."
                } else {
                    FlashNoteUiLogic.primaryActionLabel()
                },
                fontWeight = FontWeight.Bold,
            )
        }

    }
}

@Composable
private fun MinimalComposer(
    modifier: Modifier = Modifier,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    minHeight: androidx.compose.ui.unit.Dp,
    expandToParent: Boolean = false,
    onAttachmentClick: () -> Unit,
    isRecording: Boolean = false,
    onRecordClick: () -> Unit,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = minHeight),
        shape = RoundedCornerShape(16.dp),
        color = if (perClipIsDarkTheme()) MaterialTheme.colorScheme.surfaceVariant else ColorTokens.FlashBackground,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Column(
            modifier = if (expandToParent) {
                Modifier
                    .fillMaxSize()
                    .padding(horizontal = 14.dp, vertical = 12.dp)
            } else {
                Modifier.padding(horizontal = 14.dp, vertical = 12.dp)
            },
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            BasicTextField(
                modifier = if (expandToParent) {
                    Modifier
                        .fillMaxWidth()
                        .weight(1f)
                } else {
                    Modifier
                        .fillMaxWidth()
                        .heightIn(min = minHeight - 56.dp)
                },
                value = value,
                onValueChange = onValueChange,
                textStyle = MaterialTheme.typography.bodyLarge.copy(
                    color = flashInkColor(),
                ),
                decorationBox = { innerTextField ->
                    Box(Modifier.fillMaxSize()) {
                        if (value.isBlank()) {
                            Text(
                                text = placeholder,
                                style = MaterialTheme.typography.bodyLarge,
                                color = flashMutedColor().copy(alpha = 0.52f),
                            )
                        }
                        innerTextField()
                    }
                },
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ComposerToolPill(
                    icon = Icons.Rounded.AttachFile,
                    label = "附件",
                    onClick = onAttachmentClick,
                )
                ComposerToolPill(
                    icon = Icons.Rounded.Mic,
                    label = if (isRecording) "停止" else "录音",
                    emphasized = isRecording,
                    onClick = onRecordClick,
                )
            }
            if (isRecording) {
                Text(
                    text = "正在录音，点击停止保存为附件",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

@Composable
private fun ComposerToolPill(
    icon: ImageVector,
    label: String,
    emphasized: Boolean = false,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .heightIn(min = 48.dp)
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(999.dp),
        color = if (emphasized) {
            MaterialTheme.colorScheme.errorContainer
        } else {
            flashSurfaceColor()
        },
        border = BorderStroke(1.dp, if (emphasized) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.outline),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
                tint = if (emphasized) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.primary,
            )
            Spacer(Modifier.width(5.dp))
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
                color = if (emphasized) MaterialTheme.colorScheme.onErrorContainer else flashMutedColor(),
            )
        }
    }
}

@Composable
private fun flashSurfaceColor(): Color {
    return if (perClipIsDarkTheme()) MaterialTheme.colorScheme.surface else Color.White
}

@Composable
private fun flashInkColor(): Color {
    return if (perClipIsDarkTheme()) MaterialTheme.colorScheme.onSurface else ColorTokens.FlashInk
}

@Composable
private fun flashMutedColor(): Color {
    return if (perClipIsDarkTheme()) MaterialTheme.colorScheme.onSurfaceVariant else ColorTokens.FlashMuted
}

private data class RecordingUiState(
    val isRecording: Boolean,
    val onRecordClick: () -> Unit,
)

@Composable
private fun rememberRecordingUiState(onRecorded: (SharedClipItem) -> Unit): RecordingUiState {
    val context = LocalContext.current
    val recorder = remember { AudioClipRecorder(context.applicationContext) }
    var isRecording by remember { mutableStateOf(false) }

    fun startRecording() {
        val started = recorder.start()
        if (started) {
            isRecording = true
            Toast.makeText(context, "开始录音，再点一次停止。", Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(context, "录音启动失败。", Toast.LENGTH_SHORT).show()
        }
    }

    fun stopRecording() {
        val recordedItem = recorder.stop()
        isRecording = false
        if (recordedItem == null) {
            Toast.makeText(context, "录音太短或保存失败。", Toast.LENGTH_SHORT).show()
            return
        }
        onRecorded(recordedItem)
        Toast.makeText(context, "录音已添加为附件。", Toast.LENGTH_SHORT).show()
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            startRecording()
        } else {
            Toast.makeText(context, "需要麦克风权限才能录音。", Toast.LENGTH_SHORT).show()
        }
    }

    DisposableEffect(recorder) {
        onDispose {
            recorder.cancel()
        }
    }

    return RecordingUiState(
        isRecording = isRecording,
        onRecordClick = {
            if (isRecording) {
                stopRecording()
            } else if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                startRecording()
            } else {
                permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            }
        },
    )
}

@Composable
private fun ClipMetadataLine(clip: SharedClip) {
    val metadata = listOfNotNull(
        ClipPreviewMetadata.sourceLabel(clip.sourceApp),
        ClipPreviewMetadata.totalSizeLabel(clip),
    )
    if (metadata.isEmpty()) return

    Text(
        text = metadata.joinToString(" · "),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
private fun PreviewBody(
    clip: SharedClip,
    singleAttachment: FlashAttachmentPresentation?,
) {
    if (clip.text.isBlank() && clip.items.isEmpty()) {
        Text("PerClip 会先保存到本机，并在网络可用时后台同步。")
        return
    }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (clip.text.isNotBlank()) {
            Text(
                text = clip.text,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 6,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (clip.items.isNotEmpty()) {
            AttachmentPreviewList(clip, singleAttachment)
        }
    }
}

@Composable
private fun AttachmentPreviewList(
    clip: SharedClip,
    singleAttachment: FlashAttachmentPresentation?,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (ImagePreviewPolicy.shouldShowThumbnail(clip.kind, clip.items.map { it.mimeType })) {
            ImageThumbnail(uri = clip.items.first().uri)
        }
        if (singleAttachment != null) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = singleAttachment.fileName,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (singleAttachment.metadata.isNotBlank()) {
                    Text(
                        text = singleAttachment.metadata,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            return@Column
        }
        clip.items.take(5).forEach { item ->
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = item.displayName,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = listOfNotNull(
                        item.mimeType.ifBlank { null },
                        ClipPreviewMetadata.formatByteSize(item.sizeBytes),
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (clip.items.size > 5) {
            Text(
                text = "另有 ${clip.items.size - 5} 个文件",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ImageThumbnail(uri: Uri) {
    val context = LocalContext.current
    var image by remember(uri) { mutableStateOf<ImageBitmap?>(null) }

    LaunchedEffect(uri) {
        image = decodePreviewBitmap(context, uri)
    }

    image?.let { bitmap ->
        Image(
            bitmap = bitmap,
            contentDescription = null,
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(16f / 9f)
                .clip(RoundedCornerShape(8.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentScale = ContentScale.Crop,
        )
    }
}

private suspend fun decodePreviewBitmap(context: Context, uri: Uri): ImageBitmap? = withContext(Dispatchers.IO) {
    val resolver = context.contentResolver
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    runCatching {
        resolver.openInputStream(uri)?.use { stream ->
            BitmapFactory.decodeStream(stream, null, bounds)
        }
    }.getOrNull()

    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return@withContext null

    val sampleSize = calculateBitmapSampleSize(bounds.outWidth, bounds.outHeight, maxDimension = 1200)
    val decodeOptions = BitmapFactory.Options().apply { inSampleSize = sampleSize }
    runCatching {
        resolver.openInputStream(uri)?.use { stream ->
            BitmapFactory.decodeStream(stream, null, decodeOptions)?.asImageBitmap()
        }
    }.getOrNull()
}

private fun calculateBitmapSampleSize(width: Int, height: Int, maxDimension: Int): Int {
    var sampleSize = 1
    var sampledWidth = width
    var sampledHeight = height
    while (sampledWidth / 2 >= maxDimension || sampledHeight / 2 >= maxDimension) {
        sampleSize *= 2
        sampledWidth /= 2
        sampledHeight /= 2
    }
    return sampleSize
}

private fun Context.buildAttachmentClip(uris: List<Uri>): SharedClip? {
    val items = uris.distinct().mapNotNull { uri ->
        runCatching { describeAttachmentUri(uri) }.getOrNull()
    }
    if (items.isEmpty()) return null

    return buildAttachmentClipFromItems(items)
}

private fun buildSingleAttachmentClip(
    item: SharedClipItem,
    titleHint: String = item.displayName.ifBlank { "附件闪记" },
): SharedClip {
    return buildAttachmentClipFromItems(listOf(item)).copy(titleHint = titleHint)
}

private fun buildAttachmentClipFromItems(items: List<SharedClipItem>): SharedClip {
    val allImages = items.all { it.mimeType.startsWith("image/") }
    val kind = when {
        items.size > 1 -> if (allImages) ClipKind.Image else ClipKind.Multiple
        allImages -> ClipKind.Image
        items.firstOrNull()?.mimeType?.startsWith("audio/") == true -> ClipKind.File
        else -> ClipKind.File
    }
    val title = when {
        items.size == 1 -> items.first().displayName.ifBlank { "附件闪记" }
        allImages -> "${items.size} 张图片"
        else -> "${items.size} 个附件"
    }
    return SharedClip(
        id = UUID.randomUUID().toString(),
        kind = kind,
        titleHint = title,
        items = items,
        mimeType = if (items.size == 1) items.first().mimeType else "*/*",
        sourceApp = "PerClip",
    )
}

private fun SharedClip.withAddedItems(extraItems: List<SharedClipItem>): SharedClip {
    if (extraItems.isEmpty()) return this
    val mergedItems = items + extraItems
    val textOnly = text.isBlank() && url.isBlank()
    val allImages = mergedItems.all { it.mimeType.startsWith("image/") }
    val nextKind = when {
        textOnly && mergedItems.size == 1 && allImages -> ClipKind.Image
        textOnly && mergedItems.size == 1 -> ClipKind.File
        textOnly && allImages -> ClipKind.Image
        else -> ClipKind.Multiple
    }
    return copy(
        kind = nextKind,
        items = mergedItems,
        mimeType = if (mergedItems.size == 1 && textOnly) mergedItems.first().mimeType else "*/*",
    )
}

private fun Context.describeAttachmentUri(uri: Uri): SharedClipItem {
    val resolver = contentResolver
    val mimeType = resolver.getType(uri) ?: "application/octet-stream"
    var displayName = uri.lastPathSegment ?: "未命名文件"
    var sizeBytes: Long? = null

    resolver.query(uri, null, null, null, null)?.use { cursor: Cursor ->
        val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
        if (cursor.moveToFirst()) {
            if (nameIndex >= 0) {
                displayName = cursor.getString(nameIndex).orEmpty().ifBlank { displayName }
            }
            if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) {
                sizeBytes = cursor.getLong(sizeIndex)
            }
        }
    }

    return SharedClipItem(
        uri = uri,
        displayName = displayName,
        mimeType = mimeType,
        sizeBytes = sizeBytes,
    )
}

private class AudioClipRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    private var outputFile: File? = null

    fun start(): Boolean {
        cancel()
        val file = recordingFile(context)
        val mediaRecorder = createMediaRecorder(context)
        return runCatching {
            mediaRecorder.setAudioSource(MediaRecorder.AudioSource.MIC)
            mediaRecorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            mediaRecorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            mediaRecorder.setAudioChannels(1)
            mediaRecorder.setAudioEncodingBitRate(48_000)
            mediaRecorder.setAudioSamplingRate(16_000)
            mediaRecorder.setOutputFile(file.absolutePath)
            mediaRecorder.prepare()
            mediaRecorder.start()
            recorder = mediaRecorder
            outputFile = file
        }.fold(
            onSuccess = { true },
            onFailure = {
                mediaRecorder.release()
                file.delete()
                recorder = null
                outputFile = null
                false
            },
        )
    }

    fun stop(): SharedClipItem? {
        val activeRecorder = recorder ?: return null
        val file = outputFile ?: return null
        recorder = null
        outputFile = null
        val stopped = runCatching {
            activeRecorder.stop()
        }.isSuccess
        activeRecorder.release()

        if (!stopped || file.length() <= 0L) {
            file.delete()
            return null
        }

        return SharedClipItem(
            uri = file.toUri(),
            displayName = file.name,
            mimeType = AUDIO_MIME_TYPE,
            sizeBytes = file.length(),
        )
    }

    fun cancel() {
        val activeRecorder = recorder
        val file = outputFile
        recorder = null
        outputFile = null
        runCatching {
            activeRecorder?.stop()
        }
        activeRecorder?.release()
        file?.delete()
    }

    private fun recordingFile(context: Context): File {
        val dir = File(context.cacheDir, "recordings").apply { mkdirs() }
        return File(dir, "录音-${timestamp()}.m4a")
    }

    private fun timestamp(): String {
        return SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
    }

    private fun createMediaRecorder(context: Context): MediaRecorder {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }
    }

    private companion object {
        const val AUDIO_MIME_TYPE = "audio/mp4"
    }
}

private fun iconFor(kind: ClipKind): ImageVector = when (kind) {
    ClipKind.Url -> Icons.Rounded.Link
    ClipKind.Image -> Icons.Rounded.Image
    ClipKind.File, ClipKind.Multiple -> Icons.Rounded.AttachFile
    ClipKind.ScreenClip -> Icons.Rounded.ScreenshotMonitor
    ClipKind.Text, ClipKind.Unknown -> Icons.Rounded.ContentPaste
}
