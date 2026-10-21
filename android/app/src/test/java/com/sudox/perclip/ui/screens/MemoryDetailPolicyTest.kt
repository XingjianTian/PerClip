package com.sudox.perclip.ui.screens

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.data.QueuedClipMetadata
import com.sudox.perclip.knowledge.ClipTopicAssignment
import com.sudox.perclip.knowledge.KnowledgeTopicClip
import com.sudox.perclip.knowledge.TopicLabel
import com.sudox.perclip.share.QuickNoteClipBuilder
import com.sudox.perclip.ui.KnowledgeAttachmentFilter
import com.sudox.perclip.ui.KnowledgeHomeFilters
import com.sudox.perclip.ui.KnowledgeRecordState
import com.sudox.perclip.ui.KnowledgeTimeFilter
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import java.time.Instant
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class MemoryDetailPolicyTest {
    @Test
    fun `return anchor prefers stable key then nearest surviving index`() {
        val exact = MemoryListAnchor(stableKey = "local:b", fallbackIndex = 1, offset = 17)
        assertEquals(2, MemoryDetailAnchorPolicy.resolve(exact, listOf("local:a", "remote:x", "local:b")))
        assertEquals(1, MemoryDetailAnchorPolicy.resolve(exact, listOf("local:a", "local:c")))
        assertEquals(0, MemoryDetailAnchorPolicy.resolve(exact.copy(fallbackIndex = 9), listOf("local:a")))
        assertEquals(0, MemoryDetailAnchorPolicy.resolve(exact, emptyList()))
    }

    @Test
    fun `whole card and overflow menu resolve to isolated targets`() {
        assertEquals(MemoryCardClickTarget.DETAIL, MemoryCardClickPolicy.target(menuHit = false))
        assertEquals(MemoryCardClickTarget.MENU, MemoryCardClickPolicy.target(menuHit = true))
    }

    @Test
    fun `detail transitions combine app and system reduced motion`() {
        assertEquals(
            0,
            MemoryDetailTransitionPolicy.durationMillis(
                appReducedMotion = true,
                systemAnimationsDisabled = false,
            ),
        )
        assertEquals(
            0,
            MemoryDetailTransitionPolicy.durationMillis(
                appReducedMotion = false,
                systemAnimationsDisabled = true,
            ),
        )
        assertEquals(
            200,
            MemoryDetailTransitionPolicy.durationMillis(
                appReducedMotion = false,
                systemAnimationsDisabled = false,
            ),
        )
    }

    @Test
    fun `local and remote details share the same source independent transition policy`() {
        val localDuration = MemoryDetailTransitionPolicy.durationMillis(
            appReducedMotion = true,
            systemAnimationsDisabled = false,
        )
        val remoteDuration = MemoryDetailTransitionPolicy.durationMillis(
            appReducedMotion = true,
            systemAnimationsDisabled = false,
        )
        assertEquals(0, localDuration)
        assertEquals(localDuration, remoteDuration)
    }

    @Test
    fun `remote detail shows only formal assignment topics and formats ISO time`() {
        val model = MemoryDetailUiModelFactory.fromRemote(
            KnowledgeTopicClip(
                clipId = "pc_00000000000000000000000000000001",
                title = "文字闪记",
                source = "PerClip",
                capturedAt = "2026-07-26T11:05:16.787Z",
                textPreview = "Stage 23.4D Synthetic Offline",
                tags = listOf("text", "Stage"),
                topicAssignment = ClipTopicAssignment(
                    primary = TopicLabel("teaching", "教学与科研"),
                    secondary = listOf(TopicLabel("automation", "软件开发与自动化")),
                    keywords = listOf("Offline", "Synthetic", "PerClip"),
                    unclassified = false,
                ),
            ),
            zoneId = ZoneId.of("UTC"),
        )

        assertEquals("2026-07-26 11:05", model.capturedAt)
        assertEquals(listOf("教学与科研", "软件开发与自动化"), model.topics.labels)
        assertFalse(model.topics.labels.any { it in setOf("Offline", "Synthetic", "PerClip", "text", "Stage") })
        assertEquals("PerClip", model.sourceLabel)
        assertEquals(MemoryDetailBodyKind.ORIGINAL_TEXT, model.body.kind)
        assertEquals("Stage 23.4D Synthetic Offline", model.body.value)
    }

    @Test
    fun `local detail maps title source body and date but never free tags`() {
        val model = MemoryDetailUiModelFactory.fromLocal(
            UploadRecord(
                clip = SharedClip(
                    id = "local-1",
                    kind = ClipKind.Text,
                    titleHint = "课程设计复盘",
                    text = "本地原始正文",
                ),
                status = UploadStatus.Waiting,
                message = "",
                createdAtEpochMs = Instant.parse("2026-07-26T11:05:16Z").toEpochMilli(),
                metadata = QueuedClipMetadata(
                    tags = listOf("普通关键词"),
                    enrichmentTags = listOf("Offline", "Synthetic"),
                ),
            ),
            zoneId = ZoneId.of("UTC"),
        )

        assertEquals("课程设计复盘", model.title)
        assertEquals("", model.sourceLabel)
        assertEquals(MemoryDetailBodyKind.ORIGINAL_TEXT, model.body.kind)
        assertEquals("本地原始正文", model.body.value)
        assertEquals("2026-07-26 11:05", model.capturedAt)
        assertEquals(emptyList<String>(), model.topics.labels)
    }

    @Test
    fun `unclassified formal assignment remains the sole pending label`() {
        val model = MemoryDetailUiModelFactory.fromRemote(
            KnowledgeTopicClip(
                clipId = "pc_00000000000000000000000000000002",
                title = "待归类记忆",
            ),
            zoneId = ZoneId.of("UTC"),
        )

        assertEquals(listOf("待归类"), model.topics.labels)
    }

    @Test
    fun `missing formal assignment is not treated as unclassified`() {
        val model = MemoryDetailUiModelFactory.fromRemote(
            KnowledgeTopicClip(
                clipId = "pc_00000000000000000000000000000003",
                title = "尚无正式主题的记忆",
                topicAssignment = ClipTopicAssignment(
                    primary = TopicLabel("", ""),
                    keywords = listOf("Offline", "Stage", "普通关键词"),
                    unclassified = false,
                ),
            ),
            zoneId = ZoneId.of("UTC"),
        )

        assertEquals(emptyList<String>(), model.topics.labels)
    }

    @Test
    fun `remote body prefers original text then URL and never promotes summary`() {
        val sourceFaithful = MemoryDetailUiModelFactory.fromRemote(
            remoteClip(
                suffix = "03",
                text = "处理后的提取文本",
                url = "https://perclip.example/备用",
                summary = "摘要",
                originalText = "来源忠实原文",
            ),
        )
        assertEquals(MemoryDetailBodyKind.ORIGINAL_TEXT, sourceFaithful.body.kind)
        assertEquals("来源忠实原文", sourceFaithful.body.value)

        val withTextAndUrl = MemoryDetailUiModelFactory.fromRemote(
            remoteClip(
                suffix = "04",
                text = "正式原始正文",
                url = "https://perclip.example/备用",
                summary = "摘要",
            ),
        )
        assertEquals(MemoryDetailBodyKind.ORIGINAL_TEXT, withTextAndUrl.body.kind)
        assertEquals("正式原始正文", withTextAndUrl.body.value)

        val urlOnly = MemoryDetailUiModelFactory.fromRemote(
            remoteClip(
                suffix = "05",
                text = "",
                url = "https://perclip.example/资料/Stage-23.8D1?mode=review&lang=zh-CN#原始内容",
                summary = "摘要不得冒充原始内容",
            ),
        )
        assertEquals(MemoryDetailBodyKind.ORIGINAL_URL, urlOnly.body.kind)
        assertEquals(
            "https://perclip.example/资料/Stage-23.8D1?mode=review&lang=zh-CN#原始内容",
            urlOnly.body.value,
        )

        val summaryOnly = MemoryDetailUiModelFactory.fromRemote(
            remoteClip(suffix = "06", text = "", url = "", summary = "只有摘要"),
        )
        assertEquals(MemoryDetailBodyKind.EMPTY, summaryOnly.body.kind)
        assertEquals("", summaryOnly.body.value)

        val blank = MemoryDetailUiModelFactory.fromRemote(
            remoteClip(suffix = "07", text = "", url = "", summary = ""),
        )
        assertEquals(MemoryDetailBodyKind.EMPTY, blank.body.kind)
        assertEquals("", blank.body.value)
    }

    @Test
    fun `local body preserves text before URL and exposes URL when text is absent`() {
        val withText = MemoryDetailUiModelFactory.fromLocal(
            localRecord(sourceApp = "PerClip", text = "本地正文", url = "https://perclip.example/local"),
        )
        assertEquals(MemoryDetailBodyKind.ORIGINAL_TEXT, withText.body.kind)
        assertEquals("本地正文", withText.body.value)

        val urlOnly = MemoryDetailUiModelFactory.fromLocal(
            localRecord(sourceApp = "PerClip", text = "", url = "https://perclip.example/local"),
        )
        assertEquals(MemoryDetailBodyKind.ORIGINAL_URL, urlOnly.body.kind)
        assertEquals("https://perclip.example/local", urlOnly.body.value)
    }

    @Test
    fun `local detail source uses only recognized real platforms`() {
        val quickNote = UploadRecord(
            clip = QuickNoteClipBuilder.build("本地闪记正文", id = "quick-note"),
            status = UploadStatus.Waiting,
            message = "",
            createdAtEpochMs = 0L,
        )
        assertEquals("PerClip", MemoryDetailUiModelFactory.fromLocal(quickNote).sourceLabel)
        assertEquals("小红书", MemoryDetailUiModelFactory.fromLocal(localRecord(sourceApp = "com.xingin.xhs")).sourceLabel)
        assertEquals("知乎", MemoryDetailUiModelFactory.fromLocal(localRecord(sourceApp = "com.zhihu.android")).sourceLabel)
        assertEquals("Chrome", MemoryDetailUiModelFactory.fromLocal(localRecord(sourceApp = "com.android.chrome")).sourceLabel)
        assertEquals("", MemoryDetailUiModelFactory.fromLocal(localRecord(sourceApp = "")).sourceLabel)
        assertEquals("", MemoryDetailUiModelFactory.fromLocal(localRecord(sourceApp = "com.example.unknown")).sourceLabel)
        assertEquals("", MemoryDetailUiModelFactory.fromLocal(localRecord(sourceApp = "com.google.android.documentsui")).sourceLabel)
    }

    @Test
    fun `disabled formal assignment stays visible and read only`() {
        val topics = MemoryDetailTopicPolicy.fromRemote(
            ClipTopicAssignment(
                primary = TopicLabel("legacy", "历史正式主题"),
                keywords = listOf("Offline", "Stage"),
                unclassified = false,
                topicDisabled = true,
            ),
        )

        assertEquals(listOf("历史正式主题"), topics.labels)
        assertEquals(MemoryDetailTopicStyle.DISABLED, topics.style)
        assertEquals("该主题已停用", topics.statusLabel)
    }

    @Test
    fun `metadata policy covers none date source and both`() {
        assertEquals(MemoryDetailMetadataLayout.NONE, MemoryDetailMetadataPolicy.resolve("", ""))
        assertEquals(MemoryDetailMetadataLayout.DATE_ONLY, MemoryDetailMetadataPolicy.resolve("2026-07-26 19:05", ""))
        assertEquals(MemoryDetailMetadataLayout.SOURCE_ONLY, MemoryDetailMetadataPolicy.resolve("", "PerClip"))
        assertEquals(MemoryDetailMetadataLayout.BOTH, MemoryDetailMetadataPolicy.resolve("2026-07-26 19:05", "PerClip"))
    }

    @Test
    fun `malformed legacy timestamp never leaks ISO precision markers`() {
        assertEquals(
            "2026-07-26 11:05",
            MemoryDetailDatePolicy.fromRemote(
                "2026-07-26T11:05:16.787Zbad",
                ZoneId.of("UTC"),
            ),
        )
    }

    @Test
    fun `shared date policy covers UTC offset timezone conversion cross year invalid and empty`() {
        val shanghai = ZoneId.of("Asia/Shanghai")
        assertEquals(
            "2026-07-26 19:05",
            MemoryDetailDatePolicy.fromRemote("2026-07-26T11:05:16.787Z", shanghai),
        )
        assertEquals(
            "2026-07-26 11:05",
            MemoryDetailDatePolicy.fromRemote("2026-07-26T11:05:16+08:00", shanghai),
        )
        assertEquals(
            "2025-12-31 23:05",
            MemoryDetailDatePolicy.fromRemote("2025-12-31T23:05:00Z", ZoneId.of("UTC")),
        )
        assertEquals("not-a-date", MemoryDetailDatePolicy.fromRemote("not-a-date", shanghai))
        assertEquals("", MemoryDetailDatePolicy.fromRemote("", shanghai))
        assertEquals(
            "2026-07-26 19:05",
            MemoryDetailDatePolicy.fromEpochMillis(
                Instant.parse("2026-07-26T11:05:16.787Z").toEpochMilli(),
                shanghai,
            ),
        )
    }

    @Test
    fun `local actions are admitted only for local detail with an actual slot`() {
        assertEquals(
            true,
            MemoryDetailActionsPolicy.shouldShow(MemoryDetailSource.Local("local"), actionsAvailable = true),
        )
        assertEquals(
            false,
            MemoryDetailActionsPolicy.shouldShow(MemoryDetailSource.Local("local"), actionsAvailable = false),
        )
        assertEquals(
            false,
            MemoryDetailActionsPolicy.shouldShow(MemoryDetailSource.Remote("remote"), actionsAvailable = true),
        )
    }

    @Test
    fun `search companion filters survive process reconstruction codec`() {
        val filters = KnowledgeHomeFilters(
            status = KnowledgeRecordState.Ingested,
            source = "小红书",
            type = ClipLibraryTypeFilter.Url,
            attachment = KnowledgeAttachmentFilter.WithAttachment,
            time = KnowledgeTimeFilter.Last30Days,
        )
        assertEquals(filters, KnowledgeHomeFiltersSavePolicy.decode(KnowledgeHomeFiltersSavePolicy.encode(filters)))
        assertEquals(KnowledgeHomeFilters(), KnowledgeHomeFiltersSavePolicy.decode(emptyList()))
    }

    private fun localRecord(
        sourceApp: String,
        text: String = "正文",
        url: String = "",
    ): UploadRecord = UploadRecord(
        clip = SharedClip(
            id = "local-source",
            kind = ClipKind.Text,
            titleHint = "来源策略",
            text = text,
            url = url,
            sourceApp = sourceApp,
        ),
        status = UploadStatus.Waiting,
        message = "",
        createdAtEpochMs = 0L,
    )

    private fun remoteClip(
        suffix: String,
        text: String,
        url: String,
        summary: String,
        originalText: String = "",
    ): KnowledgeTopicClip = KnowledgeTopicClip(
        clipId = "pc_${suffix.padStart(32, '0')}",
        title = "正文策略",
        originalText = originalText,
        textPreview = text,
        safeDisplayUrl = url,
        summary = summary,
        topicAssignment = ClipTopicAssignment(primary = TopicLabel("", ""), unclassified = false),
    )
}
