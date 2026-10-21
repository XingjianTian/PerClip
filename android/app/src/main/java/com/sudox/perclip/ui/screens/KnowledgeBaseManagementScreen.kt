package com.sudox.perclip.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppFeatureAvailability
import com.sudox.perclip.capabilities.featureAvailability
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.design.perClipAccentColor
import com.sudox.perclip.design.perClipAccentSoftColor
import com.sudox.perclip.knowledge.KnowledgeBaseApi
import com.sudox.perclip.knowledge.KnowledgeBaseManagementState
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.knowledge.KnowledgeManagementPresentation
import com.sudox.perclip.knowledge.KnowledgeOperationPolicy
import com.sudox.perclip.ui.PerClipSourceIcon
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KnowledgeBaseManagementScreen(
    contentPadding: PaddingValues,
    settings: PerClipSettings,
    appCapabilityResult: AppCapabilityResult? = null,
    openDefaultPickerOnLaunch: Boolean = false,
    onDefaultPickerLaunchConsumed: () -> Unit = {},
    onKnowledgeBasesLoaded: (List<KnowledgeBaseSummary>) -> Unit = {},
    onBack: () -> Unit,
    previewKnowledgeBases: List<KnowledgeBaseSummary>? = null,
) {
    val api = remember { KnowledgeBaseApi() }
    val scope = rememberCoroutineScope()
    var state by remember(previewKnowledgeBases) {
        mutableStateOf(
            KnowledgeBaseManagementState(
                knowledgeBases = previewKnowledgeBases.orEmpty(),
                listLoadedSuccessfully = previewKnowledgeBases != null,
            ),
        )
    }
    var operationId by remember { mutableStateOf<String?>(null) }
    var createOpen by remember { mutableStateOf(false) }
    var renameTarget by remember { mutableStateOf<KnowledgeBaseSummary?>(null) }
    var deleteTarget by remember { mutableStateOf<KnowledgeBaseSummary?>(null) }
    var defaultPickerOpen by remember { mutableStateOf(false) }
    var archivedExpanded by remember { mutableStateOf(false) }
    val operationsEnabled = KnowledgeOperationPolicy.canCrud(appCapabilityResult)

    fun refresh() {
        state = state.copy(listLoading = true, listError = "")
        scope.launch {
            val result = withContext(Dispatchers.IO) { api.listKnowledgeBases(settings) }
            state = state.withListResult(result, System.currentTimeMillis())
            if (result.ok) onKnowledgeBasesLoaded(state.knowledgeBases)
        }
    }

    fun mutate(targetId: String, action: suspend () -> String) {
        if (!operationsEnabled) {
            state = state.copy(mutationMessage = "当前服务仅支持查看知识库。")
            return
        }
        operationId = targetId
        scope.launch {
            val message = withContext(Dispatchers.IO) { action() }
            val result = withContext(Dispatchers.IO) { api.listKnowledgeBases(settings) }
            state = state.finishMutation(message, result, System.currentTimeMillis())
            operationId = null
            if (result.ok) onKnowledgeBasesLoaded(state.knowledgeBases)
        }
    }

    LaunchedEffect(settings.apiUrl, settings.ingestToken, appCapabilityResult, previewKnowledgeBases) {
        if (previewKnowledgeBases != null) return@LaunchedEffect
        when (appCapabilityResult.featureAvailability { it.knowledgeBases }) {
            AppFeatureAvailability.AVAILABLE -> refresh()
            AppFeatureAvailability.UNAVAILABLE -> state = state.copy(
                listLoading = false,
                listError = appCapabilityResult?.message.orEmpty().ifBlank { "当前服务端不支持知识库功能。" },
            )
            AppFeatureAvailability.CHECKING -> state = state.copy(listLoading = true)
        }
    }

    val active = KnowledgeManagementPresentation.active(state.knowledgeBases)
    val archived = KnowledgeManagementPresentation.archived(state.knowledgeBases)
    val default = active.firstOrNull { it.isDefault }

    LaunchedEffect(openDefaultPickerOnLaunch, state.listLoading, active.size) {
        if (!openDefaultPickerOnLaunch || state.listLoading) return@LaunchedEffect
        if (active.size > 1 && operationsEnabled) defaultPickerOpen = true
        onDefaultPickerLaunchConsumed()
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(knowledgeBackgroundColor())
            .padding(contentPadding),
    ) {
        ManagementTopBar(onBack = onBack, onAdd = { createOpen = true }, addEnabled = operationsEnabled && operationId == null)
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 12.dp, bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (!operationsEnabled && state.knowledgeBases.isNotEmpty()) {
                item("read-only") { InlineMessage("当前服务仅支持查看知识库。", warning = true) }
            }
            if (state.listError.isNotBlank()) {
                item("list-error") {
                    InlineMessage(
                        if (state.knowledgeBases.isEmpty()) state.listError else "刷新失败，当前显示上次成功读取的内容。",
                        warning = true,
                        action = if (appCapabilityResult.featureAvailability { it.knowledgeBases } == AppFeatureAvailability.AVAILABLE) "重试" else null,
                        onAction = ::refresh,
                    )
                }
            }
            if (state.mutationMessage.isNotBlank()) {
                item("mutation-message") { InlineMessage(state.mutationMessage, warning = state.mutationMessage.isFailureMessage()) }
            }
            if (state.listLoading && state.knowledgeBases.isEmpty()) {
                item("loading") { ManagementLoading() }
            } else if (state.showEmpty) {
                item("empty") { EmptyKnowledgeBases(onCreate = { createOpen = true }, createEnabled = operationsEnabled) }
            } else if (state.knowledgeBases.isNotEmpty()) {
                item("default-heading") { SectionHeading("默认知识库") }
                item("default-card") {
                    if (default != null) {
                        DefaultKnowledgeBaseCard(default, enabled = active.size > 1 && operationId == null) { defaultPickerOpen = true }
                    } else {
                        InlineMessage("尚未设置默认知识库。", warning = true)
                    }
                }
                item("active-heading") { SectionHeading("我的知识库") }
                items(active, key = { "library:${it.id}" }) { knowledgeBase ->
                    KnowledgeBaseRow(
                        knowledgeBase = knowledgeBase,
                        operationsEnabled = operationsEnabled && operationId == null,
                        busy = operationId == knowledgeBase.id,
                        onRename = { renameTarget = knowledgeBase },
                        onSetDefault = {
                            mutate(knowledgeBase.id) {
                                val result = api.setDefault(settings, knowledgeBase.id)
                                if (result.ok) "已设为默认知识库，只影响之后保存的记忆。" else result.message
                            }
                        },
                        onDelete = { deleteTarget = knowledgeBase },
                    )
                }
                if (archived.isNotEmpty()) {
                    item("archived-toggle") {
                        ArchivedDisclosure(archived.size, archivedExpanded) { archivedExpanded = !archivedExpanded }
                    }
                    if (archivedExpanded) {
                        items(archived, key = { "archived:${it.id}" }) { knowledgeBase ->
                            ArchivedKnowledgeBaseRow(knowledgeBase)
                        }
                    }
                }
                item("platforms") { SupportedPlatforms() }
            }
        }
    }

    if (defaultPickerOpen) {
        ModalBottomSheet(onDismissRequest = { defaultPickerOpen = false }, containerColor = knowledgeSurfaceColor()) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("选择默认知识库", style = PerClipSettingsTypography.RowTitle, color = settingsPrimaryTextColor())
                Text(
                    "只影响之后新保存的记忆，不迁移历史内容。",
                    style = PerClipSettingsTypography.Supporting,
                    color = settingsSecondaryTextColor(),
                )
                active.forEach { knowledgeBase ->
                    DefaultPickerRow(knowledgeBase, operationId == null) {
                        defaultPickerOpen = false
                        mutate(knowledgeBase.id) {
                            val result = api.setDefault(settings, knowledgeBase.id)
                            if (result.ok) "已设为默认知识库，只影响之后保存的记忆。" else result.message
                        }
                    }
                }
            }
        }
    }
    if (createOpen) {
        KnowledgeBaseEditDialog("新建知识库", "", "", "创建", { createOpen = false }) { name, description ->
            createOpen = false
            mutate("create") {
                val result = api.createKnowledgeBase(settings, name, description)
                if (result.ok) "知识库已创建。" else result.message
            }
        }
    }
    renameTarget?.let { target ->
        KnowledgeBaseEditDialog("重命名知识库", target.name, target.description, "保存", { renameTarget = null }) { name, description ->
            renameTarget = null
            mutate(target.id) {
                val result = api.updateKnowledgeBase(settings, target.id, name, description)
                if (result.ok) "知识库已更新。" else result.message
            }
        }
    }
    deleteTarget?.let { target ->
        ConfirmKnowledgeBaseDialog(
            title = "移除知识库关联",
            body = "只移除 PerClip 中的知识库关联，不会删除服务端数据。此操作不适用于当前默认知识库。",
            confirmLabel = "确认删除",
            destructive = true,
            onDismiss = { deleteTarget = null },
        ) {
            deleteTarget = null
            mutate(target.id) {
                val result = api.deleteKnowledgeBase(settings, target.id)
                if (result.ok) "知识库关联已移除，服务端数据未删除。" else result.message
            }
        }
    }
}

