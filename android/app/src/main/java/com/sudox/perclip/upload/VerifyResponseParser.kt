package com.sudox.perclip.upload

import org.json.JSONObject

object VerifyResponseParser {
    const val INVALID_VERIFY_MESSAGE = "服务验证响应格式无效。"
    const val VERIFY_REJECTED_MESSAGE = "服务端未确认连接令牌。"

    fun parse(bodyText: String): UploadResult {
        val json = JSONObject(bodyText)
        if (!json.has("ok")) {
            return result(ok = false, message = INVALID_VERIFY_MESSAGE)
        }
        if (json.get("ok") !is Boolean) {
            return result(ok = false, message = INVALID_VERIFY_MESSAGE)
        }
        if (!json.getBoolean("ok")) {
            return result(
                ok = false,
                message = json.optString("detail")
                    .ifBlank { json.optString("message") }
                    .ifBlank { VERIFY_REJECTED_MESSAGE },
            )
        }
        return result(ok = true, message = "连接与 token 正常。")
    }

    private fun result(ok: Boolean, message: String): UploadResult {
        return UploadResult(
            ok = ok,
            title = "连接测试",
            originalPath = "",
            ragflowDocumentId = "",
            duplicate = false,
            message = message,
        )
    }
}
