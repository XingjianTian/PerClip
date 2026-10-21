package com.sudox.perclip.debug

import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.LibraryBooks
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Density
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.sudox.perclip.ui.MemoryPlanetTabIcon
import com.sudox.perclip.ui.BottomNavigationIconSlot
import com.sudox.perclip.ui.BottomNavigationSpec
import com.sudox.perclip.ui.bottomNavigationSelection
import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.SharedClipItem
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.design.PerClipTheme
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.capabilities.AppCapabilities
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppFeatures
import com.sudox.perclip.knowledge.KnowledgeBaseRemoteListState
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.knowledge.KnowledgeLibraryScope
import com.sudox.perclip.knowledge.ClipTopicAssignment
import com.sudox.perclip.knowledge.KnowledgeTopicClip
import com.sudox.perclip.knowledge.TopicLabel
import com.sudox.perclip.ui.screens.KnowledgeHomeScreen
import com.sudox.perclip.ui.screens.KnowledgeBaseManagementScreen
import com.sudox.perclip.ui.screens.MemoryDetailScreen
import com.sudox.perclip.ui.screens.MemoryDetailBody
import com.sudox.perclip.ui.screens.MemoryDetailSource
import com.sudox.perclip.ui.screens.MemoryDetailTopics
import com.sudox.perclip.ui.screens.MemoryDetailUiModel
import com.sudox.perclip.ui.screens.MemoryDetailUiModelFactory
import com.sudox.perclip.ui.KnowledgeHomeFilters
import com.sudox.perclip.ui.KnowledgeRecordState
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import com.sudox.perclip.data.QueuedClipMetadata

/** Debug-only fictional records for deterministic screenshots. This class is absent from release builds. */
class KnowledgeEvidenceActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val fixture = intent.getStringExtra("fixture") ?: "data"
        val forceDark = intent.getBooleanExtra("dark", false)
        val records = when (fixture) {
            "empty", "pending-empty", "failed-empty" -> emptyList()
            "stage26" -> KnowledgeFixtures.stage26Records
            "long" -> KnowledgeFixtures.records + (7..34).map { KnowledgeFixtures.record(it) }
            "image" -> listOf(KnowledgeFixtures.imageRecord) + KnowledgeFixtures.records
            else -> KnowledgeFixtures.records
        }
        val bases = if (fixture == "long-bases") KnowledgeFixtures.longBases else KnowledgeFixtures.bases
        val startsInManagement = fixture.startsWith("management-")
        setContent {
            PerClipTheme(darkTheme = forceDark || fixture == "dark" || fixture == "detail-dark" || fixture == "management-dark") {
                val currentDensity = LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(currentDensity.density, if (fixture == "font130" || fixture == "detail-font130" || fixture == "detail-metadata-long-source" || fixture == "management-font130") 1.3f else currentDensity.fontScale)) {
                    var management by remember { mutableStateOf(startsInManagement) }
                    var detailOpen by remember { mutableStateOf(false) }
                    Scaffold(bottomBar = { if (!management && !detailOpen) EvidenceBottomBar() }) { padding ->
                        if (fixture == "v2-topic-detail" || fixture.startsWith("detail-")) {
                            MemoryDetailEvidence(
                                contentPadding = padding,
                                fixture = fixture,
                                onDetailVisibilityChanged = { detailOpen = it },
                            )
                        } else if (fixture == "reduced-detail-flow") {
                            ReducedMotionDetailEvidence(
                                contentPadding = padding,
                                onDetailVisibilityChanged = { detailOpen = it },
                            )
                        } else if (management) KnowledgeBaseManagementScreen(
                            contentPadding = padding,
                            settings = PerClipSettings("", "", "Evidence", true, false),
                            appCapabilityResult = if (fixture == "management-readonly" || fixture == "management-loading") null else KnowledgeFixtures.managementCapability,
                            openDefaultPickerOnLaunch = fixture == "management-default-picker",
                            onBack = { management = false },
                            previewKnowledgeBases = when (fixture) {
                                "management-loading", "management-error" -> null
                                "management-empty" -> emptyList()
                                "management-long" -> KnowledgeFixtures.longBases
                                else -> KnowledgeFixtures.managementBases
                            },
                        ) else KnowledgeHomeScreen(
                        contentPadding = padding,
                        records = records,
                        settings = PerClipSettings(
                            "",
                            "",
                            "Evidence",
                            true,
                            false,
                            reduceMotion = fixture == "reduced-motion",
                        ),
                        topicReadAvailability = com.sudox.perclip.capabilities.AppFeatureAvailability.UNAVAILABLE,
                        requestedDetailClipId = if (fixture == "detail") records.firstOrNull()?.clip?.id else null,
                        onRequestedDetailHandled = {},
                        onDetailVisibilityChanged = { detailOpen = it },
                        knowledgeBases = bases,
                        knowledgeBasesLoading = false,
                        knowledgeBaseRemoteListState = if (fixture == "offline") KnowledgeBaseRemoteListState.FAILED else KnowledgeBaseRemoteListState.SUCCESS,
                        knowledgeBaseListMessage = if (fixture == "offline") "服务暂不可用" else "",
                        processingMessage = "",
                        processingStatusRefreshingClipId = null,
                        selectedKnowledgeScope = KnowledgeLibraryScope.Specific("personal"),
                            onKnowledgeScopeSelected = {}, onRetry = {}, onDelete = {}, onRefreshKnowledgeBases = {}, onRefreshProcessingStatus = {},
                            initialFilters = when (fixture) {
                                "failed", "failed-empty" -> KnowledgeHomeFilters(status = KnowledgeRecordState.Failed)
                                "pending-empty" -> KnowledgeHomeFilters(status = KnowledgeRecordState.Pending)
                                else -> KnowledgeHomeFilters()
                            },
                        )
                    }
                }
            }
        }
    }
}