@Composable
private fun ManagementTopBar(onBack: () -> Unit, onAdd: () -> Unit, addEnabled: Boolean) {
    Row(Modifier.fillMaxWidth().height(64.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
            Icon(Icons.AutoMirrored.Rounded.ArrowBack, "返回")
        }
        Text("知识库管理", modifier = Modifier.weight(1f), style = PerClipSettingsTypography.PageTitle, color = settingsPrimaryTextColor())
        IconButton(onClick = onAdd, enabled = addEnabled, modifier = Modifier.size(48.dp)) {
            Surface(color = perClipAccentSoftColor(), shape = CircleShape) {
                Box(Modifier.size(36.dp), contentAlignment = Alignment.Center) {
                    Icon(Icons.Rounded.Add, "新建知识库", tint = perClipAccentColor())
                }
            }
        }
    }
}

@Composable
private fun SectionHeading(title: String) {
    Text(title, style = PerClipSettingsTypography.RowTitle, color = settingsPrimaryTextColor())
}

@Composable
private fun DefaultKnowledgeBaseCard(knowledgeBase: KnowledgeBaseSummary, enabled: Boolean, onClick: () -> Unit) {
    Card(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = knowledgeSurfaceColor()),
        border = BorderStroke(1.dp, knowledgeBorderColor()),
    ) {
        Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            LibraryMark(knowledgeBase.displayName)
            Spacer(Modifier.width(10.dp))
            LibraryCopy(knowledgeBase, Modifier.weight(1f))
            DefaultPill("当前默认")
            Spacer(Modifier.width(4.dp))
            Icon(Icons.Rounded.ChevronRight, null, tint = settingsSecondaryTextColor())
        }
    }
}

