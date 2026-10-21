package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipMetadata
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadMultipartKnowledgeBaseMetadataTest {
    @Test
    fun uploadFailureDoesNotExposeServerResponsePaths() {
        val client = OkHttpClient.Builder()
            .addInterceptor { chain ->
                Response.Builder()
                    .request(chain.request())
                    .protocol(Protocol.HTTP_1_1)
                    .code(422)
                    .message("Unprocessable")
                    .body(
                        """{"detail":"archive failed","original_path":"/Volumes/private/archive.md"}"""
                            .toResponseBody("application/json".toMediaType()),
                    )
                    .build()
            }
            .build()

        val result = PersonalClipsApi(client = client).upload(
            settings = settings(),
            clip = SharedClip(id = "clip-failed", kind = ClipKind.Text, titleHint = "failed", text = "body"),
            note = "",
            item = null,
            cachedFile = null,
            capturedAtEpochMs = 1_700_000_000_000L,
            capturedTimezone = "Asia/Shanghai",
        )

        assertFalse(result.ok)
        assertEquals("HTTP 422: 保存失败。", result.message)
        assertFalse(result.message.contains("original_path"))
        assertFalse(result.message.contains("/Volumes/"))
    }

    @Test
    fun uploadMultipartAddsTargetKnowledgeBaseIdWhenPresent() {
        val capturedParts = mutableMapOf<String, String>()
        val client = OkHttpClient.Builder()
            .addInterceptor(
                Interceptor { chain ->
                    val body = chain.request().body
                    if (body is MultipartBody) {
                        body.parts.forEach { part ->
                            val disposition = part.headers?.get("Content-Disposition").orEmpty()
                            val name = disposition.substringAfter("name=\"").substringBefore("\"")
                            val buffer = Buffer()
                            part.body.writeTo(buffer)
                            capturedParts[name] = buffer.readUtf8()
                        }
                    }
                    Response.Builder()
                        .request(chain.request())
                        .protocol(Protocol.HTTP_1_1)
                        .code(200)
                        .message("OK")
                        .body("""{"ok": true, "duplicate": false, "title": "ok"}""".toResponseBody("application/json".toMediaType()))
                        .build()
                },
            )
            .build()

        val result = PersonalClipsApi(client = client).upload(
            settings = PerClipSettings(
                apiUrl = "http://127.0.0.1:18080",
                ingestToken = "mobile-token",
                deviceName = "Android",
                wifiOnlyLargeFiles = true,
                persistentQuickEntry = false,
            ),
            clip = SharedClip(
                id = "clip-1",
                kind = ClipKind.Text,
                titleHint = "Note",
                text = "hello",
                sourceApp = "PerClipTest",
            ),
            note = "note",
            item = null,
            cachedFile = null,
            targetKnowledgeBaseId = "kb_target",
            capturedAtEpochMs = 1_700_000_000_000L,
            capturedTimezone = "Asia/Shanghai",
        )

        assertTrue(result.ok)
        assertTrue(capturedParts.containsKey("source_type"))
        assertTrue(capturedParts.containsKey("client_request_id"))
        assertEquals("kb_target", capturedParts["target_knowledge_base_id"])
        assertEquals("", capturedParts["client_batch_id"])
        assertEquals("clip-1:", capturedParts["parent_client_request_id"])
        assertEquals("0", capturedParts["client_part_index"])
        assertEquals("1", capturedParts["client_part_count"])
        assertEquals("text", capturedParts["part_role"])
        assertEquals("share", capturedParts["source_intent"])
        assertEquals("2023-11-14T22:13:20Z", capturedParts["captured_at"])
        assertEquals("Asia/Shanghai", capturedParts["captured_timezone"])
        assertFalse(capturedParts.containsKey("knowledgeBaseId"))
        assertFalse(capturedParts.containsKey("knowledgeBaseName"))
        assertFalse(capturedParts.containsKey("routingReason"))
        assertFalse(capturedParts.containsKey("matchedRuleIds"))
        assertFalse(capturedParts.containsKey("ragflow_dataset_id"))
        assertFalse(capturedParts.containsKey("original_path"))
        assertFalse(capturedParts.containsKey("storage_uri"))
        assertFalse(capturedParts.containsKey("ragflow_document_id"))
        assertFalse(capturedParts.containsKey("Authorization"))
        assertFalse(capturedParts.values.joinToString("\n").contains("change-me-server-side-ragflow-key"))
        assertFalse(capturedParts.values.joinToString("\n").contains("change-me-baidu-api-key"))
        assertFalse(capturedParts.values.joinToString("\n").contains("nas-password"))
        assertFalse(capturedParts.values.joinToString("\n").contains("ssh-password"))
        assertFalse(capturedParts.values.joinToString("\n").contains("cloud-secret"))
        assertFalse(capturedParts.values.joinToString("\n").contains("social-secret"))
    }

    @Test
    fun uploadMultipartOmitsTargetKnowledgeBaseIdWhenBlank() {
        val capturedPartNames = mutableListOf<String>()
        val client = OkHttpClient.Builder()
            .addInterceptor(
                Interceptor { chain ->
                    val body = chain.request().body
                    if (body is MultipartBody) {
                        body.parts.forEach { part ->
                            val disposition = part.headers?.get("Content-Disposition").orEmpty()
                            capturedPartNames.add(disposition.substringAfter("name=\"").substringBefore("\""))
                        }
                    }
                    Response.Builder()
                        .request(chain.request())
                        .protocol(Protocol.HTTP_1_1)
                        .code(200)
                        .message("OK")
                        .body("""{"ok": true, "duplicate": false, "title": "ok"}""".toResponseBody("application/json".toMediaType()))
                        .build()
                },
            )
            .build()

        val result = PersonalClipsApi(client = client).upload(
            settings = PerClipSettings(
                apiUrl = "http://127.0.0.1:18080",
                ingestToken = "mobile-token",
                deviceName = "Android",
                wifiOnlyLargeFiles = true,
                persistentQuickEntry = false,
            ),
            clip = SharedClip(
                id = "clip-1",
                kind = ClipKind.Text,
                titleHint = "Note",
                text = "hello",
                sourceApp = "PerClipTest",
            ),
            note = "note",
            item = null,
            cachedFile = null,
            capturedAtEpochMs = 1_700_000_000_000L,
            capturedTimezone = "Asia/Shanghai",
        )

        assertTrue(result.ok)
        assertTrue(capturedPartNames.contains("source_type"))
        assertTrue(capturedPartNames.contains("client_request_id"))
        assertFalse(capturedPartNames.contains("target_knowledge_base_id"))
    }

    @Test
    fun defaultOnlyMultipartSendsModeAndCaptureTimeDefaultId() {
        val capturedParts = mutableMapOf<String, String>()
        val client = OkHttpClient.Builder()
            .addInterceptor { chain ->
                (chain.request().body as? MultipartBody)?.parts?.forEach { part ->
                    val disposition = part.headers?.get("Content-Disposition").orEmpty()
                    val name = disposition.substringAfter("name=\"").substringBefore("\"")
                    val buffer = Buffer()
                    part.body.writeTo(buffer)
                    capturedParts[name] = buffer.readUtf8()
                }
                Response.Builder()
                    .request(chain.request())
                    .protocol(Protocol.HTTP_1_1)
                    .code(200)
                    .message("OK")
                    .body("""{"ok": true, "duplicate": false, "title": "ok"}""".toResponseBody("application/json".toMediaType()))
                    .build()
            }
            .build()

        val result = PersonalClipsApi(client = client).upload(
            settings = settings(),
            clip = SharedClip(id = "clip-default", kind = ClipKind.Text, titleHint = "Note", text = "hello"),
            note = "",
            item = null,
            cachedFile = null,
            targetKnowledgeBaseId = "cached-default-id",
            routingMode = "default_only",
            capturedAtEpochMs = 1_700_000_000_000L,
            capturedTimezone = "Asia/Shanghai",
        )

        assertTrue(result.ok)
        assertEquals("default_only", capturedParts["routing_mode"])
        assertEquals("cached-default-id", capturedParts["target_knowledge_base_id"])
    }

    @Test
    fun uploadWorkerReadsTargetKnowledgeBaseIdFromQueuedClipMetadata() {
        val queuedClip = QueuedClip(
            id = "clip-1",
            kind = ClipKind.Text,
            titleHint = "Note",
            text = "hello",
            url = "",
            mimeType = "text/plain",
            sourceApp = "PerClipTest",
            note = "",
            items = emptyList(),
            status = UploadStatus.Waiting,
            message = "等待后台同步",
            remotePath = "",
            createdAtEpochMs = 1L,
            metadata = QueuedClipMetadata(
                knowledgeBaseId = "  kb_from_queue  ",
                knowledgeBaseName = "Display only",
                routingReason = "Display only",
                matchedRuleIds = listOf("rule-display"),
            ),
        )

        assertEquals("kb_from_queue", UploadWorkerKnowledgeBaseTarget.fromQueuedClip(queuedClip))
    }

    private fun settings() = PerClipSettings(
        apiUrl = "http://127.0.0.1:18080",
        ingestToken = "mobile-token",
        deviceName = "Android",
        wifiOnlyLargeFiles = true,
        persistentQuickEntry = false,
    )
}
