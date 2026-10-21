package com.sudox.perclip.upload

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadResponseParserTest {
    @Test
    fun parsesConfirmedUploadResponse() {
        val result = UploadResponseParser.parseSuccessfulUpload(
            bodyText = """
                {
                  "ok": true,
                  "duplicate": false,
                  "title": "来自安卓",
                  "original_path": "/clips/demo.md",
                  "ragflow_document_id": "doc-1",
                  "archive_status": "clip_to_ragflow"
                }
            """.trimIndent(),
            fallbackTitle = "fallback",
        )

        assertTrue(result.ok)
        assertFalse(result.duplicate)
        assertEquals("来自安卓", result.title)
        assertEquals("", result.originalPath)
        assertEquals("doc-1", result.ragflowDocumentId)
        assertEquals("clip_to_ragflow", result.archiveStatus)
        assertEquals("已保存，后台处理已开始。", result.message)
    }

    @Test
    fun parsesDuplicateUploadResponse() {
        val result = UploadResponseParser.parseSuccessfulUpload(
            bodyText = """{"ok": true, "duplicate": true, "title": "旧记录"}""",
            fallbackTitle = "fallback",
        )

        assertTrue(result.ok)
        assertTrue(result.duplicate)
        assertEquals("旧记录", result.title)
        assertEquals("已存在，未重复保存。", result.message)
    }

    @Test
    fun treatsMissingDuplicateAsFreshUpload() {
        val result = UploadResponseParser.parseSuccessfulUpload(
            bodyText = """{"ok": true, "title": "新记录"}""",
            fallbackTitle = "fallback",
        )

        assertTrue(result.ok)
        assertFalse(result.duplicate)
        assertEquals("已保存，后台处理已开始。", result.message)
    }

    @Test
    fun treatsOkFalseAsUnconfirmedFailure() {
        val result = UploadResponseParser.parseSuccessfulUpload(
            bodyText = """{"ok": false, "detail": "original_path /Volumes/private/archive.md", "title": "失败记录"}""",
            fallbackTitle = "fallback",
        )

        assertFalse(result.ok)
        assertEquals("失败记录", result.title)
        assertEquals(UploadResponseParser.UNCONFIRMED_RESPONSE_MESSAGE, result.message)
        assertFalse(result.message.contains("original_path"))
        assertFalse(result.message.contains("/Volumes/"))
    }

    @Test
    fun treatsMissingOkAsMalformedSuccess() {
        val result = UploadResponseParser.parseSuccessfulUpload(
            bodyText = """{"title": "missing ok"}""",
            fallbackTitle = "fallback",
        )

        assertFalse(result.ok)
        assertEquals("fallback", result.title)
        assertEquals(UploadResponseParser.INVALID_RESPONSE_MESSAGE, result.message)
    }

    @Test
    fun treatsStringOkAsMalformedSuccess() {
        val result = UploadResponseParser.parseSuccessfulUpload(
            bodyText = """{"ok": "true", "title": "string ok"}""",
            fallbackTitle = "fallback",
        )

        assertFalse(result.ok)
        assertEquals("fallback", result.title)
        assertEquals(UploadResponseParser.INVALID_RESPONSE_MESSAGE, result.message)
    }

    @Test
    fun treatsStringDuplicateAsMalformedSuccess() {
        val result = UploadResponseParser.parseSuccessfulUpload(
            bodyText = """{"ok": true, "duplicate": "true", "title": "string duplicate"}""",
            fallbackTitle = "fallback",
        )

        assertFalse(result.ok)
        assertEquals("fallback", result.title)
        assertEquals(UploadResponseParser.INVALID_RESPONSE_MESSAGE, result.message)
    }
}
