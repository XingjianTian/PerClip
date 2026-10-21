package com.sudox.perclip.debug

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.remember
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.automirrored.rounded.LibraryBooks
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.design.PerClipTheme
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.recall.RecallGraph
import com.sudox.perclip.recall.RecallGraphEdge
import com.sudox.perclip.recall.RecallGraphNode
import com.sudox.perclip.recall.RecallHighlight
import com.sudox.perclip.recall.RecallMetrics
import com.sudox.perclip.recall.RecallOverview
import com.sudox.perclip.recall.RecallProgress
import com.sudox.perclip.recall.RecallSession
import com.sudox.perclip.recall.RecallSessionItem
import com.sudox.perclip.recall.RecallSessionResponse
import com.sudox.perclip.recall.RecallTopic
import com.sudox.perclip.recall.RecallTopicClip
import com.sudox.perclip.recall.RecallTopicDetail
import com.sudox.perclip.recall.RecallTopicMetrics
import com.sudox.perclip.recall.RecallWeeklyItem
import com.sudox.perclip.recall.RecallWeeklyReview
import com.sudox.perclip.recall.RecallWeeklySummary
import com.sudox.perclip.recall.RecallWeeklyTopic
import com.sudox.perclip.recall.RecallWindow
import com.sudox.perclip.ui.recall.RecallDestination
import com.sudox.perclip.ui.recall.RecallResource
import com.sudox.perclip.ui.recall.RecallUiState
import com.sudox.perclip.ui.recall.RecallStateHolder
import com.sudox.perclip.ui.recall.RecallScreen
import com.sudox.perclip.ui.MemoryPlanetTabIcon
import com.sudox.perclip.ui.BottomNavigationIconSlot
import com.sudox.perclip.ui.BottomNavigationSpec
import com.sudox.perclip.ui.bottomNavigationSelection
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import com.sudox.perclip.ui.recall.RecallPeriod
import com.sudox.perclip.ui.recall.RecallScope
import com.sudox.perclip.ui.recall.RecallPresentationState
import com.sudox.perclip.recall.repository.RecallDomainMemory
import com.sudox.perclip.recall.repository.RecallDomainPresentationDefaults
import com.sudox.perclip.recall.repository.RecallDomainSnapshot
import com.sudox.perclip.recall.repository.RecallDomainTopic
import com.sudox.perclip.recall.repository.RecallResurfaceItem
import com.sudox.perclip.recall.repository.RecallResurfacePage
import com.sudox.perclip.recall.repository.MemoryPlanet

