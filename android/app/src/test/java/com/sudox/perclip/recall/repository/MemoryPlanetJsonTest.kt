package com.sudox.perclip.recall.repository

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MemoryPlanetJsonTest {
    @Test
    fun `parser enforces five by five and one memory only once`() {
        fun memory(id: Int) = """{"clip_id":"pc_${id.toString(16).padStart(32, '0')}","title":"Memory $id","summary":"Synthetic","captured_at":"2026-07-01T00:00:00Z","source":"Fixture"}"""
        val topics = (1..6).joinToString(",") { topic ->
            val memories = (1..6).joinToString(",") { item -> memory(if (topic == 2 && item == 1) 1 else topic * 10 + item) }
            """{"topic_id":"topic_$topic","display_name":"Topic $topic","memory_count":6,"memories":[$memories]}"""
        }
        val parsed = MemoryPlanetJson.parse(
            """{"ok":true,"planet":{"contract_version":"perclip.memory-planet.v1","window":{"kind":"month","days":30,"start":"","end":""},"topics":[$topics],"unclassified_count":1,"unclassified_preview":[${memory(99)}],"has_more_unclassified":false}}""",
        )

        assertEquals(5, parsed.topics.size)
        assertEquals(5, parsed.topics.first().memories.size)
        val ids = parsed.topics.flatMap { it.memories }.map { it.clipId }
        assertEquals(ids.distinct(), ids)
        assertFalse(parsed.toString().contains("chunk", ignoreCase = true))
    }

    @Test
    fun `small unclassified memories remain a separate entry`() {
        val parsed = MemoryPlanetJson.parse(
            """{"ok":true,"planet":{"contract_version":"perclip.memory-planet.v1","window":{"kind":"custom","days":5,"start":"2026-06-30T16:00:00Z","end":"2026-07-05T16:00:00Z","start_date":"2026-07-01","end_date":"2026-07-05","timezone":"Asia/Shanghai"},"topics":[],"unclassified_count":1,"unclassified_preview":[{"clip_id":"pc_00000000000000000000000000000063","title":"Waiting","summary":"","captured_at":"","source":"Fixture"}],"has_more_unclassified":false}}""",
        )

        assertEquals("custom", parsed.window.kind)
        assertEquals(5, parsed.window.days)
        assertEquals("2026-07-01", parsed.window.startDate)
        assertEquals("2026-07-05", parsed.window.endDate)
        assertEquals("Asia/Shanghai", parsed.window.timezone)
        assertEquals(1, parsed.unclassifiedPreview.size)
        assertEquals(0, parsed.topics.size)
    }

    @Test
    fun `parser keeps the selected knowledge base identity in the window`() {
        val parsed = MemoryPlanetJson.parse(
            """{"ok":true,"planet":{"contract_version":"perclip.memory-planet.v1","window":{"kind":"week","days":7,"start":"","end":"","knowledge_base_id":"kb-development-test"},"topics":[],"unclassified_count":0,"unclassified_preview":[],"has_more_unclassified":false}}""",
        )

        assertEquals("kb-development-test", parsed.window.knowledgeBaseId)
        assertTrue(parsed.window.matches(MemoryPlanetWindow(knowledgeBaseId = "kb-development-test")))
        assertFalse(parsed.window.matches(MemoryPlanetWindow(knowledgeBaseId = "kb-other")))
    }
}