@Composable
private fun KnowledgeBaseRow(
    knowledgeBase: KnowledgeBaseSummary,
    operationsEnabled: Boolean,
    busy: Boolean,
    onRename: () -> Unit,
    onSetDefault: () -> Unit,
    onDelete: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = knowledgeSurfaceColor()),
        border = BorderStroke(1.dp, knowledgeBorderColor()),
    ) {
        Row(Modifier.fillMaxWidth().padding(start = 14.dp, top = 12.dp, bottom = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            LibraryMark(knowledgeBase.displayName)
            Spacer(Modifier.width(10.dp))
            LibraryCopy(knowledgeBase, Modifier.weight(1f))
            if (knowledgeBase.isDefault) DefaultPill("默认")
            Box {
                IconButton(onClick = { menuOpen = true }, enabled = operationsEnabled, modifier = Modifier.size(48.dp)) {
                    if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) else Icon(Icons.Rounded.MoreVert, "知识库更多操作")
                }
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    if (!knowledgeBase.isDefault) DropdownMenuItem(text = { Text("设为默认") }, onClick = { menuOpen = false; onSetDefault() })
                    DropdownMenuItem(text = { Text("重命名") }, onClick = { menuOpen = false; onRename() })
                    if (!knowledgeBase.isDefault) DropdownMenuItem(text = { Text("移除关联", color = MaterialTheme.colorScheme.error) }, onClick = { menuOpen = false; onDelete() })
                }
            }
        }
    }
}

