package com.sudox.perclip.upload

data class UploadFailureDisposition(
    val status: UploadStatus,
    val message: String,
    val shouldRetry: Boolean,
    val shouldNotifyFailure: Boolean,
)

object UploadAttemptPolicy {
    const val WAITING_RETRY_SUFFIX = "等待自动重试。"

    fun forFailure(
        result: UploadResult,
        runAttemptCount: Int,
        maxRetryAttempts: Int,
    ): UploadFailureDisposition {
        val shouldRetry = result.retryable && runAttemptCount < maxRetryAttempts
        return if (shouldRetry) {
            UploadFailureDisposition(
                status = UploadStatus.Waiting,
                message = retryMessage(result.message),
                shouldRetry = true,
                shouldNotifyFailure = false,
            )
        } else {
            UploadFailureDisposition(
                status = UploadStatus.Failed,
                message = result.message,
                shouldRetry = false,
                shouldNotifyFailure = true,
            )
        }
    }

    private fun retryMessage(message: String): String {
        return message.ifBlank { "后台同步暂时失败" } + "，$WAITING_RETRY_SUFFIX"
    }
}