/** Debug-only visual evidence entry. Fixtures are fictional and never ship in release. */
class RecallEvidenceActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val fixture = intent.getStringExtra("fixture") ?: "overview_data"
        val forceDark = intent.getBooleanExtra("dark", false)
        setContent {
            PerClipTheme(darkTheme = forceDark || fixture == "dark" || fixture == "dark_motion" || fixture == "reduced_dark") {
                val density = LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(density.density, if (fixture == "font130") 1.3f else density.fontScale)) {
                Scaffold(bottomBar = {
                    Surface(
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp).shadow(8.dp, RoundedCornerShape(22.dp)),
                        color = androidx.compose.material3.MaterialTheme.colorScheme.surface,
                        shape = RoundedCornerShape(22.dp),
                        border = BorderStroke(1.dp, ColorTokens.FlashBorder),
                    ) {
                    NavigationBar(modifier = Modifier.height(BottomNavigationSpec.NAVIGATION_HEIGHT_DP.dp).bottomNavigationSelection(2), containerColor = Color.Transparent) {
                        val navItemColors = NavigationBarItemDefaults.colors(selectedIconColor = ColorTokens.FlashPurple, selectedTextColor = ColorTokens.FlashPurple, indicatorColor = Color.Transparent, unselectedIconColor = androidx.compose.material3.MaterialTheme.colorScheme.onSurfaceVariant, unselectedTextColor = androidx.compose.material3.MaterialTheme.colorScheme.onSurfaceVariant)
                        NavigationBarItem(selected = false, onClick = {}, icon = { BottomNavigationIconSlot { Icon(Icons.Rounded.Bolt, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("闪记") }, colors = navItemColors)
                        NavigationBarItem(selected = false, onClick = {}, icon = { BottomNavigationIconSlot { Icon(Icons.AutoMirrored.Rounded.LibraryBooks, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("知识库") }, colors = navItemColors)
                        NavigationBarItem(selected = true, onClick = {}, icon = { BottomNavigationIconSlot { MemoryPlanetTabIcon(selected = true, modifier = Modifier.size(BottomNavigationSpec.MEMORY_PLANET_ICON_DP.dp)) } }, label = { Text("记忆星球") }, colors = navItemColors)
                        NavigationBarItem(selected = false, onClick = {}, icon = { BottomNavigationIconSlot { Icon(Icons.Rounded.Settings, null, Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp)) } }, label = { Text("设置") }, colors = navItemColors)
                    }
                    }
                }) { padding ->
                    RecallScreen(
                        contentPadding = padding,
                        settings = PerClipSettings(
                            "",
                            "",
                            "Evidence",
                            true,
                            false,
                            recallGraphExpanded = fixture != "collapsed",
                            reduceMotion = fixture.startsWith("reduced_"),
                        ),
                        localRecords = emptyList(),
                        knowledgeBases = listOf(
                            KnowledgeBaseSummary("kb-personal", "个人收藏", isDefault = true),
                            KnowledgeBaseSummary("kb-development", "开发测试"),
                        ),
                        knowledgeBasesLoading = false,
                        knowledgeBaseListMessage = "",
                        onRefreshKnowledgeBases = {},
                        onOpenLocalClip = {},
                        onGoToSave = {},
                        featureAvailability = com.sudox.perclip.capabilities.AppFeatureAvailability.CHECKING,
                        memoryPlanetAvailability = com.sudox.perclip.capabilities.AppFeatureAvailability.AVAILABLE,
                        holder = remember(fixture) { RecallStateHolder(EvidenceFixtures.state(fixture)) },
                    )
                }
                }
            }
        }
    }
}

