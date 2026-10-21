package com.sudox.perclip.upload

import java.io.File
import java.io.InputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

object CachedPayloadWriter {
    fun copyToFile(input: InputStream, target: File): File {
        target.parentFile?.mkdirs()
        val targetExistedBeforeCopy = target.exists()
        val tempFile = File(target.parentFile, "${target.name}.tmp-${UUID.randomUUID()}")

        try {
            tempFile.outputStream().use { output -> input.copyTo(output) }
            moveIntoPlace(tempFile, target)
            return target
        } catch (throwable: Throwable) {
            tempFile.delete()
            if (!targetExistedBeforeCopy) {
                target.delete()
            }
            throw throwable
        }
    }

    private fun moveIntoPlace(source: File, target: File) {
        try {
            Files.move(
                source.toPath(),
                target.toPath(),
                StandardCopyOption.REPLACE_EXISTING,
                StandardCopyOption.ATOMIC_MOVE,
            )
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(
                source.toPath(),
                target.toPath(),
                StandardCopyOption.REPLACE_EXISTING,
            )
        }
    }
}