@Composable
private fun ArchivedKnowledgeBaseRow(knowledgeBase: KnowledgeBaseSummary) {
    Surface(modifier = Modifier.fillMaxWidth(), color = knowledgeSurfaceColor(), shape = RoundedCornerShape(16.dp), border = BorderStroke(1.dp, knowledgeBorderColor())) {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            LibraryMark(knowledgeBase.displayName)
            Spacer(Modifier.width(10.dp))
            LibraryCopy(knowledgeBase, Modifier.weight(1f))
            DefaultPill("已归档")
        }
    }
}

@Composable
private fun LibraryMark(name: String) {
    Surface(Modifier.size(44.dp), color = perClipAccentSoftColor(), shape = RoundedCornerShape(12.dp)) {
        Box(contentAlignment = Alignment.Center) {
            Text(libraryMarkText(name), color = perClipAccentColor(), fontWeight = FontWeight.Black)
        }
    }
}

@Composable
private fun LibraryCopy(knowledgeBase: KnowledgeBaseSummary, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(knowledgeBase.displayName, style = PerClipSettingsTypography.RowTitle, color = settingsPrimaryTextColor(), maxLines = 2, overflow = TextOverflow.Ellipsis)
        if (knowledgeBase.description.isNotBlank()) {
            Text(knowledgeBase.description, style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor(), maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun DefaultPill(label: String) {
    Surface(color = perClipAccentSoftColor(), shape = RoundedCornerShape(8.dp)) {
        Text(
            label,
            Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
            style = PerClipSettingsTypography.Supporting,
            color = perClipAccentColor(),
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
private fun ArchivedDisclosure(count: Int, expanded: Boolean, onClick: () -> Unit) {
    TextButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Text(
            "历史归档（$count）",
            modifier = Modifier.weight(1f),
            style = PerClipSettingsTypography.RowTitle,
            color = settingsPrimaryTextColor(),
        )
        Text(if (expanded) "收起" else "展开", color = perClipAccentColor())
        Icon(if (expanded) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore, null, tint = perClipAccentColor())
    }
}

private data class SupportedPlatform(val source: String, val label: String)
private val supportedPlatforms = listOf(
    SupportedPlatform("xiaohongshu", "小红书"), SupportedPlatform("zhihu", "知乎"),
    SupportedPlatform("wechat", "微信"), SupportedPlatform("chrome", "网页"),
    SupportedPlatform("bilibili", "Bilibili"), SupportedPlatform("x", "X"),
    SupportedPlatform("medium", "Medium"), SupportedPlatform("more", "更多"),
)

@Composable
private fun SupportedPlatforms() {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionHeading("支持的平台")
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            supportedPlatforms.forEach { platform ->
                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    PerClipSourceIcon(platform.source, Modifier.size(32.dp), compact = true)
                    Text(
                        platform.label,
                        style = PerClipSettingsTypography.Supporting,
                        color = settingsSecondaryTextColor(),
                        maxLines = 1,
                    )
                }
            }
        }
    }
}

@Composable
private fun DefaultPickerRow(knowledgeBase: KnowledgeBaseSummary, enabled: Boolean, onClick: () -> Unit) {
    Surface(onClick = onClick, enabled = enabled, modifier = Modifier.fillMaxWidth(), color = Color.Transparent, shape = RoundedCornerShape(16.dp)) {
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            LibraryMark(knowledgeBase.displayName)
            Spacer(Modifier.width(10.dp))
            LibraryCopy(knowledgeBase, Modifier.weight(1f))
            if (knowledgeBase.isDefault) { Icon(Icons.Rounded.Check, "当前默认", tint = perClipAccentColor()) }
        }
    }
}

@Composable
private fun InlineMessage(
    text: String,
    warning: Boolean = false,
    success: Boolean = false,
    action: String? = null,
    onAction: () -> Unit = {},
) {
    val container = when { warning -> MaterialTheme.colorScheme.errorContainer; success -> Color(0xFFEAF8EF); else -> perClipAccentSoftColor() }
    val content = when {
        warning -> MaterialTheme.colorScheme.onErrorContainer
        success -> Color(0xFF177A4B)
        else -> settingsSecondaryTextColor()
    }
    Surface(modifier = Modifier.fillMaxWidth(), color = container, shape = RoundedCornerShape(14.dp)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            if (success) { Icon(Icons.Rounded.Check, null, tint = content, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)) }
            Text(text, modifier = Modifier.weight(1f), style = PerClipSettingsTypography.Supporting, color = content)
            if (action != null) TextButton(onClick = onAction) { Text(action) }
        }
    }
}