@androidx.compose.runtime.Composable
private fun MemoryDetailEvidence(
    contentPadding: androidx.compose.foundation.layout.PaddingValues,
    fixture: String,
    onDetailVisibilityChanged: (Boolean) -> Unit,
) {
    LaunchedEffect(Unit) { onDetailVisibilityChanged(true) }
    val longBody = """今天整理 Stage 23.8D1 的共享记忆详情页。

正文需要自然支持多段、中英文混排、URL 与文件名，例如：https://perclip.example/docs/stage23-8d1 和 MemoryDetailScreen.kt。

原始内容是页面主体，不再被亮点、信息卡或重复操作区抢占层级。长正文继续向下增长，由页面统一滚动；返回后仍恢复列表原来的稳定锚点与偏移。

Reduced Motion 开启时，详情进入与退出不播放过渡动画。""".trimIndent()
    val noTopics = ClipTopicAssignment(primary = TopicLabel("", ""), unclassified = false)
    fun remoteFixture(
        idSuffix: String,
        title: String = "文字闪记",
        capturedAt: String = "2026-07-26T11:05:00Z",
        source: String = "PerClip",
        text: String = "Stage 23.4D Synthetic Offline",
        originalText: String = "",
        url: String = "",
        summary: String = "",
        assignment: ClipTopicAssignment = ClipTopicAssignment(
            primary = TopicLabel("teaching", "教学与科研"),
            secondary = listOf(TopicLabel("automation", "软件开发与自动化")),
            unclassified = false,
        ),
    ) = MemoryDetailUiModelFactory.fromRemote(
        KnowledgeTopicClip(
            clipId = "pc_${idSuffix.padStart(32, '0')}",
            title = title,
            capturedAt = capturedAt,
            source = source,
            originalText = originalText,
            textPreview = text,
            safeDisplayUrl = url,
            summary = summary,
            topicAssignment = assignment,
        ),
    )
    val model = when (fixture) {
        "detail-loading", "detail-error" -> null
        "detail-stage29-original" -> remoteFixture(
            idSuffix = "29",
            title = "Stage 29 ScreenClip",
            source = "Chrome · com.android.chrome",
            originalText = "来源忠实原文：Example Domain。此内容来自已安全存储的当前屏幕闪记。",
            text = "不应优先显示的处理文本",
            url = "https://example.test/stage29",
            summary = "不应冒充原始内容的摘要",
            assignment = noTopics,
        )
        "detail-url-only" -> remoteFixture(
            idSuffix = "11",
            title = "URL 原始内容",
            text = "",
            url = "https://perclip.example/资料/Stage-23.8D1?mode=review&lang=zh-CN#原始内容",
            summary = "这段摘要不得冒充原始内容",
            assignment = noTopics,
        )
        "detail-disabled-topic" -> remoteFixture(
            idSuffix = "12",
            title = "历史主题记忆",
            assignment = ClipTopicAssignment(
                primary = TopicLabel("legacy-research", "教学与科研"),
                secondary = listOf(TopicLabel("legacy-automation", "软件开发与自动化")),
                unclassified = false,
                topicDisabled = true,
            ),
        )
        "detail-metadata-date-only" -> remoteFixture(
            idSuffix = "13",
            title = "仅日期元数据",
            source = "",
            assignment = noTopics,
        )
        "detail-metadata-source-only" -> remoteFixture(
            idSuffix = "14",
            title = "仅来源元数据",
            capturedAt = "",
            assignment = noTopics,
        )
        "detail-metadata-neither" -> remoteFixture(
            idSuffix = "15",
            title = "无元数据",
            capturedAt = "",
            source = "",
            assignment = noTopics,
        )
        "detail-metadata-long-source" -> remoteFixture(
            idSuffix = "16",
            title = "长来源与大字体",
            source = "PerClip Synthetic Research Archive 2026 / Knowledge Capture Pipeline",
            assignment = noTopics,
        )
        else -> MemoryDetailUiModel(
            source = if (fixture == "detail-actions") MemoryDetailSource.Local("fixture-local") else MemoryDetailSource.Remote("pc_synthetic_v2_topic"),
            title = if (fixture == "detail-font130") "一条可以自然换行的文字闪记标题" else "文字闪记",
            capturedAt = "2026-07-26 19:05",
            topics = if (fixture == "detail-no-topic" || fixture == "detail-actions") MemoryDetailTopics() else MemoryDetailTopics(listOf("教学与科研", "软件开发与自动化")),
            sourceLabel = "PerClip",
            body = MemoryDetailBody.text(
                when (fixture) {
                    "detail-long" -> longBody
                    "detail-actions" -> "本地保存的正文。操作仅在确实存在时出现在正文之后。"
                    else -> "Stage 23.4D Synthetic Offline"
                },
            ),
        )
    }
    MemoryDetailScreen(
        contentPadding = contentPadding,
        model = model,
        loading = fixture == "detail-loading",
        errorMessage = if (fixture == "detail-error") "这条记忆暂时无法打开" else "",
        reducedMotionOverride = true,
        onBack = {},
        actions = if (fixture == "detail-actions") {
            {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("本地记录操作", style = androidx.compose.material3.MaterialTheme.typography.titleMedium)
                    OutlinedButton(onClick = {}, modifier = Modifier.fillMaxWidth()) { Text("重试同步") }
                    androidx.compose.material3.TextButton(onClick = {}) { Text("刷新处理状态") }
                    androidx.compose.material3.TextButton(onClick = {}) {
                        Text(
                            "删除本地记录",
                            color = androidx.compose.material3.MaterialTheme.colorScheme.error,
                        )
                    }
                }
            }
        } else {
            null
        },
    )
}