private object EvidenceFixtures {
    private val domainTopics = listOf(
        RecallDomainTopic("topic:teaching", "教学", "教学", 18, colorSlot = 0, iconSlot = "school"),
        RecallDomainTopic("topic:project", "项目", "项目", 12, colorSlot = 1, iconSlot = "project"),
        RecallDomainTopic("topic:paper", "论文", "论文", 9, colorSlot = 2, iconSlot = "paper"),
        RecallDomainTopic("topic:idea", "想法 / 回想", "想法", 16, colorSlot = 3, iconSlot = "idea"),
        RecallDomainTopic("topic:ai", "AI 工具", "AI 工具", 24, colorSlot = 4, iconSlot = "tools"),
    )
    private val domainMemories = listOf(
        RecallDomainMemory("memory:notion", "clip:notion", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai"), label = "Notion AI 使用笔记", shortLabel = "Notion AI", summary = "记录了本地 Docker 环境部署 RAGFlow 的完整流程，包括环境准备、服务配置与常见问题处理。", sourceType = "note", tags = listOf("AI 工具", "部署"), capturedAt = "2026-05-12T14:30:00Z"),
        RecallDomainMemory("memory:cursor", "clip:cursor", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai"), label = "Cursor 最佳实践", shortLabel = "Cursor", summary = "记录项目上下文与规则配置方法。", sourceType = "note", tags = listOf("AI 工具", "开发"), capturedAt = "2026-05-11T18:40:00Z"),
        RecallDomainMemory("memory:ragflow", "clip:ragflow", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai", "topic:project"), label = "RAGFlow 部署小记", shortLabel = "RAGFlow", summary = "记录了在本地 Docker 环境中部署 RAGFlow 的完整流程，包括环境准备、服务配置与常见问题处理。", sourceType = "note", tags = listOf("AI 工具", "项目", "部署"), capturedAt = "2026-05-12T06:30:00Z"),
        RecallDomainMemory("memory:prompt", "clip:prompt", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai", "topic:idea"), label = "提示词设计心得", shortLabel = "Prompt", summary = "好的提示词应包含角色、任务、上下文、约束与输出格式，形成可复用的结构。", sourceType = "idea", tags = listOf("想法", "Prompt"), capturedAt = "2026-05-08T09:20:00Z"),
        RecallDomainMemory("memory:evaluation", "clip:evaluation", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai"), label = "AI 评测记录", shortLabel = "AI 评测", summary = "整理模型评测方法。", sourceType = "note", tags = listOf("AI 工具", "评测"), capturedAt = "2026-05-07T08:00:00Z"),
        RecallDomainMemory("memory:compose-motion", "clip:compose-motion", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai", "topic:project"), label = "Compose 动效笔记", shortLabel = "Compose", summary = "用同一进度驱动列表位移、淡出和记忆圈更新，避免两套动画不同步。", sourceType = "note", tags = listOf("AI 工具", "Compose"), capturedAt = "2026-05-06T15:20:00Z"),
        RecallDomainMemory("memory:vector-search", "clip:vector-search", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai"), label = "向量检索调优", shortLabel = "向量检索", summary = "记录召回数量、相似度阈值与重排策略之间的取舍。", sourceType = "note", tags = listOf("AI 工具", "检索"), capturedAt = "2026-05-05T11:10:00Z"),
        RecallDomainMemory("memory:local-model", "clip:local-model", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai"), label = "本地模型评测", shortLabel = "模型评测", summary = "比较本地模型在摘要、标签和结构化抽取任务上的稳定性。", sourceType = "note", tags = listOf("AI 工具", "模型"), capturedAt = "2026-05-04T08:45:00Z"),
        RecallDomainMemory("memory:prompt-chain", "clip:prompt-chain", primaryTopicId = "topic:ai", topicIds = listOf("topic:ai", "topic:idea"), label = "提示链复盘", shortLabel = "提示链", summary = "复盘多步骤提示链中的上下文衰减与错误传递。", sourceType = "idea", tags = listOf("想法", "Prompt"), capturedAt = "2026-05-03T19:00:00Z"),
    )
    private val domain = RecallDomainSnapshot(
        windowDays = 7,
        topics = domainTopics,
        memories = domainMemories,
        presentationDefaults = RecallDomainPresentationDefaults(visibleLabelCount = 5, labelRotationSeconds = 8, defaultDays = 7),
    )
    private val resurfaced = RecallResurfacePage(items = listOf(
        domainMemories.first { it.id == "memory:ragflow" }.let { memory ->
            RecallResurfaceItem(memory.clipId, topicId = memory.primaryTopicId, title = memory.label, summary = memory.summary, sourceType = memory.sourceType, tags = memory.tags, capturedAt = memory.capturedAt)
        },
        RecallResurfaceItem("clip:teaching-method", topicId = "topic:teaching", title = "教学方法笔记", summary = "课堂互动设计要围绕学生的认知节奏，问题要层层递进。", sourceType = "note", tags = listOf("教学", "方法", "设计"), capturedAt = "2026-05-10T01:15:00Z"),
        domainMemories.first { it.id == "memory:prompt" }.let { memory ->
            RecallResurfaceItem(memory.clipId, topicId = memory.primaryTopicId, title = memory.label, summary = memory.summary, sourceType = memory.sourceType, tags = memory.tags, capturedAt = memory.capturedAt)
        },
    ))
    private val overviewGraph = RecallGraph(
        nodes = listOf(
            RecallGraphNode("topic:ai", "topic", "AI Agent", 8, 0, "topic:ai"),
            RecallGraphNode("topic:teaching", "topic", "教学", 5, 1, "topic:teaching"),
            RecallGraphNode("topic:reading", "topic", "论文阅读", 4, 2, "topic:reading"),
            RecallGraphNode("topic:workflow", "topic", "工作流设计", 3, 3, "topic:workflow"),
            RecallGraphNode("clip:101", "clip", "工具使用模式", 1, 0, clipId = "101"),
            RecallGraphNode("clip:102", "clip", "课程设计笔记", 1, 1, clipId = "102"),
            RecallGraphNode("clip:103", "clip", "论文问题树", 1, 2, clipId = "103"),
            RecallGraphNode("clip:104", "clip", "流程节点命名", 1, 3, clipId = "104"),
        ),
        edges = listOf(
            RecallGraphEdge("topic:ai", "clip:101", "contains"), RecallGraphEdge("topic:teaching", "clip:102", "contains"),
            RecallGraphEdge("topic:reading", "clip:103", "contains"), RecallGraphEdge("topic:workflow", "clip:104", "contains"),
        ),
    )
    private val topicGraph = RecallGraph(
        nodes = listOf(
            RecallGraphNode("topic:ai", "topic", "AI Agent", 8, 0, "topic:ai"),
            RecallGraphNode("topic:teaching", "topic", "教学", 2, 1, "topic:teaching"),
            RecallGraphNode("clip:101", "clip", "工具使用模式", 1, 0, clipId = "101"),
            RecallGraphNode("clip:102", "clip", "提示词复盘", 1, 0, clipId = "102"),
            RecallGraphNode("clip:103", "clip", "行动路径", 1, 0, clipId = "103"),
            RecallGraphNode("clip:104", "clip", "任务拆分", 1, 0, clipId = "104"),
        ),
        edges = listOf(
            RecallGraphEdge("topic:ai", "clip:101", "contains"), RecallGraphEdge("topic:ai", "clip:102", "contains"),
            RecallGraphEdge("topic:ai", "clip:103", "contains"), RecallGraphEdge("topic:ai", "clip:104", "contains"),
        ),
    )
    private val overview = RecallOverview(
        RecallWindow(7, "2026-07-04T00:00:00Z", "2026-07-10T12:00:00Z"),
        RecallMetrics(8, 6, 4, .62), overviewGraph,
        listOf(RecallHighlight("topic", "AI Agent 有新发现", "新增 3 条闪记，连接了 2 个相关主题", "topic:ai", occurredAt = "2026-07-10T09:00:00Z"), RecallHighlight("clip", "教学：知识图谱的应用", "整理成可复用的课堂素材", clipId = "102", occurredAt = "2026-07-09T09:00:00Z")),
    )
    private val sessionItem = RecallSessionItem(
        "item-101",
        "101",
        title = "ReAct 与工具使用模式",
        summary = "将推理过程与外部工具调用组合，形成清晰、可追溯的行动路径。",
        revealText = "复杂任务中，将思考、工具调用和结果观察串成连续记录，可以在回看时迅速恢复当时的判断路径，也能理解每一步为何发生。",
        tags = listOf("AI Agent", "推理", "框架"),
        sourceLabel = "项目笔记",
        knowledgeBaseName = "个人知识库",
        capturedAt = "2026-07-10T09:00:00Z",
    )
    private val activeSession = RecallSessionResponse(RecallSession("session-evidence", status = "active", totalItems = 3, currentPosition = 1), listOf(sessionItem), sessionItem, RecallProgress(0, 3, 1))
    fun state(name: String): RecallUiState = when (name) {
        "overview_empty" -> RecallUiState(domain = RecallResource(value = RecallDomainSnapshot()), resurfaced = RecallResource(value = RecallResurfacePage()))
        "topic" -> RecallUiState(destination = RecallDestination.Topic("topic:ai"), domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai"), topic = RecallResource(value = RecallTopicDetail(topic = RecallTopic("topic:ai", "AI Agent", 8), metrics = RecallTopicMetrics(4, 3, 1), graph = topicGraph, items = listOf(RecallTopicClip("101", title = "ReAct 与工具使用模式", summary = "将推理与工具调用组合，形成清晰的行动路径。", tags = listOf("AI Agent", "推理"), sourceLabel = "项目笔记", capturedAt = "2026-07-10T09:00:00Z"), RecallTopicClip("103", title = "论文阅读工作流", summary = "用主题和问题串起阅读笔记。", tags = listOf("论文", "方法"), sourceLabel = "阅读器", capturedAt = "2026-07-09T09:00:00Z")))))
        "teaching" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:teaching", lastInteractionAt = Long.MAX_VALUE / 2))
        "collapsed" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", graphExpanded = false, lastInteractionAt = Long.MAX_VALUE / 2))
        "monthly" -> RecallUiState(domain = RecallResource(value = domain.copy(windowDays = 30)), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", period = RecallPeriod.MONTHLY, lastInteractionAt = Long.MAX_VALUE / 2))
        "topic_scope" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", scope = RecallScope.ACTIVE_TOPIC, lastInteractionAt = Long.MAX_VALUE / 2))
        "auto_off" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", autoSurfaceEnabled = false))
        "motion" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", lastInteractionAt = 0L))
        "dark_motion" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", lastInteractionAt = 0L))
        "fifo_motion" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", scope = RecallScope.ACTIVE_TOPIC, lastInteractionAt = 0L))
        "resume_2s" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", lastInteractionAt = System.currentTimeMillis()))
        "display_settings" -> RecallUiState(destination = RecallDestination.DisplaySettings, domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", lastInteractionAt = Long.MAX_VALUE / 2))
        "display_compact" -> RecallUiState(domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:teaching", visibleTopicCount = 3, visibleMemoryLabels = 3, hiddenTopicIds = setOf("topic:paper"), lastInteractionAt = Long.MAX_VALUE / 2))
        "session_hidden" -> RecallUiState(destination = RecallDestination.Session("session-evidence"), session = RecallResource(value = activeSession))
        "session_revealed" -> RecallUiState(destination = RecallDestination.Session("session-evidence"), session = RecallResource(value = activeSession), revealedItemId = "item-101", revealedText = sessionItem.revealText)
        "weekly" -> RecallUiState(destination = RecallDestination.Weekly, weekly = RecallResource(value = RecallWeeklyReview(summary = RecallWeeklySummary(8, 6, 3, 4, "这周重新浮现了 8 条闪记，回看了 6 次，串起 3 个主题。"), topTopics = listOf(RecallWeeklyTopic("topic:ai", "AI Agent", 3, 4), RecallWeeklyTopic("topic:teaching", "教学", 2, 2)), mostRecalled = listOf(RecallWeeklyItem("101", "ReAct 与工具使用模式", "topic:ai", "AI Agent", 3)), suggestedItems = listOf(RecallWeeklyItem("102", "课程设计笔记", "topic:teaching", "教学")))))
        "loading" -> RecallUiState(memoryPlanet = RecallResource<MemoryPlanet>(loading = true), domain = RecallResource(value = RecallDomainSnapshot(), loading = true), resurfaced = RecallResource(loading = true))
        "error" -> RecallUiState(memoryPlanet = RecallResource<MemoryPlanet>(error = "暂时无法加载记忆星球内容，请检查连接后重试。"), domain = RecallResource(value = RecallDomainSnapshot(), error = "暂时无法加载记忆星球内容，请检查连接后重试。"))
        else -> RecallUiState(overview = RecallResource(value = overview), domain = RecallResource(value = domain), resurfaced = RecallResource(value = resurfaced), presentation = RecallPresentationState(activeTopicId = "topic:ai", lastInteractionAt = Long.MAX_VALUE / 2))
    }
}