@Composable
private fun ManagementLoading() {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SectionHeading("默认知识库")
        repeat(3) {
            Surface(Modifier.fillMaxWidth().height(72.dp), color = knowledgeSurfaceColor(), shape = RoundedCornerShape(18.dp), border = BorderStroke(1.dp, knowledgeBorderColor())) {}
        }
    }
}

@Composable
private fun EmptyKnowledgeBases(onCreate: () -> Unit, createEnabled: Boolean) {
    Surface(Modifier.fillMaxWidth(), color = knowledgeSurfaceColor(), shape = RoundedCornerShape(20.dp), border = BorderStroke(1.dp, knowledgeBorderColor())) {
        Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
            LibraryMark("K")
            Text("还没有知识库", style = PerClipSettingsTypography.RowTitle, color = settingsPrimaryTextColor())
            Text("创建第一个知识库，之后保存的记忆会进入默认库。", style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor())
            Button(onClick = onCreate, enabled = createEnabled) { Icon(Icons.Rounded.Add, null); Spacer(Modifier.width(6.dp)); Text("新建知识库") }
        }
    }
}

@Composable
private fun KnowledgeBaseEditDialog(title: String, initialName: String, initialDescription: String, confirmLabel: String, onDismiss: () -> Unit, onConfirm: (String, String) -> Unit) {
    var name by remember(initialName) { mutableStateOf(initialName) }
    var description by remember(initialDescription) { mutableStateOf(initialDescription) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(name, { name = it }, label = { Text("名称") }, singleLine = true)
            OutlinedTextField(description, { description = it }, label = { Text("说明（选填）") }, minLines = 2)
        } },
        confirmButton = { Button(enabled = name.trim().isNotBlank(), onClick = { onConfirm(name.trim(), description.trim()) }) { Text(confirmLabel) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
private fun ConfirmKnowledgeBaseDialog(title: String, body: String, confirmLabel: String, destructive: Boolean = false, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) }, text = { Text(body) },
        confirmButton = { Button(onClick = onConfirm, colors = if (destructive) ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error) else ButtonDefaults.buttonColors()) { Text(confirmLabel) } },
        dismissButton = { OutlinedButton(onClick = onDismiss) { Text("取消") } },
    )
}

private fun String.isFailureMessage() = contains("失败") || contains("HTTP") || contains("认证") || contains("错误")

private fun libraryMarkText(name: String) = when {
    name.contains("工作") || name.contains("项目") -> "W"
    name.contains("学习") || name.contains("成长") -> "L"
    name.contains("阅读") -> "R"
    name.firstOrNull()?.isLetter() == true && name.first().code < 128 -> name.first().uppercase()
    else -> "K"
}