@androidx.compose.runtime.Composable
private fun ReducedMotionDetailEvidence(
    contentPadding: androidx.compose.foundation.layout.PaddingValues,
    onDetailVisibilityChanged: (Boolean) -> Unit,
) {
    var selected by remember { mutableStateOf<MemoryDetailUiModel?>(null) }
    val context = LocalContext.current
    val animatorScale = remember(context) {
        runCatching {
            Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE)
        }.getOrDefault(1f)
    }
    LaunchedEffect(selected) { onDetailVisibilityChanged(selected != null) }
    if (selected != null) {
        MemoryDetailScreen(
            contentPadding = contentPadding,
            model = selected,
            reducedMotionOverride = true,
            onBack = { selected = null },
        )
        return
    }
    Column(
        Modifier.fillMaxSize().padding(contentPadding).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("共享记忆详情动效验证", style = androidx.compose.material3.MaterialTheme.typography.headlineSmall)
        Text("App 内减少动态效果：已开启")
        Text("系统动画比例：${animatorScale}×（保持正常）")
        EvidenceDetailLauncher("打开本地记忆详情") {
            selected = MemoryDetailUiModel(
                source = MemoryDetailSource.Local("fixture-local"),
                title = "课程设计复盘",
                capturedAt = "2026-07-26 10:20",
                sourceLabel = "本机保存",
                body = MemoryDetailBody.text("这是一条不包含真实内容的本地证据记录。"),
            )
        }
        EvidenceDetailLauncher("打开服务端记忆详情") {
            selected = MemoryDetailUiModel(
                source = MemoryDetailSource.Remote("fixture-remote"),
                title = "服务端记忆：知识整理方法",
                capturedAt = "2026-07-26 19:05",
                topics = MemoryDetailTopics(listOf("知识管理", "方法")),
                sourceLabel = "PerClip",
                body = MemoryDetailBody.text("这是一条不包含真实内容的服务端证据记录。"),
            )
        }
    }
}

