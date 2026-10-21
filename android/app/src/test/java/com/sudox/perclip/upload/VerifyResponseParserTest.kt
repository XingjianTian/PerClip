package com.sudox.perclip.upload

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VerifyResponseParserTest {
    @Test
    fun acceptsOkTrueVerifyResponse() {
        val result = VerifyResponseParser.parse("""{"ok": true, "auth": "mobile_ingest_token"}""")

        assertTrue(result.ok)
        assertEquals("连接测试", result.title)
        assertEquals("连接与 token 正常。", result.message)
    }

    @Test
    fun rejectsOkFalseVerifyResponse() {
        val result = VerifyResponseParser.parse("""{"ok": false, "detail": "token rejected"}""")

        assertFalse(result.ok)
        assertEquals("token rejected", result.message)
    }

    @Test
    fun rejectsMissingOkVerifyResponse() {
        val result = VerifyResponseParser.parse("""{"service": "perclip-ingest"}""")

        assertFalse(result.ok)
        assertEquals(VerifyResponseParser.INVALID_VERIFY_MESSAGE, result.message)
    }

    @Test
    fun rejectsStringOkVerifyResponse() {
        val result = VerifyResponseParser.parse("""{"ok": "true", "auth": "mobile_ingest_token"}""")

        assertFalse(result.ok)
        assertEquals(VerifyResponseParser.INVALID_VERIFY_MESSAGE, result.message)
    }
}
