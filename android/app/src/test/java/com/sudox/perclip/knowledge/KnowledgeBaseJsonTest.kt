package com.sudox.perclip.knowledge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeBaseJsonTest {
    @Test
    fun parsesKnowledgeBaseListResponse() {
        val parsed = KnowledgeBaseJson.parseList(
            """
            {
              "ok": true,
              "knowledge_bases": [
                {
                  "id": "kb_default",
                  "name": "个人收藏",
                  "description": "默认知识库",
                  "icon": "inbox",
                  "color": "yellow",
                  "is_default": true,
                  "is_archived": false,
                  "ragflow_dataset_id": "dataset-123456",
                  "ragflow_dataset_name": "Personal",
                  "template_key": "general",
                  "top_topics": [
                    {"id": "topic:ai", "label": "AI 工具", "clip_count": 7},
                    {"id": "topic:android", "label": "Android", "clip_count": 5}
                  ],
                  "created_at": "2026-07-09T00:00:00Z",
                  "updated_at": "2026-07-09T00:00:00Z",
                  "deleted_at": ""
                }
              ]
            }
            """.trimIndent(),
        )

        assertTrue(parsed.ok)
        assertEquals("kb_default", parsed.knowledgeBases.single().id)
        assertEquals("个人收藏", parsed.knowledgeBases.single().name)
        assertTrue(parsed.knowledgeBases.single().isDefault)
        assertEquals("dataset-", parsed.knowledgeBases.single().ragflowShortId)
        assertEquals(listOf("AI 工具", "Android"), parsed.knowledgeBases.single().topTopics.map { it.label })
        assertEquals(7, parsed.knowledgeBases.single().topTopics.first().clipCount)
    }

    @Test
    fun parsesKnowledgeBaseMutationResponse() {
        val parsed = KnowledgeBaseJson.parseMutation(
            """
            {
              "ok": true,
              "ragflow_dataset_deleted": false,
              "knowledge_base": {
                "id": "kb_1",
                "name": "Research",
                "description": "Papers",
                "is_default": false,
                "is_archived": false,
                "template_key": "research_papers"
              }
            }
            """.trimIndent(),
        )

        assertTrue(parsed.ok)
        assertFalse(parsed.ragflowDatasetDeleted)
        assertEquals("Research", parsed.knowledgeBase.name)
        assertEquals("research_papers", parsed.knowledgeBase.templateKey)
    }

    @Test
    fun parsesRagflowCapabilityWithoutSecrets() {
        val parsed = KnowledgeBaseJson.parseRagflowCapabilities(
            """
            {
              "ok": true,
              "ragflow": {
                "adapter_status": "http_skeleton",
                "configured": true,
                "capabilities": {
                  "dataset_list": "unknown",
                  "document_upload": "unknown"
                },
                "notes": ["server-side only"]
              }
            }
            """.trimIndent(),
        )

        assertEquals("http_skeleton", parsed.adapterStatus)
        assertTrue(parsed.configured)
        assertEquals("unknown", parsed.capabilities["dataset_list"])
        assertFalse(parsed.toString().contains("ragflow-api-key"))
    }

    @Test
    fun parsesReadOnlyRagflowProbeWithoutInfrastructureDetails() {
        val parsed = KnowledgeBaseJson.parseRagflowProbe(
            """
            {
              "ok": true,
              "configured": true,
              "status": "reachable",
              "capabilities": {"dataset_list": true},
              "warnings": [],
              "latency_ms": 42
            }
            """.trimIndent(),
        )

        assertTrue(parsed.configured)
        assertEquals("reachable", parsed.status)
        assertEquals("true", parsed.capabilities["dataset_list"])
        assertEquals(42L, parsed.latencyMs)
    }

    @Test
    fun mapsHttpErrorsToUiMessages() {
        assertTrue(KnowledgeBaseApiError.http(401, """{"detail": "invalid mobile ingest token"}""").contains("认证失败"))
        assertTrue(KnowledgeBaseApiError.http(404, """{"detail": "knowledge base not found"}""").contains("没有找到"))
        assertTrue(KnowledgeBaseApiError.http(409, """{"detail": "knowledge base is archived"}""").contains("操作冲突"))
        assertTrue(KnowledgeBaseApiError.http(422, """{"detail": "name is required"}""").contains("请求参数无效"))
    }

    @Test
    fun htmlHttpErrorsDoNotExposeTheUpstreamResponseBody() {
        val html = """
            <html>
              <head><title>HTTP 404</title></head>
              <body>internal reverse proxy error page</body>
            </html>
        """.trimIndent()

        val message = KnowledgeBaseApiError.http(404, html)

        assertTrue(message.contains("没有找到"))
        assertFalse(message.contains("<html>"))
        assertFalse(message.contains("reverse proxy"))
    }

    @Test
    fun androidModelsDoNotExposeServerSecretFields() {
        val modelText = listOf(
            KnowledgeBaseSummary(id = "kb", name = "name").toString(),
            RagflowCapabilitySummary(
                adapterStatus = "disabled",
                configured = false,
                capabilities = mapOf("dataset_list" to "not_configured"),
            ).toString(),
        ).joinToString("\n")

        listOf("ragflowApiKey", "asrKey", "nasPassword", "sshPassword", "cloudSecret", "socialSecret").forEach {
            assertFalse(modelText.contains(it))
        }
    }
}
