package com.sudox.perclip.ui

import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.LibraryBooks
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import com.sudox.perclip.SharedClip
import com.sudox.perclip.LaunchNavigationPolicy
import com.sudox.perclip.StartTab
import com.sudox.perclip.capabilities.AppCapabilitiesApi
import com.sudox.perclip.capabilities.AppCapabilityCoordinator
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppFeatureAvailability
import com.sudox.perclip.capabilities.featureAvailability
import com.sudox.perclip.capabilities.capabilityConfigurationFingerprint
import com.sudox.perclip.capture.CaptureSaveController
import com.sudox.perclip.capture.CaptureOrigin
import com.sudox.perclip.capture.CaptureSaveRequest
import com.sudox.perclip.config.PerClipSettingsStore
import com.sudox.perclip.config.AppThemeMode
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.design.perClipAccentColor
import com.sudox.perclip.design.perClipIsDarkTheme
import com.sudox.perclip.knowledge.KnowledgeBaseApi
import com.sudox.perclip.knowledge.KnowledgeBaseCacheScope
import com.sudox.perclip.knowledge.KnowledgeBaseLocalCache
import com.sudox.perclip.knowledge.ClipSyncStatusLocalMetadataUpdater
import com.sudox.perclip.knowledge.ClipProcessingStatusRefresh
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.knowledge.KnowledgeBaseRemoteListState
import com.sudox.perclip.knowledge.KnowledgeLibraryScope
import com.sudox.perclip.knowledge.KnowledgeBaseLoadPolicy
import com.sudox.perclip.notifications.QuickEntryNotificationHelper
import com.sudox.perclip.ui.screens.KnowledgeHomeScreen
import com.sudox.perclip.ui.screens.KnowledgeBaseManagementScreen
import com.sudox.perclip.ui.screens.FlashNoteUiLogic
import com.sudox.perclip.ui.screens.SettingsScreen
import com.sudox.perclip.ui.screens.SettingsStateHolder
import com.sudox.perclip.ui.screens.FlashNoteScreen
import com.sudox.perclip.ui.recall.RecallScreen
import com.sudox.perclip.ui.recall.RecallController
import com.sudox.perclip.ui.recall.RecallDomainLoader
import com.sudox.perclip.ui.recall.RecallStateHolder
import com.sudox.perclip.ui.recall.RecallStateHolderSaver
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadQueue
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun PerClipApp(
    startTab: StartTab,
    navigationRevision: Int,
    onRequestNotificationPermission: () -> Unit,
    onThemeModeChanged: (AppThemeMode) -> Unit = {},
) {
    val context = LocalContext.current
    val darkTheme = perClipIsDarkTheme()
    val settingsStore = remember { PerClipSettingsStore(context) }
    val quickEntryNotification = remember { QuickEntryNotificationHelper(context) }
    val uploadQueue = remember { UploadQueue(context) }
    val captureSaveController = remember { CaptureSaveController(context, uploadQueue) }
    val knowledgeBaseApi = remember { KnowledgeBaseApi() }
    val appCapabilitiesApi = remember { AppCapabilitiesApi() }
    var selectedTab by rememberSaveable { mutableIntStateOf(StartTab.Save.index) }
    var appliedNavigationRevision by rememberSaveable { mutableIntStateOf(0) }
    var activeClip by remember { mutableStateOf<SharedClip?>(null) }
    var flashQuickText by rememberSaveable { mutableStateOf("") }
    var flashSaving by remember { mutableStateOf(false) }
    var settings by remember { mutableStateOf(settingsStore.load()) }
    val knowledgeBaseCache = remember(settings.apiUrl, settings.ingestToken) {
        KnowledgeBaseLocalCache(context, KnowledgeBaseCacheScope.fromSettings(settings))
    }
    var uploadMessage by remember { mutableStateOf("") }
    var knowledgeBaseListMessage by remember { mutableStateOf("") }
    var processingMessage by remember { mutableStateOf("") }
    var processingStatusRefreshingClipId by remember { mutableStateOf<String?>(null) }
    var knowledgeBasesLoading by remember { mutableStateOf(false) }
    var knowledgeBaseRemoteListState by remember { mutableStateOf(KnowledgeBaseRemoteListState.NOT_LOADED) }
    var knowledgeBasesLoadedForFingerprint by remember { mutableStateOf("") }
    var appCapabilityResult by remember { mutableStateOf<AppCapabilityResult?>(null) }
    var appCapabilityLoading by remember { mutableStateOf(false) }
    val appCapabilityCoordinator = remember { AppCapabilityCoordinator() }
    var recentlySavedClipId by remember { mutableStateOf<String?>(null) }
    var requestedDetailClipId by remember { mutableStateOf<String?>(null) }
    var selectedKnowledgeScopeKind by rememberSaveable { mutableStateOf("all") }
    var selectedKnowledgeScopeId by rememberSaveable { mutableStateOf("") }
    val selectedKnowledgeScope: KnowledgeLibraryScope = when (selectedKnowledgeScopeKind) {
        "specific" -> KnowledgeLibraryScope.Specific(selectedKnowledgeScopeId)
        "unassigned" -> KnowledgeLibraryScope.Unassigned
        else -> KnowledgeLibraryScope.All
    }
    var knowledgeManagementOpen by remember { mutableStateOf(false) }
    var openDefaultPickerOnManagement by remember { mutableStateOf(false) }
    var returnToFlashAfterManagement by remember { mutableStateOf(false) }
    var knowledgeDetailOpen by rememberSaveable { mutableStateOf(false) }
    var uploadCompletionTrackerState by remember { mutableStateOf(UploadCompletionToastPolicy.State()) }
    var uploadCompletionRevision by remember { mutableIntStateOf(0) }
    val recallStateHolder = rememberSaveable(saver = RecallStateHolderSaver) { RecallStateHolder() }
    val recallController = remember { RecallController() }
    val recallDomainLoader = remember(recallController) { RecallDomainLoader(recallController::domain) }
    val settingsStateHolder = remember { SettingsStateHolder() }
    val recentRecords = remember { mutableStateListOf<UploadRecord>() }
    val knowledgeBases = remember { mutableStateListOf<KnowledgeBaseSummary>() }
    val scope = rememberCoroutineScope()

    fun closeKnowledgeManagement() {
        knowledgeManagementOpen = false
        if (returnToFlashAfterManagement) selectedTab = StartTab.Save.index
        returnToFlashAfterManagement = false
    }

    fun openSettingsHome() {
        knowledgeManagementOpen = false
        settingsStateHolder.showHome()
        selectedTab = StartTab.Settings.index
    }

    BackHandler(enabled = knowledgeManagementOpen) { closeKnowledgeManagement() }

    fun requestCapabilities(force: Boolean = false) {
        val snapshot = settings
        val request = appCapabilityCoordinator.begin(snapshot, force)
        appCapabilityResult = appCapabilityCoordinator.state.result
        appCapabilityLoading = appCapabilityCoordinator.state.loading
        if (request == null) return
        scope.launch {
            val result = withContext(Dispatchers.IO) { appCapabilitiesApi.fetch(snapshot) }
            if (appCapabilityCoordinator.accept(request, result)) {
                appCapabilityResult = result
                appCapabilityLoading = false
            }
        }
    }

    fun refreshRecentRecords() {
        recentRecords.clear()
        recentRecords.addAll(uploadQueue.recent())
    }

    fun refreshKnowledgeBases() {
        val normalizedSettings = settings.normalized()
        if (!normalizedSettings.hasUploadConfig) {
            knowledgeBaseListMessage = "请先完成连接设置。"
            knowledgeBaseRemoteListState = KnowledgeBaseRemoteListState.NOT_LOADED
            return
        }
        if (appCapabilityResult.featureAvailability { it.knowledgeBases } != AppFeatureAvailability.AVAILABLE) {
            knowledgeBaseListMessage = appCapabilityResult?.message.orEmpty().ifBlank { "正在检查服务能力。" }
            return
        }
        knowledgeBasesLoading = true
        knowledgeBaseRemoteListState = KnowledgeBaseRemoteListState.LOADING
        val snapshot = settings
        scope.launch {
            val result = withContext(Dispatchers.IO) { knowledgeBaseApi.listKnowledgeBases(snapshot) }
            knowledgeBasesLoading = false
            if (result.ok) {
                knowledgeBases.clear()
                knowledgeBases.addAll(result.value?.knowledgeBases.orEmpty())
                knowledgeBaseCache.save(knowledgeBases)
                knowledgeBasesLoadedForFingerprint = capabilityConfigurationFingerprint(snapshot)
                knowledgeBaseRemoteListState = KnowledgeBaseRemoteListState.SUCCESS
                knowledgeBaseListMessage = if (knowledgeBases.isEmpty()) "服务端知识库列表为空。" else ""
            } else {
                knowledgeBaseRemoteListState = KnowledgeBaseRemoteListState.FAILED
                knowledgeBaseListMessage = "服务端列表暂不可用：${result.message}"
            }
        }
    }

    LaunchedEffect(Unit) {
        while (true) {
            val latestRecords = uploadQueue.recent()
            recentRecords.clear()
            recentRecords.addAll(latestRecords)
            val completionEvaluation = UploadCompletionToastPolicy.evaluate(
                records = latestRecords,
                state = uploadCompletionTrackerState,
            )
            uploadCompletionTrackerState = completionEvaluation.state
            if (completionEvaluation.newlyUploadedClipIds.isNotEmpty()) {
                Toast.makeText(context, UploadCompletionToastPolicy.UPLOADED_MESSAGE, Toast.LENGTH_SHORT).show()
                uploadCompletionRevision += completionEvaluation.newlyUploadedClipIds.size
            }
            delay(1000)
        }
    }

    LaunchedEffect(startTab, navigationRevision) {
        if (!LaunchNavigationPolicy.shouldApply(navigationRevision, appliedNavigationRevision)) {
            return@LaunchedEffect
        }
        if (startTab == StartTab.Settings) settingsStateHolder.showHome()
        selectedTab = startTab.index
        appliedNavigationRevision = navigationRevision
    }

    LaunchedEffect(uploadMessage) {
        val currentMessage = uploadMessage
        if (currentMessage == "已保存到本地，正在后台同步") {
            delay(3000)
            if (uploadMessage == currentMessage) uploadMessage = ""
        }
    }

    LaunchedEffect(settings.persistentQuickEntry) {
        quickEntryNotification.sync(settings.persistentQuickEntry)
    }

    LaunchedEffect(settings.apiUrl, settings.ingestToken) {
        val cachedKnowledgeBases = knowledgeBaseCache.load()
        knowledgeBases.clear()
        knowledgeBases.addAll(cachedKnowledgeBases)
        knowledgeBasesLoadedForFingerprint = ""
        knowledgeBaseRemoteListState = if (cachedKnowledgeBases.isEmpty()) {
            KnowledgeBaseRemoteListState.NOT_LOADED
        } else {
            KnowledgeBaseRemoteListState.SUCCESS
        }
        knowledgeBaseListMessage = ""
        delay(300)
        requestCapabilities()
    }

    LaunchedEffect(appCapabilityResult) {
        if (appCapabilityResult.featureAvailability { it.knowledgeBases } == AppFeatureAvailability.UNAVAILABLE) {
            knowledgeBaseListMessage = appCapabilityResult?.message.orEmpty()
        }
    }

    LaunchedEffect(selectedTab, knowledgeManagementOpen, appCapabilityResult, settings.apiUrl, settings.ingestToken) {
        val fingerprint = capabilityConfigurationFingerprint(settings)
        if (KnowledgeBaseLoadPolicy.shouldLoad(
                isKnowledgeSurface = KnowledgeBaseLoadPolicy.isRemoteListSurface(selectedTab, knowledgeManagementOpen),
                knowledgeAvailable = appCapabilityResult.featureAvailability { it.knowledgeBases } == AppFeatureAvailability.AVAILABLE,
                configurationFingerprint = fingerprint,
                loadedFingerprint = knowledgeBasesLoadedForFingerprint,
                loading = knowledgeBasesLoading,
            )
        ) {
            refreshKnowledgeBases()
        }
    }

    LaunchedEffect(selectedTab) {
        if (selectedTab != StartTab.Recents.index) knowledgeDetailOpen = false
    }

    Scaffold(
        bottomBar = {
            if (!knowledgeManagementOpen && !knowledgeDetailOpen) {
            Surface(
                modifier = Modifier
                    .padding(horizontal = 12.dp, vertical = 8.dp)
                    .shadow(8.dp, RoundedCornerShape(22.dp)),
                color = if (darkTheme) MaterialTheme.colorScheme.surface else Color.White,
                shape = RoundedCornerShape(22.dp),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
            ) {
                NavigationBar(
                    modifier = Modifier
                        .height(BottomNavigationSpec.NAVIGATION_HEIGHT_DP.dp)
                        .bottomNavigationSelection(selectedTab, perClipAccentColor()),
                    containerColor = Color.Transparent,
                ) {
                    val navItemColors = NavigationBarItemDefaults.colors(
                        selectedIconColor = perClipAccentColor(),
                        selectedTextColor = perClipAccentColor(),
                        indicatorColor = Color.Transparent,
                        unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    NavigationBarItem(
                        selected = selectedTab == StartTab.Save.index,
                        onClick = { knowledgeManagementOpen = false; selectedTab = StartTab.Save.index },
                        icon = {
                            BottomNavigationIconSlot {
                                Icon(
                                    imageVector = Icons.Rounded.Bolt,
                                    contentDescription = null,
                                    modifier = Modifier.size(BottomNavigationSpec.FLASH_ICON_DP.dp),
                                )
                            }
                        },
                        label = { Text("闪记") },
                        colors = navItemColors,
                    )
                    NavigationBarItem(
                        selected = selectedTab == StartTab.Recents.index,
                        onClick = { knowledgeManagementOpen = false; selectedTab = StartTab.Recents.index },
                        icon = {
                            BottomNavigationIconSlot {
                                Icon(
                                    Icons.AutoMirrored.Rounded.LibraryBooks,
                                    contentDescription = null,
                                    modifier = Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp),
                                )
                            }
                        },
                        label = { Text("知识库") },
                        colors = navItemColors,
                    )
                    NavigationBarItem(
                        selected = selectedTab == StartTab.Recall.index,
                        onClick = { knowledgeManagementOpen = false; selectedTab = StartTab.Recall.index },
                        icon = {
                            BottomNavigationIconSlot {
                                MemoryPlanetTabIcon(
                                    selected = selectedTab == StartTab.Recall.index,
                                    modifier = Modifier.size(BottomNavigationSpec.MEMORY_PLANET_ICON_DP.dp),
                                )
                            }
                        },
                        label = { Text("记忆星球") },
                        colors = navItemColors,
                    )
                    NavigationBarItem(
                        selected = selectedTab == StartTab.Settings.index,
                        onClick = ::openSettingsHome,
                        icon = {
                            BottomNavigationIconSlot {
                                Icon(
                                    Icons.Rounded.Settings,
                                    contentDescription = null,
                                    modifier = Modifier.size(BottomNavigationSpec.STANDARD_ICON_DP.dp),
                                )
                            }
                        },
                        label = { Text("设置") },
                        colors = navItemColors,
                    )
                }
            }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    if (selectedTab == StartTab.Save.index && !darkTheme) ColorTokens.FlashBackground
                    else MaterialTheme.colorScheme.background,
                ),
        ) {
            when (selectedTab) {
                StartTab.Save.index -> FlashNoteScreen(
                    contentPadding = padding,
                    clip = activeClip,
                    quickText = flashQuickText,
                    isSaving = flashSaving,
                    uploadMessage = uploadMessage,
                    defaultKnowledgeBaseName = knowledgeBases.firstOrNull { it.isDefault }?.displayName.orEmpty(),
                    onChangeDefaultKnowledgeBase = {
                        selectedTab = StartTab.Recents.index
                        openDefaultPickerOnManagement = true
                        returnToFlashAfterManagement = true
                        knowledgeManagementOpen = true
                    },
                    onClearClip = {
                        activeClip = null
                        uploadMessage = ""
                    },
                    onQuickTextChange = { flashQuickText = it },
                    onClipSelected = { selectedClip ->
                        activeClip = selectedClip
                        flashQuickText = ""
                        uploadMessage = ""
                    },
                    onSaved = { clip, note ->
                        flashSaving = true
                        scope.launch {
                            val result = withContext(Dispatchers.IO) {
                                captureSaveController.save(
                                    CaptureSaveRequest(
                                        clip = clip,
                                        note = note,
                                        origin = CaptureOrigin.IN_APP_FLASH,
                                    ),
                                )
                            }
                            flashSaving = false
                            val queuedClip = result.queuedClip
                            if (!FlashNoteUiLogic.shouldClearDraftAfterSave(result.savedLocally) || queuedClip == null) {
                                uploadMessage = result.message.ifBlank { "本地保存失败，请重试。" }
                                return@launch
                            }
                            val waitingRecord = queuedClip.toUploadRecord()
                            val existingIndex = recentRecords.indexOfFirst { it.clip.id == clip.id }
                            if (existingIndex >= 0) recentRecords[existingIndex] = waitingRecord
                            else recentRecords.add(0, waitingRecord)
                            recentlySavedClipId = clip.id
                            activeClip = null
                            flashQuickText = ""
                            uploadMessage = "已保存到本地，正在后台同步"
                            selectedTab = StartTab.Save.index
                        }
                    },
                )
                StartTab.Recents.index -> if (knowledgeManagementOpen) {
                    KnowledgeBaseManagementScreen(
                        contentPadding = padding,
                        settings = settings,
                        appCapabilityResult = appCapabilityResult,
                        openDefaultPickerOnLaunch = openDefaultPickerOnManagement,
                        onDefaultPickerLaunchConsumed = { openDefaultPickerOnManagement = false },
                        onKnowledgeBasesLoaded = { loaded ->
                            knowledgeBases.clear()
                            knowledgeBases.addAll(loaded)
                            knowledgeBaseCache.save(loaded)
                            knowledgeBaseRemoteListState = KnowledgeBaseRemoteListState.SUCCESS
                            knowledgeBasesLoadedForFingerprint = capabilityConfigurationFingerprint(settings)
                        },
                        onBack = { closeKnowledgeManagement() },
                    )
                } else KnowledgeHomeScreen(
                    contentPadding = padding,
                    records = recentRecords,
                    settings = settings,
                    topicReadAvailability = appCapabilityResult.featureAvailability { it.qualityReadModel },
                    capabilityResult = appCapabilityResult,
                    uploadCompletionRevision = uploadCompletionRevision,
                    requestedDetailClipId = requestedDetailClipId,
                    onRequestedDetailHandled = { requestedDetailClipId = null },
                    onDetailVisibilityChanged = { knowledgeDetailOpen = it },
                    knowledgeBases = knowledgeBases,
                    knowledgeBasesLoading = knowledgeBasesLoading,
                    knowledgeBaseRemoteListState = knowledgeBaseRemoteListState,
                    knowledgeBaseListMessage = knowledgeBaseListMessage,
                    processingMessage = processingMessage,
                    processingStatusRefreshingClipId = processingStatusRefreshingClipId,
                    selectedKnowledgeScope = selectedKnowledgeScope,
                    onKnowledgeScopeSelected = { selected ->
                        when (selected) {
                            KnowledgeLibraryScope.All -> {
                                selectedKnowledgeScopeKind = "all"
                                selectedKnowledgeScopeId = ""
                            }
                            KnowledgeLibraryScope.Unassigned -> {
                                selectedKnowledgeScopeKind = "unassigned"
                                selectedKnowledgeScopeId = ""
                            }
                            is KnowledgeLibraryScope.Specific -> {
                                selectedKnowledgeScopeKind = "specific"
                                selectedKnowledgeScopeId = selected.knowledgeBaseId
                            }
                        }
                    },
                    onRetry = { id ->
                        uploadQueue.retry(id)
                        refreshRecentRecords()
                    },
                    onDelete = { id ->
                        uploadQueue.delete(id)
                        if (id == recentlySavedClipId) {
                            recentlySavedClipId = null
                        }
                        refreshRecentRecords()
                    },
                    onRefreshKnowledgeBases = {
                        refreshKnowledgeBases()
                    },
                    onRefreshProcessingStatus = refresh@{ record ->
                        if (processingStatusRefreshingClipId == record.clip.id) return@refresh
                        processingStatusRefreshingClipId = record.clip.id
                        scope.launch {
                            try {
                                val result = withContext(Dispatchers.IO) {
                                    val sync = knowledgeBaseApi.ragflowSyncStatus(settings, record.clip.id)
                                    val enrichment = knowledgeBaseApi.enrichmentStatus(settings, record.clip.id)
                                    Triple(sync, enrichment, ClipProcessingStatusRefresh.resolve(sync, enrichment))
                                }
                                val (sync, enrichment, outcome) = result
                                if (outcome.shouldApplyRemoteState) {
                                    uploadQueue.updateMetadata(record.clip.id) { metadata ->
                                        ClipSyncStatusLocalMetadataUpdater.apply(metadata, sync.value, enrichment.value)
                                    }
                                    refreshRecentRecords()
                                }
                                processingMessage = outcome.message
                            } finally {
                                processingStatusRefreshingClipId = null
                            }
                        }
                    },
                    onGoToSave = { selectedTab = StartTab.Save.index },
                )
                StartTab.Recall.index -> RecallScreen(
                    contentPadding = padding,
                    settings = settings,
                    localRecords = recentRecords,
                    knowledgeBases = knowledgeBases,
                    knowledgeBasesLoading = knowledgeBasesLoading,
                    knowledgeBaseListMessage = knowledgeBaseListMessage,
                    onRefreshKnowledgeBases = { refreshKnowledgeBases() },
                    onOpenLocalClip = { clipId ->
                        requestedDetailClipId = clipId
                        selectedTab = StartTab.Recents.index
                    },
                    onGoToSave = { selectedTab = StartTab.Save.index },
                    onGoToSettings = ::openSettingsHome,
                    featureAvailability = appCapabilityResult.featureAvailability { it.recall },
                    memoryPlanetAvailability = appCapabilityResult.featureAvailability { it.memoryPlanet },
                    unavailableMessage = appCapabilityResult?.message.orEmpty(),
                    holder = recallStateHolder,
                    onSettingsChange = { updated ->
                        settings = updated
                        settingsStore.save(updated)
                    },
                    controllerOverride = recallController,
                )
                StartTab.Settings.index -> SettingsScreen(
                    contentPadding = padding,
                    settings = settings,
                    recentRecords = recentRecords,
                    recallStateHolder = recallStateHolder,
                    stateHolder = settingsStateHolder,
                    onRequestNotificationPermission = onRequestNotificationPermission,
                    onConnectionVerified = {
                        val outcome = uploadQueue.refreshWaitingNetworkPolicyWithResult()
                        recentRecords.clear()
                        recentRecords.addAll(outcome.records)
                        outcome.requeuedCount
                    },
                    onSettingsChange = { updated ->
                        val previousWifiOnlyLargeFiles = settings.wifiOnlyLargeFiles
                        val previousThemeMode = settings.themeMode
                        settings = updated
                        settingsStore.save(updated)
                        if (previousThemeMode != updated.themeMode) onThemeModeChanged(updated.themeMode)
                        if (previousWifiOnlyLargeFiles != updated.wifiOnlyLargeFiles) {
                            recentRecords.clear()
                            recentRecords.addAll(uploadQueue.refreshWaitingNetworkPolicy())
                        }
                    },
                    onOpenKnowledgeRecords = {
                        requestedDetailClipId = null
                        selectedTab = StartTab.Recents.index
                    },
                    appCapabilityResult = appCapabilityResult,
                    appCapabilityLoading = appCapabilityLoading,
                    knowledgeBases = knowledgeBases,
                    onKnowledgeBasesLoaded = { loaded ->
                        knowledgeBases.clear()
                        knowledgeBases.addAll(loaded)
                        knowledgeBaseCache.save(loaded)
                        knowledgeBaseRemoteListState = KnowledgeBaseRemoteListState.SUCCESS
                        knowledgeBasesLoadedForFingerprint = capabilityConfigurationFingerprint(settings)
                    },
                    onRequestCapabilityRefresh = { requestCapabilities(force = true) },
                    recallDomainLoaderOverride = recallDomainLoader,
                )
            }
        }
    }
}