@androidx.compose.runtime.Composable
private fun EvidenceDetailLauncher(label: String, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = androidx.compose.material3.MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, ColorTokens.FlashBorder),
    ) {
        Text(label, Modifier.padding(18.dp), color = ColorTokens.FlashPurple)
    }
}

@androidx.compose.runtime.Composable
private fun EvidenceBottomBar() {
    Surface(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), shape = RoundedCornerShape(22.dp), border = BorderStroke(1.dp, ColorTokens.FlashBorder)) {
        NavigationBar(modifier = Modifier.height(BottomNavigationSpec.NAVIGATION_HEIGHT_DP.dp).bottomNavigationSelection(1), containerColor = Color.Transparent) {
            val colors = NavigationBarItemDefaults.colors(selectedIconColor = ColorTokens.FlashPurple, selectedTextColor = ColorTokens.FlashPurple, indicatorColor = Color.Transparent)
            NavigationBarItem(false, {}, { BottomNavigationIconSlot { Icon(Icons.Rounded.Bolt, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("闪记") }, colors = colors)
            NavigationBarItem(true, {}, { BottomNavigationIconSlot { Icon(Icons.AutoMirrored.Rounded.LibraryBooks, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("知识库") }, colors = colors)
            NavigationBarItem(false, {}, { BottomNavigationIconSlot { MemoryPlanetTabIcon(selected = false, modifier = Modifier.size(BottomNavigationSpec.MEMORY_PLANET_ICON_DP.dp)) } }, label = { Text("记忆星球") }, colors = colors)
            NavigationBarItem(false, {}, { BottomNavigationIconSlot { Icon(Icons.Rounded.Settings, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("设置") }, colors = colors)
        }
    }
}

private object KnowledgeFixtures {
    val managementCapability = AppCapabilityResult(
        ok = true,
        capabilities = AppCapabilities(
            apiContract = "perclip.app.v1",
            service = "perclip-ingest",
            features = AppFeatures(true, true, true, true, true, true, true),
        ),
        message = "ok",
    )
    val bases = listOf(
        KnowledgeBaseSummary("personal", "个人收藏", "日常收集的碎片知识", isDefault = true),
        KnowledgeBaseSummary("work", "工作资料", "项目、会议与工作文档"),
        KnowledgeBaseSummary("reading", "阅读笔记", "文章、论文与书摘"),
    )
    val longBases = bases + (1..18).map { KnowledgeBaseSummary("kb-$it", "这是一个用于验证长列表与长知识库名称的测试知识库 $it") }
    val managementBases = bases + KnowledgeBaseSummary("archive", "旧项目资料", "已结束项目的历史内容", isArchived = true)
    val records = listOf(
        record(1, "如何利用 AI 提升个人生产力", "com.xingin.xhs", UploadStatus.Uploaded),
        record(2, "大模型时代的知识管理思考", "com.zhihu.android", UploadStatus.Waiting),
        record(3, "产品需求文档与核心功能规划——这是用于验证超长标题不会挤压状态和更多操作的完整标题", "com.android.chrome", UploadStatus.Uploaded, true),
        record(4, "微信聊天中的灵感记录", "com.tencent.mm", UploadStatus.Failed),
        record(5, "阅读笔记：如何建立第二大脑", "com.android.chrome", UploadStatus.Uploaded, knowledgeBaseId = "reading", knowledgeBaseName = "阅读笔记"),
        record(6, "工作资料：季度产品路线", "com.android.chrome", UploadStatus.Waiting, knowledgeBaseId = "work", knowledgeBaseName = "工作资料"),
    )
    val stage26Records = listOf("bilibili", "douyin", "xiaohongshu", "zhihu", "weixin", "web").flatMapIndexed { platformIndex, platform ->
        (1..10).map { itemIndex ->
            val index = platformIndex * 10 + itemIndex
            record(
                index = 100 + index,
                title = "Core Memory ${platform}-${itemIndex.toString().padStart(3, '0')}",
                source = when (platform) {
                    "bilibili" -> "tv.danmaku.bili"
                    "douyin" -> "com.ss.android.ugc.aweme"
                    "xiaohongshu" -> "com.xingin.xhs"
                    "zhihu" -> "com.zhihu.android"
                    "weixin" -> "com.tencent.mm"
                    else -> "com.android.chrome"
                },
            )
        }
    }
    val imageRecord = UploadRecord(
        SharedClip("fixture-image", ClipKind.Image, "设计参考图片", text = "三张图片附件的视觉记录", items = (1..3).map { SharedClipItem(Uri.parse("content://perclip.fixture/image-$it"), "参考图-$it.jpg", "image/jpeg", 2048) }, sourceApp = "com.xingin.xhs"),
        UploadStatus.Uploaded, "", createdAtEpochMs = 1_784_000_000_100L, metadata = QueuedClipMetadata(knowledgeBaseId = "personal", knowledgeBaseName = "个人收藏"),
    )
    fun record(index: Int, title: String = "知识记忆 $index", source: String = if (index % 2 == 0) "com.zhihu.android" else "com.xingin.xhs", status: UploadStatus = UploadStatus.Uploaded, attachment: Boolean = false, knowledgeBaseId: String = "personal", knowledgeBaseName: String = "个人收藏"): UploadRecord {
        val items = if (attachment) listOf(SharedClipItem(Uri.parse("content://perclip.fixture/$index"), "资料-$index.pdf", "application/pdf", 2048)) else emptyList()
        return UploadRecord(SharedClip("fixture-$index", if (attachment) ClipKind.File else ClipKind.Url, title, text = "分享一些常用工具和工作流，希望对你有帮助。", url = "https://example.com/$index", items = items, sourceApp = source), status, "", createdAtEpochMs = 1_784_000_000_000L + index, metadata = QueuedClipMetadata(enrichmentSummary = "把常用 AI 工具整理成可复用的个人工作流，并保留关键选择依据。", enrichmentTags = listOf("AI 工具", "工作流"), knowledgeBaseId = knowledgeBaseId, knowledgeBaseName = knowledgeBaseName))
    }
}
