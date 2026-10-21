package com.sudox.perclip.knowledge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeTopicJsonTest {
    @Test
    fun `core memory explicit states survive list parsing for display and detail`() {
        val page = KnowledgeTopicJson.parseKnowledgeList(
            """
            {
              "ok": true,
              "contract_version": "perclip.knowledge-list.v2",
              "scope": {"knowledge_base_ids": []},
              "items": [{
                "public_clip_id": "pc_00000000000000000000000000000001",
                "knowledge_base_ids": ["kb_default"],
                "title": "受限页面标题",
                "summary": "内容暂不可用",
                "source": "未明确来源",
                "captured_at": "2026-08-25T00:00:00Z",
                "topic_assignment": {
                  "contract_version": "perclip.topic-assignment.v1",
                  "primary": {"topic_id": "unclassified", "display_name": "待归类", "source": "unclassified"},
                  "secondary": [], "entities": [], "keywords": [], "unclassified": true,
                  "manual_override": false, "topic_disabled": false
                },
                "item_revision": 1,
                "updated_at": "2026-08-25T00:00:00Z"
              }],
              "summary": {"total_count": 1, "matching_count": 1, "revision": 1, "generated_at": "2026-08-25T00:00:00Z"},
              "next_cursor": ""
              ,"has_more": false
            }
            """.trimIndent(),
        )

        val clip = page.items.single().clip
        assertEquals("受限页面标题", clip.title)
        assertEquals("未明确来源", clip.source)
        assertEquals("内容暂不可用", clip.summary)
    }

    @Test
    fun `page exposes at most two card topics and no internal execution fields`() {
        val page = KnowledgeTopicJson.parsePage(
            """{"ok":true,"contract_version":"perclip.quality-read.v1","knowledge_base":{"id":"kb_public","name":"Synthetic"},"items":[{"clip_id":"pc_00000000000000000000000000000001","title":"Fictional memory","summary":"Safe summary","source":"Fixture","captured_at":"2026-07-01T00:00:00Z","topic_assignment":{"contract_version":"perclip.topic-assignment.v1","primary":{"topic_id":"ai_ml","display_name":"AI 与大模型"},"secondary":[{"topic_id":"work","display_name":"工作"},{"topic_id":"reading","display_name":"阅读"}],"entities":["PerClip"],"keywords":["Android"],"unclassified":false,"manual_override":false,"topic_disabled":false}}],"next_cursor":null}""",
        )

        assertEquals(1, page.items.size)
        assertEquals("", page.nextCursor)
        assertEquals(listOf("AI 与大模型", "工作"), page.items.single().topicAssignment.cardTopics.map { it.displayName })
        assertFalse(page.toString().contains("engine"))
        assertFalse(page.toString().contains("run_id"))
    }

    @Test
    fun `detail retains user-facing topic fields and manual state`() {
        val detail = KnowledgeTopicJson.parseDetail(
            """{"ok":true,"quality_read":{"contract_version":"perclip.quality-read.v1","clip_id":"pc_00000000000000000000000000000002","active_content":{"title":"Fictional detail","summary":"Summary","source":"Fixture","captured_at":"2026-07-02T00:00:00Z","original_text":"Source-faithful original","text_preview":"Safe extracted excerpt","safe_display_url":"https://example.invalid/story","tags":["睡眠","text","Stage231"]},"topic_assignment":{"contract_version":"perclip.topic-assignment.v1","primary":{"topic_id":"health","display_name":"健康"},"secondary":[],"entities":["角色甲"],"keywords":["睡眠","text","knowledge-base","个人收藏","PersonalClips","Stage231"],"unclassified":false,"manual_override":true,"topic_disabled":false}}}""",
        )

        assertTrue(detail.clip.topicAssignment.manualOverride)
        assertEquals(listOf("角色甲"), detail.clip.topicAssignment.entities)
        assertEquals(listOf("睡眠"), detail.clip.topicAssignment.keywords)
        assertEquals("Source-faithful original", detail.clip.originalText)
        assertEquals("Safe extracted excerpt", detail.clip.textPreview)
        assertEquals("https://example.invalid/story", detail.clip.safeDisplayUrl)
        assertEquals(listOf("睡眠"), detail.clip.tags)
    }

    @Test
    fun `disabled topic keeps its name and becomes correction only`() {
        val page = KnowledgeTopicJson.parsePage(
            """{"ok":true,"contract_version":"perclip.quality-read.v1","knowledge_base":{"id":"kb_public","name":"Synthetic"},"items":[{"clip_id":"pc_00000000000000000000000000000003","title":"Historical topic","summary":"Safe","source":"Fixture","captured_at":"2026-07-03T00:00:00Z","topic_assignment":{"contract_version":"perclip.topic-assignment.v1","primary":{"topic_id":"football","display_name":"足球观察"},"secondary":[],"entities":[],"keywords":[],"unclassified":false,"manual_override":false,"topic_disabled":true}}],"next_cursor":null}""",
        )
        val assignment = page.items.single().topicAssignment
        assertTrue(assignment.topicDisabled)
        assertTrue(assignment.correctionOnly)
        assertEquals("足球观察", assignment.primary.displayName)
        assertEquals("该主题已停用", assignment.statusLabel)
        assertFalse(assignment.unclassified)
    }

    @Test
    fun `correction choices contain enabled classified topics only`() {
        val registry = KnowledgeTopicJson.parseRegistry(
            """
            {
              "ok": true,
              "registry": {
                "topics": [
                  {"topic_id": "ai_ml", "display_name": "AI 与大模型", "enabled": true},
                  {"topic_id": "football", "display_name": "足球观察", "enabled": false},
                  {"topic_id": "unclassified", "display_name": "待归类", "enabled": true}
                ]
              }
            }
            """.trimIndent(),
        )

        assertEquals(listOf("ai_ml"), registry.selectableTopics.map { it.id })
    }
}
