package com.sudox.perclip

import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidNoServerSecretsTest {
    @Test
    fun androidSourceDoesNotEmbedServerSideRagflowSecretsOrPlaceholders() {
        val forbiddenMatches = mutableListOf<String>()

        Files.walk(Paths.get("src/main")).use { paths ->
            paths.filter(Files::isRegularFile).forEach { path ->
                val text = path.readText()
                FORBIDDEN_SERVER_SIDE_MARKERS.forEach { marker ->
                    if (text.contains(marker)) {
                        forbiddenMatches += "${path.invariantPath()}: $marker"
                    }
                }
            }
        }

        assertTrue(
            "Android source must not contain server-side RAGFlow secret markers: $forbiddenMatches",
            forbiddenMatches.isEmpty(),
        )
    }

    private fun Path.readText(): String {
        return Files.readAllBytes(this).toString(Charsets.UTF_8)
    }

    private fun Path.invariantPath(): String {
        return toString().replace('\\', '/')
    }

    companion object {
        private val FORBIDDEN_SERVER_SIDE_MARKERS = listOf(
            "RAGFLOW_API_KEY",
            "PERSONAL_CLIPS_DATASET_ID",
            "RAGFLOW_DATASET_ID",
            "change-me-server-side-ragflow-key",
            "change-me-dataset-id",
            "http://ragflow.internal:18080",
        )
    }
}
