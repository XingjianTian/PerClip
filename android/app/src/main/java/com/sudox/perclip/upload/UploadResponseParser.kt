package com.sudox.perclip.upload

import org.json.JSONObject

object UploadResponseParser {
    const val INVALID_RESPONSE_MESSAGE = "服务响应格式无效。"
    const val UNCONFIRMED_RESPONSE_MESSAGE = "服务端未确认保存。"

    fun parseSuccessfulUpload(bodyText: String, fallbackTitle: String): UploadResult {
        val json = JSONObject(bodyText)
        if (!json.has("ok")) {
            return failed(fallbackTitle, INVALID_RESPONSE_MESSAGE)
        }
        if (json.get("ok") !is Boolean) {
            return failed(fallbackTitle, INVALID_RESPONSE_MESSAGE)
        }
        if (!json.getBoolean("ok")) {
            return failed(
                title = json.optString("title", fallbackTitle),
                message = UNCONFIRMED_RESPONSE_MESSAGE,
            )
        }
        if (json.has("duplicate") && json.get("duplicate") !is Boolean) {
            return failed(fallbackTitle, INVALID_RESPONSE_MESSAGE)
        }
        val duplicate = json.optBoolean("duplicate", false)
        return UploadResult(
            ok = true,
            duplicate = duplicate,
            title = json.optString("title", fallbackTitle),
            originalPath = "",
            ragflowDocumentId = json.optString("ragflow_document_id"),
            message = if (duplicate) "已存在，未重复保存。" else "已保存，后台处理已开始。",
            archiveStatus = json.optString("archive_status"),
        )
    }

    private fun failed(title: String, message: String): UploadResult {
        return UploadResult(
            ok = false,
            title = title,
            originalPath = "",
            ragflowDocumentId = "",
            duplicate = false,
            message = message,
        )
    }
}
