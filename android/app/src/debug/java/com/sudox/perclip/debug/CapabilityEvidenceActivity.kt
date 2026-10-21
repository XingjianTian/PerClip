package com.sudox.perclip.debug

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sudox.perclip.capabilities.AppCapabilitiesApi
import com.sudox.perclip.capabilities.AppFeatureAvailability
import com.sudox.perclip.capabilities.featureAvailability
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.design.PerClipTheme
import com.sudox.perclip.knowledge.KnowledgeOperationPolicy
import com.sudox.perclip.ui.ConnectionVerificationPolicy
import com.sudox.perclip.upload.PersonalClipsApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Debug-only USB evidence against a loopback fake; never reads or changes saved app configuration. */
class CapabilityEvidenceActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val mode = intent.getStringExtra("mode") ?: "partial"
        val port = if (mode == "old") 18083 else 18082
        setContent {
            PerClipTheme {
                var lines by remember { mutableStateOf(listOf("正在读取本地 USB fake…")) }
                LaunchedEffect(mode) {
                    val settings = PerClipSettings("http://127.0.0.1:$port", "test-token", "USB fake", true, false)
                    val (health, capability) = withContext(Dispatchers.IO) {
                        PersonalClipsApi().health(settings) to AppCapabilitiesApi().fetch(settings)
                    }
                    val connection = ConnectionVerificationPolicy.evaluate(health.ok, capability)
                    lines = listOf(
                        "模式：$mode",
                        "基础保存：${if (health.ok) "可用" else "不可用"}",
                        "Knowledge：${capability.featureAvailability { it.knowledgeBases }}",
                        "Recall：${capability.featureAvailability { it.recall }}",
                        "完整：${capability.complete}",
                        "重新入队策略：${connection.shouldRequeue}",
                        "浏览：${KnowledgeOperationPolicy.canBrowse(capability)}",
                        "CRUD：${KnowledgeOperationPolicy.canCrud(capability)}",
                    )
                }
                Column(Modifier.fillMaxSize().padding(28.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Stage 20.6 capability USB evidence", style = MaterialTheme.typography.headlineSmall)
                    lines.forEach { Text(it) }
                }
            }
        }
    }
}
