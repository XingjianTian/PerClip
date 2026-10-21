package com.sudox.perclip.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.LocalContext
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppFeatureAvailability
import com.sudox.perclip.capabilities.capabilityConfigurationFingerprint
import com.sudox.perclip.capabilities.featureAvailability
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.ui.SettingsPresentation
import com.sudox.perclip.ui.recall.RecallDisplayPreferenceStore
import com.sudox.perclip.ui.recall.RecallDisplaySettingsContent
import com.sudox.perclip.ui.recall.RecallController
import com.sudox.perclip.ui.recall.RecallDomainLoader
import com.sudox.perclip.ui.recall.RecallPeriod
import com.sudox.perclip.ui.recall.RecallStateHolder
import com.sudox.perclip.ui.recall.RecallUiReducer
import com.sudox.perclip.recall.repository.RecallDomainRequest
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.PersonalClipsApi
import com.sudox.perclip.upload.UploadResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.launch

/** Route owner only; credentials are passed exclusively to the connection page. */
@Composable
fun SettingsScreen(
    contentPadding: PaddingValues,
    settings: PerClipSettings,
    recentRecords: List<UploadRecord>,
    recallStateHolder: RecallStateHolder,
    onRequestNotificationPermission: () -> Unit,
    onConnectionVerified: () -> Int,
    onSettingsChange: (PerClipSettings) -> Unit,
    onOpenKnowledgeRecords: () -> Unit,
    appCapabilityResult: AppCapabilityResult? = null,
    appCapabilityLoading: Boolean = false,
    knowledgeBases: List<KnowledgeBaseSummary> = emptyList(),
    onKnowledgeBasesLoaded: (List<KnowledgeBaseSummary>) -> Unit = {},
    onRequestCapabilityRefresh: () -> Unit = {},
    initialDestination: SettingsDestination = SettingsDestination.Home,
    stateHolder: SettingsStateHolder? = null,
    verifyConnection: suspend (PerClipSettings) -> UploadResult = { PersonalClipsApi().health(it) },
    recallDomainLoaderOverride: RecallDomainLoader? = null,
) {
    val context = LocalContext.current
    val routeHolder = stateHolder ?: remember(initialDestination) { SettingsStateHolder(initialDestination) }
    val scope = rememberCoroutineScope()
    val recallController = remember { RecallController() }
    val rememberedRecallDomainLoader = remember(recallController) { RecallDomainLoader(recallController::domain) }
    val recallDomainLoader = recallDomainLoaderOverride ?: rememberedRecallDomainLoader
    val recallAvailability = appCapabilityResult.featureAvailability { it.recallDomain }
    val recallConfigurationFingerprint = remember(settings.apiUrl, settings.ingestToken) {
        capabilityConfigurationFingerprint(settings)
    }
    val destination = routeHolder.destination
    val dashboard = SettingsPresentation.dashboard(settings, appCapabilityResult, recentRecords)
    fun back() { routeHolder.back() }
    fun updateSettings(updated: PerClipSettings) {
        onSettingsChange(updated)
        recallStateHolder.update { state ->
            state.copy(presentation = state.presentation.copy(
                period = if (updated.recallPeriodDays == 30) RecallPeriod.MONTHLY else RecallPeriod.WEEKLY,
                autoSurfaceEnabled = true,
                graphExpanded = updated.recallGraphExpanded,
                reducedMotion = updated.reduceMotion,
            ))
        }
    }

    LaunchedEffect(recallStateHolder) {
        recallStateHolder.applyDisplayPreferencesOnce(RecallDisplayPreferenceStore.load(context))
    }
    LaunchedEffect(settings.recallPeriodDays, settings.recallGraphExpanded, settings.reduceMotion) {
        recallStateHolder.update { state ->
            state.copy(presentation = state.presentation.copy(
                period = if (settings.recallPeriodDays == 30) RecallPeriod.MONTHLY else RecallPeriod.WEEKLY,
                autoSurfaceEnabled = true,
                graphExpanded = settings.recallGraphExpanded,
                reducedMotion = settings.reduceMotion,
            ))
        }
    }
    LaunchedEffect(destination, recallConfigurationFingerprint, recallAvailability) {
        if (destination != SettingsDestination.RecallDisplayManagement) return@LaunchedEffect
        recallStateHolder.prepareOverviewForConfiguration("$recallConfigurationFingerprint|$recallAvailability")
        when (recallAvailability) {
            AppFeatureAvailability.CHECKING -> recallStateHolder.update { current ->
                current.copy(domain = current.domain.copy(loading = true, error = ""))
            }
            AppFeatureAvailability.UNAVAILABLE -> recallStateHolder.update { current ->
                RecallUiReducer.domainFailed(
                    current,
                    appCapabilityResult?.message.orEmpty().ifBlank { "当前服务未提供记忆星球数据。" },
                )
            }
            AppFeatureAvailability.AVAILABLE -> if (recallStateHolder.state.domain.value == null) {
                recallDomainLoader.load(
                    recallStateHolder,
                    settings,
                    RecallDomainRequest(days = recallStateHolder.state.presentation.period.days ?: 7, topicLimit = 5, memoryLimit = 80),
                )
            }
        }
    }
    BackHandler(enabled = destination != SettingsDestination.Home) { back() }

    when (val current = destination) {
        SettingsDestination.Home -> SettingsHomeScreen(
            contentPadding,
            dashboard,
            settings.reduceMotion,
            settings.themeMode,
            onReduceMotionChanged = { updateSettings(settings.copy(reduceMotion = it)) },
            onOpen = { routeHolder.navigate(it) },
        )
        SettingsDestination.Connection -> ServerSettingsScreen(
            contentPadding = contentPadding,
            settings = settings,
            capabilityResult = appCapabilityResult,
            capabilityLoading = appCapabilityLoading,
            onSettingsChange = ::updateSettings,
            onConnectionVerified = onConnectionVerified,
            onRequestCapabilityRefresh = onRequestCapabilityRefresh,
            onBack = ::back,
            verifyConnection = verifyConnection,
        )
        SettingsDestination.CaptureAndIngest -> CaptureAndIngestSettingsScreen(
            contentPadding, settings, dashboard, onRequestNotificationPermission, ::updateSettings, onOpenKnowledgeRecords, ::back,
        )
        SettingsDestination.Appearance -> AppearanceSettingsScreen(
            contentPadding = contentPadding,
            selectedMode = settings.themeMode,
            onModeSelected = { updateSettings(settings.copy(themeMode = it)) },
            onBack = ::back,
        )
        SettingsDestination.KnowledgeManagement -> KnowledgeBaseManagementScreen(
            contentPadding = contentPadding,
            settings = settings,
            appCapabilityResult = appCapabilityResult,
            onKnowledgeBasesLoaded = onKnowledgeBasesLoaded,
            onBack = ::back,
        )
        SettingsDestination.RecallDisplayManagement -> RecallDisplaySettingsContent(
            state = recallStateHolder.state,
            padding = contentPadding,
            onBack = ::back,
            onVisibleTopicCount = { count ->
                recallStateHolder.update { RecallUiReducer.setVisibleTopicCount(it, count) }
                RecallDisplayPreferenceStore.save(context, recallStateHolder.state.presentation)
            },
            onVisibleMemoryLabels = { count ->
                recallStateHolder.update { RecallUiReducer.setVisibleMemoryLabels(it, count) }
                RecallDisplayPreferenceStore.save(context, recallStateHolder.state.presentation)
            },
            onTopicVisible = { topicId, visible ->
                recallStateHolder.update { RecallUiReducer.setTopicVisible(it, topicId, visible) }
                RecallDisplayPreferenceStore.save(context, recallStateHolder.state.presentation)
            },
            onRestoreDefaults = {
                recallStateHolder.update(RecallUiReducer::restoreDisplayDefaults)
                RecallDisplayPreferenceStore.save(context, recallStateHolder.state.presentation)
            },
            featureAvailability = recallAvailability,
            unavailableMessage = appCapabilityResult?.message.orEmpty(),
            onRetry = {
                if (recallAvailability == AppFeatureAvailability.AVAILABLE) {
                    scope.launch {
                        recallDomainLoader.load(
                            recallStateHolder,
                            settings,
                            RecallDomainRequest(days = recallStateHolder.state.presentation.period.days ?: 7, topicLimit = 5, memoryLimit = 80),
                        )
                    }
                } else {
                    recallStateHolder.update { current -> current.copy(domain = current.domain.copy(loading = true, error = "")) }
                    onRequestCapabilityRefresh()
                }
            },
        )
    }
}
