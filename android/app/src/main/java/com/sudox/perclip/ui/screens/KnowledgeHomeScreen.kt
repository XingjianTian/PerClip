package com.sudox.perclip.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.LibraryBooks
import androidx.compose.material.icons.rounded.Cloud
import androidx.compose.material.icons.rounded.CloudOff
import androidx.compose.material.icons.rounded.CloudUpload
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.PriorityHigh
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.PullToRefreshDefaults
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.material3.MaterialTheme
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppFeatureAvailability
import com.sudox.perclip.capabilities.capabilityConfigurationFingerprint
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.knowledge.ClipTopicAssignment
import com.sudox.perclip.knowledge.KnowledgeBaseApi
import com.sudox.perclip.knowledge.KnowledgeBaseRemoteListState
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.knowledge.KnowledgeLibraryScope
import com.sudox.perclip.knowledge.KnowledgeLibraryScopes
import com.sudox.perclip.knowledge.KnowledgeEmptyStatePolicy
import com.sudox.perclip.knowledge.KnowledgeMemoryCacheStore
import com.sudox.perclip.knowledge.KnowledgeReadMode
import com.sudox.perclip.knowledge.KnowledgeReadModeResolver
import com.sudox.perclip.knowledge.KnowledgeRepository
import com.sudox.perclip.knowledge.KnowledgeRepositoryState
import com.sudox.perclip.knowledge.knowledgeRemoteQuery
import com.sudox.perclip.knowledge.KnowledgeTopicClip
import com.sudox.perclip.knowledge.KnowledgeTopicPaginationState
import com.sudox.perclip.knowledge.KnowledgeTopicPaginator
import com.sudox.perclip.knowledge.KnowledgeUploadRefreshPolicy
import com.sudox.perclip.knowledge.KnowledgeRemoteCacheKey
import com.sudox.perclip.knowledge.KnowledgeRemoteCacheVisibility
import com.sudox.perclip.knowledge.KnowledgeRemoteSearch
import com.sudox.perclip.ui.ClipLibraryCardModelBuilder
import com.sudox.perclip.ui.KnowledgeAttachmentFilter
import com.sudox.perclip.ui.KnowledgeHomeFilters
import com.sudox.perclip.ui.KnowledgeLibraryUiModel
import com.sudox.perclip.ui.KnowledgeRecordState
import com.sudox.perclip.ui.KnowledgeTimeFilter
import com.sudox.perclip.ui.PerClipSourceIcon
import com.sudox.perclip.upload.ClipLibraryFilter
import com.sudox.perclip.upload.ClipLibraryQuery
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KnowledgeHomeScreen(
    contentPadding: PaddingValues,
    records: List<UploadRecord>,
    settings: PerClipSettings,
    topicReadAvailability: AppFeatureAvailability,
    capabilityResult: AppCapabilityResult? = null,
    uploadCompletionRevision: Int = 0,
    requestedDetailClipId: String? = null,
    onRequestedDetailHandled: () -> Unit = {},
    knowledgeBases: List<KnowledgeBaseSummary>,
    knowledgeBasesLoading: Boolean,
    knowledgeBaseRemoteListState: KnowledgeBaseRemoteListState,
    knowledgeBaseListMessage: String,
    processingMessage: String,
    processingStatusRefreshingClipId: String?,
    selectedKnowledgeScope: KnowledgeLibraryScope,
    onKnowledgeScopeSelected: (KnowledgeLibraryScope) -> Unit,
    onRetry: (String) -> Unit,
    onDelete: (String) -> Unit,
    onRefreshKnowledgeBases: () -> Unit,
    onRefreshProcessingStatus: (UploadRecord) -> Unit,
    onDetailVisibilityChanged: (Boolean) -> Unit = {},
    onGoToSave: () -> Unit = {},
    initialFilters: KnowledgeHomeFilters = KnowledgeHomeFilters(),
) {
    var query by rememberSaveable { mutableStateOf("") }
    var filters by rememberSaveable(initialFilters, saver = KnowledgeHomeFiltersSaver) { mutableStateOf(initialFilters) }
    var showFilters by remember { mutableStateOf(false) }
    var showScopes by remember { mutableStateOf(false) }
    var selectedRecordId by rememberSaveable { mutableStateOf<String?>(null) }
    var selectedRemoteClipId by rememberSaveable { mutableStateOf<String?>(null) }
    var remoteDetail by remember { mutableStateOf<KnowledgeTopicClip?>(null) }
    var remoteDetailLoading by remember { mutableStateOf(false) }
    var remoteDetailError by remember { mutableStateOf("") }
    var remoteDetailRetryGeneration by remember { mutableStateOf(0) }
    var anchorKey by rememberSaveable { mutableStateOf("") }
    var anchorIndex by rememberSaveable { mutableStateOf(0) }
    var anchorOffset by rememberSaveable { mutableStateOf(0) }
    var restoreAnchor by rememberSaveable { mutableStateOf(false) }
    var remoteRetryGeneration by remember { mutableStateOf(0) }
    var remoteState by remember { mutableStateOf(KnowledgeTopicPaginationState()) }
    var pullRefreshing by remember { mutableStateOf(false) }
    var pullRefreshStartedAt by remember { mutableLongStateOf(0L) }
    var debouncedQuery by rememberSaveable { mutableStateOf("") }
    var v2State by remember { mutableStateOf<KnowledgeRepositoryState?>(null) }
    var cachedV2Hint by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val configurationFingerprint = capabilityConfigurationFingerprint(settings)
    val memoryCacheStore = remember { KnowledgeMemoryCacheStore(context) }
    val repository = remember { KnowledgeRepository(memoryCacheStore) }
    val readMode = KnowledgeReadModeResolver.resolve(settings.normalized().hasUploadConfig, capabilityResult, cachedV2Hint)
    var handledUploadCompletionRevision by remember(configurationFingerprint) {
        mutableIntStateOf(uploadCompletionRevision)
    }
    val coroutineScope = rememberCoroutineScope()
    val topicApi = remember { KnowledgeBaseApi() }
    val paginator = remember { KnowledgeTopicPaginator.network(topicApi) }
    val choices = KnowledgeLibraryScopes.activeChoices(knowledgeBases, records, knowledgeBaseRemoteListState)
    val scope = KnowledgeLibraryScopes.resolveSelection(selectedKnowledgeScope, choices)
    val scoped = KnowledgeLibraryScopes.filter(records, scope)
    val searched = ClipLibraryFilter.apply(scoped, ClipLibraryQuery(text = query))
    val visible = KnowledgeLibraryUiModel.apply(searched, filters)
    val selectedRecord = records.firstOrNull { it.clip.id == selectedRecordId }
    val selectedName = when (scope) {
        KnowledgeLibraryScope.All -> "全部记忆"
        KnowledgeLibraryScope.Unassigned -> "未分配"
        is KnowledgeLibraryScope.Specific -> choices.firstOrNull { it.id == scope.knowledgeBaseId }?.displayName ?: "知识库"
    }
    val remoteKnowledgeBaseIds = when (scope) {
        KnowledgeLibraryScope.All -> if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST) emptyList() else choices.map { it.id }
        is KnowledgeLibraryScope.Specific -> listOf(scope.knowledgeBaseId)
        KnowledgeLibraryScope.Unassigned -> emptyList()
    }
    val v2Query = knowledgeRemoteQuery(
        knowledgeBaseIds = remoteKnowledgeBaseIds,
        text = debouncedQuery,
        source = filters.source,
        type = filters.type,
        attachment = filters.attachment,
        time = filters.time,
    )
    val remoteCacheKey = KnowledgeRemoteCacheKey.create(settings, remoteKnowledgeBaseIds)
    val visibleRemoteState = KnowledgeRemoteCacheVisibility.pagination(
        remoteCacheKey,
        remoteKnowledgeBaseIds,
        remoteState,
    )
    val activeRemoteItems = if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST) {
        v2State?.snapshot?.items.orEmpty().map { it.clip }
    } else {
        visibleRemoteState.items
    }
    val remoteCorrelationIds = if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST) {
        v2State?.snapshot?.items.orEmpty().mapNotNull { it.correlationIdentity.takeIf(String::isNotBlank) }.toSet()
    } else emptySet()
    val deduplicatedLocal = visible.filterNot { record ->
        record.status == UploadStatus.Uploaded && record.uploadParts.any { it.clientRequestId in remoteCorrelationIds }
    }
    val authoritativeCloudCount = KnowledgeCountLabelPolicy.cloudTotal(
        readMode,
        v2State?.snapshot?.summary?.totalCount,
    )
    val summary = KnowledgeLibraryUiModel.summary(
        records = scoped,
        cloudIngestedCount = authoritativeCloudCount,
    )
    val remoteVisible = KnowledgeUnifiedListPolicy.remoteItems(
        if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST && query.trim() == debouncedQuery) {
            activeRemoteItems
        } else KnowledgeRemoteSearch.filter(activeRemoteItems, query),
        filters.status,
    )
    val authoritativeRemoteMatching = if (filters.status != null && filters.status != KnowledgeRecordState.Ingested) {
        0
    } else if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST) {
        v2State?.snapshot?.summary?.matchingCount
    } else remoteVisible.size
    val unifiedVisibleCount = KnowledgeUnifiedListPolicy.statusCount(
        status = filters.status,
        remoteMatchingCount = authoritativeRemoteMatching ?: remoteVisible.size,
        pendingCount = deduplicatedLocal.count { KnowledgeLibraryUiModel.state(it) == KnowledgeRecordState.Pending },
        failedCount = deduplicatedLocal.count { KnowledgeLibraryUiModel.state(it) == KnowledgeRecordState.Failed },
        unconfirmedUploadedCount = deduplicatedLocal.count { it.status == UploadStatus.Uploaded },
    )
    val remoteEnabled = readMode != KnowledgeReadMode.LOCAL_ONLY && scope != KnowledgeLibraryScope.Unassigned &&
        (readMode == KnowledgeReadMode.V2_LOCAL_FIRST || remoteKnowledgeBaseIds.isNotEmpty())
    val remoteLoading = if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST) v2State?.loading == true else visibleRemoteState.loading
    val remoteFailureMessage = if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST) {
        v2State?.syncError.orEmpty().ifBlank { v2State?.snapshot?.lastError.orEmpty() }
    } else visibleRemoteState.failuresByKnowledgeBase.values.firstOrNull().orEmpty()
    val localPendingCount = deduplicatedLocal.count {
        val state = KnowledgeLibraryUiModel.state(it)
        state == KnowledgeRecordState.Pending
    }
    val localFailedCount = deduplicatedLocal.count { KnowledgeLibraryUiModel.state(it) == KnowledgeRecordState.Failed }
    val unconfirmedUploadedCount = deduplicatedLocal.count { it.status == UploadStatus.Uploaded }
    val showEmptyState = if (remoteEnabled) {
        KnowledgeEmptyStatePolicy.shouldShow(
            cacheReadComplete = readMode == KnowledgeReadMode.V2_LOCAL_FIRST && v2State != null,
            loading = remoteLoading,
            offline = v2State?.offline == true,
            partialSyncFailure = v2State?.partialSyncFailure == true || remoteFailureMessage.isNotBlank(),
            authoritativeCount = KnowledgeEmptyAuthoritativeCount.forStatus(
                filters.status,
                authoritativeRemoteMatching,
            ),
            remoteItemCount = remoteVisible.size,
            pendingCount = localPendingCount,
            failedCount = localFailedCount,
            unconfirmedUploadedCount = unconfirmedUploadedCount,
            dirty = v2State?.snapshot?.dirty == true,
        )
    } else {
        deduplicatedLocal.isEmpty() && !remoteLoading
    }
    val listState = rememberLazyListState()
    val pullRefreshState = rememberPullToRefreshState()

    fun refreshKnowledgeList() {
        if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST) {
            coroutineScope.launch {
                try {
                    v2State = v2State?.copy(refreshing = true)
                    v2State = repository.synchronize(
                        settings, configurationFingerprint, v2Query, readMode, forceHead = true,
                    )
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    v2State = v2State?.copy(
                        refreshing = false,
                        partialSyncFailure = true,
                        syncError = error.message.orEmpty().ifBlank { "同步暂不可用" },
                    )
                } finally {
                    pullRefreshing = false
                }
            }
            onRefreshKnowledgeBases()
            return
        }
        remoteState = KnowledgeTopicPaginationState(
            cacheKey = remoteCacheKey,
            knowledgeBaseIds = remoteKnowledgeBaseIds,
        )
        remoteRetryGeneration += 1
        onRefreshKnowledgeBases()
    }

    LaunchedEffect(query) {
        delay(KnowledgeRepository.SEARCH_DEBOUNCE_MS)
        debouncedQuery = query.trim()
    }

    LaunchedEffect(configurationFingerprint) {
        cachedV2Hint = withContext(Dispatchers.IO) { memoryCacheStore.hasCache(configurationFingerprint) }
    }

    LaunchedEffect(configurationFingerprint, v2Query.key, readMode) {
        if (readMode != KnowledgeReadMode.V2_LOCAL_FIRST || scope == KnowledgeLibraryScope.Unassigned) {
            v2State = null
            return@LaunchedEffect
        }
        val cachedState = repository.cached(configurationFingerprint, v2Query, readMode)
        v2State = cachedState.copy(loading = true)
        v2State = repository.synchronize(settings, configurationFingerprint, v2Query, readMode)
    }

    LaunchedEffect(uploadCompletionRevision, configurationFingerprint, v2Query.key, readMode, scope) {
        val shouldRefresh = KnowledgeUploadRefreshPolicy.shouldRefresh(
            completionRevision = uploadCompletionRevision,
            handledRevision = handledUploadCompletionRevision,
            mode = readMode,
            scope = scope,
        )
        handledUploadCompletionRevision = KnowledgeUploadRefreshPolicy.handledRevision(
            completionRevision = uploadCompletionRevision,
            handledRevision = handledUploadCompletionRevision,
        )
        if (!shouldRefresh) return@LaunchedEffect
        try {
            v2State = v2State?.copy(refreshing = true)
            v2State = repository.synchronize(
                settings,
                configurationFingerprint,
                v2Query,
                readMode,
                forceHead = true,
            )
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            v2State = v2State?.copy(
                refreshing = false,
                partialSyncFailure = true,
                syncError = error.message.orEmpty().ifBlank { "同步暂不可用" },
            )
        }
    }

    LaunchedEffect(
        listState.firstVisibleItemIndex,
        v2State?.snapshot?.items?.size,
        v2State?.snapshot?.nextCursor,
        configurationFingerprint,
        v2Query.key,
        readMode,
    ) {
        if (readMode != KnowledgeReadMode.V2_LOCAL_FIRST) return@LaunchedEffect
        val last = listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
        val total = listState.layoutInfo.totalItemsCount
        if (total > 0 && total - last <= KnowledgeRepository.PREFETCH_DISTANCE) {
            val before = v2State?.snapshot?.nextCursor.orEmpty()
            if (before.isNotBlank()) {
                try {
                    v2State = v2State?.copy(loadingNextPage = true)
                    v2State = repository.loadNext(settings, configurationFingerprint, v2Query, readMode)
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    v2State = v2State?.copy(
                        loadingNextPage = false,
                        partialSyncFailure = true,
                        syncError = error.message.orEmpty().ifBlank { "下一页同步失败" },
                    )
                }
            }
        }
    }

    LaunchedEffect(pullRefreshing, knowledgeBasesLoading, visibleRemoteState.loading) {
        if (!pullRefreshing || knowledgeBasesLoading || visibleRemoteState.loading) return@LaunchedEffect
        val minimumVisibleMillis = if (settings.reduceMotion) 120L else 420L
        val elapsed = android.os.SystemClock.elapsedRealtime() - pullRefreshStartedAt
        if (elapsed < minimumVisibleMillis) delay(minimumVisibleMillis - elapsed)
        if (!knowledgeBasesLoading && !visibleRemoteState.loading) pullRefreshing = false
    }

    LaunchedEffect(selectedRecordId, selectedRemoteClipId) {
        onDetailVisibilityChanged(selectedRecordId != null || selectedRemoteClipId != null)
    }

    LaunchedEffect(selectedRemoteClipId, remoteDetailRetryGeneration) {
        val clipId = selectedRemoteClipId ?: run {
            remoteDetail = null
            remoteDetailLoading = false
            remoteDetailError = ""
            return@LaunchedEffect
        }
        remoteDetail = activeRemoteItems.firstOrNull { it.clipId == clipId }
        remoteDetailLoading = true
        remoteDetailError = ""
        val result = withContext(Dispatchers.IO) { topicApi.topicDetail(settings, clipId) }
        if (selectedRemoteClipId != clipId) return@LaunchedEffect
        remoteDetailLoading = false
        if (result.ok && result.value != null) {
            remoteDetail = result.value.clip
        } else {
            remoteDetailError = result.message.ifBlank { "这条记忆暂时无法读取" }
        }
    }

    LaunchedEffect(remoteCacheKey, topicReadAvailability, remoteRetryGeneration, readMode) {
        if (
            readMode != KnowledgeReadMode.LEGACY_QUALITY_READ ||
            topicReadAvailability != AppFeatureAvailability.AVAILABLE ||
            remoteKnowledgeBaseIds.isEmpty()
        ) {
            remoteState = KnowledgeTopicPaginationState(
                cacheKey = remoteCacheKey,
                knowledgeBaseIds = remoteKnowledgeBaseIds,
            )
            return@LaunchedEffect
        }
        remoteState = if (remoteState.cacheKey == remoteCacheKey) {
            remoteState.copy(loading = true)
        } else {
            KnowledgeTopicPaginationState(
                cacheKey = remoteCacheKey,
                knowledgeBaseIds = remoteKnowledgeBaseIds,
                loading = true,
            )
        }
        remoteState = paginator.load(settings, remoteKnowledgeBaseIds, remoteState)
    }

    LaunchedEffect(requestedDetailClipId, records) {
        requestedDetailClipId?.takeIf { id -> records.any { it.clip.id == id } }?.let {
            selectedRecordId = it
            onRequestedDetailHandled()
        }
    }

    fun closeDetail() {
        selectedRecordId = null
        selectedRemoteClipId = null
        restoreAnchor = true
    }

    LaunchedEffect(restoreAnchor, visible, remoteVisible) {
        if (!restoreAnchor) return@LaunchedEffect
        val keys = buildList {
            add("list-header")
            if (remoteEnabled) {
                if (remoteLoading) add("remote-loading")
                if (remoteFailureMessage.isNotBlank()) add("remote-failure")
                addAll(remoteVisible.map { "remote:${it.clipId}" })
            }
            if (visible.isEmpty()) add("local-empty") else addAll(visible.map { "local:${it.clip.id}" })
        }
        val resolved = MemoryDetailAnchorPolicy.resolve(
            MemoryListAnchor(anchorKey, anchorIndex, anchorOffset),
            keys,
        )
        listState.scrollToItem(resolved, anchorOffset.coerceAtLeast(0))
        restoreAnchor = false
    }

    if (selectedRecord != null) {
        MemoryDetailScreen(
            contentPadding = contentPadding,
            model = MemoryDetailUiModelFactory.fromLocal(selectedRecord),
            errorMessage = processingMessage,
            reducedMotionOverride = settings.reduceMotion,
            onBack = ::closeDetail,
            actions = {
                LocalMemoryDetailActions(
                    record = selectedRecord,
                    processingStatusRefreshing = processingStatusRefreshingClipId == selectedRecord.clip.id,
                    onRefreshProcessingStatus = onRefreshProcessingStatus,
                    onRetry = onRetry,
                    onDelete = { id -> closeDetail(); onDelete(id) },
                )
            },
        )
        return
    }

    if (selectedRemoteClipId != null) {
        val detail = remoteDetail
        MemoryDetailScreen(
            contentPadding = contentPadding,
            model = detail?.let(MemoryDetailUiModelFactory::fromRemote),
            loading = remoteDetailLoading,
            errorMessage = remoteDetailError,
            reducedMotionOverride = settings.reduceMotion,
            onBack = ::closeDetail,
            onRetry = {
                remoteDetailRetryGeneration += 1
            },
        )
        return
    }

    Column(
        Modifier.fillMaxSize().background(knowledgeBackgroundColor())
            .padding(bottom = contentPadding.calculateBottomPadding())
            .padding(horizontal = 16.dp)
            .padding(top = contentPadding.calculateTopPadding() + 12.dp),
    ) {
        KnowledgeHeader(
            selectedName = selectedName,
            showScopes = showScopes,
            choices = choices,
            onShowScopes = { showScopes = it },
            onKnowledgeScopeSelected = onKnowledgeScopeSelected,
        )

        SummaryCard(summary.ingested, summary.pending, summary.failed, filters.status) { selected ->
            filters = filters.copy(status = selected?.let { KnowledgeLibraryUiModel.toggleStatus(filters.status, it) })
        }
        val showOfflineNotice = v2State?.offline == true ||
            knowledgeBaseRemoteListState == KnowledgeBaseRemoteListState.FAILED ||
            knowledgeBaseListMessage.contains("配置")
        if (showOfflineNotice) {
            Row(
                Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Rounded.CloudOff, null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text(
                    if (v2State?.snapshot?.items?.isNotEmpty() == true) {
                        "离线，显示上次同步内容"
                    } else {
                        "当前离线，暂无可显示的服务器缓存"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            Spacer(Modifier.height(10.dp))
        }
        val searchShape = RoundedCornerShape(16.dp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                modifier = Modifier
                    .weight(1f)
                    .height(58.dp)
                    .shadow(3.dp, searchShape),
                singleLine = true,
                placeholder = { Text("搜索标题、摘要、平台或文件名", maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall) },
                leadingIcon = { Icon(Icons.Rounded.Search, null) },
                shape = searchShape,
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = MaterialTheme.colorScheme.primary,
                    unfocusedBorderColor = knowledgeBorderColor(),
                    focusedContainerColor = knowledgeSurfaceColor(),
                    unfocusedContainerColor = knowledgeSurfaceColor(),
                ),
            )
            Surface(
                modifier = Modifier.height(58.dp).width(88.dp).clickable { showFilters = true },
                color = MaterialTheme.colorScheme.primary,
                shape = RoundedCornerShape(16.dp),
            ) {
                Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Rounded.Tune, "筛选", tint = Color.White, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(if (filters.activeCount > 0) "筛选 ${filters.activeCount}" else "筛选", color = Color.White, fontWeight = FontWeight.Bold)
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        PullToRefreshBox(
            isRefreshing = pullRefreshing,
            onRefresh = {
                pullRefreshStartedAt = android.os.SystemClock.elapsedRealtime()
                pullRefreshing = true
                refreshKnowledgeList()
            },
            modifier = Modifier.weight(1f),
            state = pullRefreshState,
            indicator = {
                if (settings.reduceMotion) {
                    PullToRefreshDefaults.IndicatorBox(
                        state = pullRefreshState,
                        isRefreshing = pullRefreshing,
                        modifier = Modifier.align(Alignment.TopCenter).semantics {
                            contentDescription = if (pullRefreshing) "正在刷新记忆列表" else "下拉刷新记忆列表"
                        },
                        containerColor = knowledgeSurfaceColor(),
                    ) {
                        Icon(
                            Icons.Rounded.Refresh,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(22.dp),
                        )
                    }
                } else {
                    PullToRefreshDefaults.Indicator(
                        state = pullRefreshState,
                        isRefreshing = pullRefreshing,
                        modifier = Modifier.align(Alignment.TopCenter).semantics {
                            contentDescription = if (pullRefreshing) "正在刷新记忆列表" else "下拉刷新记忆列表"
                        },
                        containerColor = knowledgeSurfaceColor(),
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            },
        ) {
        LazyColumn(Modifier.fillMaxSize(), state = listState, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item("list-header") {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("记忆列表", fontWeight = FontWeight.Black, color = MaterialTheme.colorScheme.onBackground)
                    if (remoteLoading && remoteVisible.isNotEmpty()) {
                        Spacer(Modifier.width(8.dp))
                        Text("正在同步", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Spacer(Modifier.weight(1f))
                    Text(
                        KnowledgeCountLabelPolicy.listLabel(
                            mode = readMode,
                            status = filters.status,
                            authoritativeMatchingCount = authoritativeRemoteMatching,
                            visibleCount = unifiedVisibleCount,
                        ),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (
                remoteEnabled
            ) {
                if (remoteLoading && remoteVisible.isEmpty()) {
                    item("remote-loading") {
                        RemoteKnowledgeSkeleton()
                    }
                }
                if (remoteFailureMessage.isNotBlank() && remoteVisible.isEmpty()) {
                    item("remote-failure") {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                if (remoteVisible.isEmpty()) "当前离线，暂无可显示的服务器缓存。" else "当前离线，正在显示上次同步的缓存。",
                                Modifier.weight(1f),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            TextButton(onClick = {
                                if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST) {
                                    coroutineScope.launch {
                                        v2State = if (
                                            v2State?.pageLoadFailure == true &&
                                            v2State?.snapshot?.nextCursor?.isNotBlank() == true
                                        ) {
                                            v2State = v2State?.copy(loadingNextPage = true)
                                            repository.loadNext(settings, configurationFingerprint, v2Query, readMode)
                                        } else repository.synchronize(settings, configurationFingerprint, v2Query, readMode)
                                    }
                                } else remoteRetryGeneration += 1
                            }) { Text("重试") }
                        }
                    }
                }
                val newContent = v2State?.newContentCount ?: 0
                if (readMode == KnowledgeReadMode.V2_LOCAL_FIRST && newContent > 0) {
                    item("new-content") {
                        Surface(
                            Modifier.fillMaxWidth().clickable {
                                coroutineScope.launch {
                                    v2State = repository.acceptNewContent(configurationFingerprint, v2Query, readMode)
                                    listState.animateScrollToItem(0)
                                }
                            },
                            color = MaterialTheme.colorScheme.primaryContainer,
                            shape = RoundedCornerShape(14.dp),
                        ) {
                            Text("有 $newContent 条新记忆 · 点击查看", Modifier.padding(12.dp), color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                        }
                    }
                }
                items(remoteVisible, key = { "remote:${it.clipId}" }) { clip ->
                    KnowledgeServerTopicCard(
                        clip = clip,
                        onOpen = {
                            val viewportAnchor = listState.layoutInfo.visibleItemsInfo.firstOrNull()
                            anchorKey = viewportAnchor?.key?.toString().orEmpty()
                            anchorIndex = viewportAnchor?.index ?: listState.firstVisibleItemIndex
                            anchorOffset = listState.firstVisibleItemScrollOffset
                            selectedRemoteClipId = clip.clipId
                        },
                    )
                }
                if (remoteFailureMessage.isNotBlank() && remoteVisible.isNotEmpty()) {
                    item("remote-page-failure") {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text("同步暂不可用，已保留上次内容", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            TextButton(onClick = {
                                coroutineScope.launch {
                                    v2State = if (
                                        v2State?.pageLoadFailure == true &&
                                        v2State?.snapshot?.nextCursor?.isNotBlank() == true
                                    ) {
                                        v2State = v2State?.copy(loadingNextPage = true)
                                        repository.loadNext(settings, configurationFingerprint, v2Query, readMode)
                                    } else repository.synchronize(settings, configurationFingerprint, v2Query, readMode)
                                }
                            }) { Text("重试") }
                        }
                    }
                }
                if (v2State?.loadingNextPage == true) {
                    item("remote-page-loading") {
                        Text(
                            "正在加载更多…",
                            Modifier.fillMaxWidth().padding(vertical = 12.dp),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            if (showEmptyState) {
                item("local-empty") {
                    Column(
                        Modifier.fillMaxWidth().padding(vertical = 28.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Icon(Icons.AutoMirrored.Rounded.LibraryBooks, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(38.dp))
                        val filtered = query.isNotBlank() || filters.activeCount > 0
                        Text(
                            when {
                                filtered -> "没有符合当前条件的记忆"
                                remoteEnabled -> "这里还没有记忆"
                                else -> "还没有本机保存记录"
                            },
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onBackground,
                        )
                        Text(
                            if (filtered) "试试清除搜索或调整筛选条件" else "闪记的内容会先保存在本机",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        if (scoped.isEmpty()) TextButton(onClick = onGoToSave, modifier = Modifier.height(48.dp)) { Text("去闪记", color = MaterialTheme.colorScheme.primary) }
                    }
                }
            } else if (deduplicatedLocal.isNotEmpty()) {
                items(deduplicatedLocal, key = { "local:${it.clip.id}" }) { record ->
                    KnowledgeRecordCard(
                        record,
                        onOpen = {
                            val viewportAnchor = listState.layoutInfo.visibleItemsInfo.firstOrNull()
                            anchorKey = viewportAnchor?.key?.toString().orEmpty()
                            anchorIndex = viewportAnchor?.index ?: listState.firstVisibleItemIndex
                            anchorOffset = listState.firstVisibleItemScrollOffset
                            selectedRecordId = record.clip.id
                        },
                    )
                }
            }
        }
        }
    }

    if (showFilters) FilterSheet(
        filters,
        (KnowledgeLibraryUiModel.sources(scoped) + activeRemoteItems.map { it.source }.filter(String::isNotBlank)).distinct().sorted(),
        onChange = { filters = it },
        onDismiss = { showFilters = false },
    )
}

private val KnowledgeHomeFiltersSaver = Saver<androidx.compose.runtime.MutableState<KnowledgeHomeFilters>, List<String>>(
    save = { state -> KnowledgeHomeFiltersSavePolicy.encode(state.value) },
    restore = { saved -> mutableStateOf(KnowledgeHomeFiltersSavePolicy.decode(saved)) },
)

internal object KnowledgeHomeFiltersSavePolicy {
    fun encode(value: KnowledgeHomeFilters): List<String> = listOf(
        value.status?.name.orEmpty(),
        value.source,
        value.type.name,
        value.attachment.name,
        value.time.name,
    )

    fun decode(saved: List<String>): KnowledgeHomeFilters = KnowledgeHomeFilters(
        status = saved.getOrNull(0)?.takeIf(String::isNotBlank)?.let { savedStatus ->
            if (savedStatus == "LocalSaved") KnowledgeRecordState.Pending else KnowledgeRecordState.valueOf(savedStatus)
        },
        source = saved.getOrNull(1).orEmpty(),
        type = saved.getOrNull(2)?.let(ClipLibraryTypeFilter::valueOf) ?: ClipLibraryTypeFilter.All,
        attachment = saved.getOrNull(3)?.let(KnowledgeAttachmentFilter::valueOf) ?: KnowledgeAttachmentFilter.All,
        time = saved.getOrNull(4)?.let(KnowledgeTimeFilter::valueOf) ?: KnowledgeTimeFilter.All,
    )
}

@Composable
private fun LocalMemoryDetailActions(
    record: UploadRecord,
    processingStatusRefreshing: Boolean,
    onRefreshProcessingStatus: (UploadRecord) -> Unit,
    onRetry: (String) -> Unit,
    onDelete: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("本地记录操作", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Black)
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            enabled = record.status == UploadStatus.Failed,
            onClick = { onRetry(record.clip.id) },
        ) { Text("重试同步") }
        TextButton(
            onClick = { onRefreshProcessingStatus(record) },
            enabled = !processingStatusRefreshing,
        ) { Text(if (processingStatusRefreshing) "正在刷新…" else "刷新处理状态") }
        TextButton(
            onClick = { onDelete(record.clip.id) },
            colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
        ) { Text("删除本地记录") }
    }
}

@Composable
private fun KnowledgeHeader(
    selectedName: String,
    showScopes: Boolean,
    choices: List<KnowledgeBaseSummary>,
    onShowScopes: (Boolean) -> Unit,
    onKnowledgeScopeSelected: (KnowledgeLibraryScope) -> Unit,
) {
    Box(Modifier.fillMaxWidth().height(KnowledgeHomeLayoutSpec.HEADER_HEIGHT_DP.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().align(Alignment.TopStart),
            verticalAlignment = Alignment.Top,
        ) {
            Box(
                Modifier.weight(1f).height(48.dp).clickable(role = Role.Button) { onShowScopes(true) }.semantics {
                    contentDescription = "切换知识库，当前为 $selectedName"
                    role = Role.Button
                },
            ) {
                Row(
                    modifier = Modifier.align(Alignment.TopStart),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        selectedName,
                        modifier = Modifier.weight(1f, fill = false),
                        style = MaterialTheme.typography.headlineMedium,
                        fontWeight = FontWeight.Black,
                        color = MaterialTheme.colorScheme.onBackground,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.width(2.dp))
                    Icon(
                        Icons.Rounded.ExpandMore,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onBackground,
                        modifier = Modifier.size(24.dp),
                    )
                }
                DropdownMenu(expanded = showScopes, onDismissRequest = { onShowScopes(false) }) {
                    DropdownMenuItem(text = { Text("全部记忆") }, onClick = { onShowScopes(false); onKnowledgeScopeSelected(KnowledgeLibraryScope.All) })
                    choices.forEach { kb ->
                        DropdownMenuItem(
                            text = { Text(if (kb.isDefault) "${kb.displayName} · 默认" else kb.displayName) },
                            onClick = { onShowScopes(false); onKnowledgeScopeSelected(KnowledgeLibraryScope.Specific(kb.id)) },
                        )
                    }
                }
            }
        }
    }
}

internal object KnowledgeHomeLayoutSpec {
    const val HEADER_HEIGHT_DP = 56
}

@Composable
private fun SummaryCard(ingested: Int?, pending: Int, failed: Int, selected: KnowledgeRecordState?, onSelect: (KnowledgeRecordState?) -> Unit) {
    val shape = RoundedCornerShape(18.dp)
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .shadow(3.dp, shape),
        colors = CardDefaults.cardColors(containerColor = knowledgeSurfaceColor()),
        border = BorderStroke(1.dp, knowledgeBorderColor()),
        shape = shape,
    ) {
        Column(Modifier.fillMaxWidth().padding(10.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SummaryMetric(Modifier.weight(1f), "已处理", ingested, Color(0xFF2E8B61), KnowledgeRecordState.Ingested, selected == KnowledgeRecordState.Ingested) { onSelect(KnowledgeRecordState.Ingested) }
                SummaryMetric(Modifier.weight(1f), "待同步", pending, MaterialTheme.colorScheme.primary, KnowledgeRecordState.Pending, selected == KnowledgeRecordState.Pending) { onSelect(KnowledgeRecordState.Pending) }
                SummaryMetric(Modifier.weight(1f), "失败", failed, Color(0xFFB83A4D), KnowledgeRecordState.Failed, selected == KnowledgeRecordState.Failed) { onSelect(KnowledgeRecordState.Failed) }
            }
        }
    }
}

@Composable private fun SummaryMetric(modifier: Modifier, label: String, value: Int?, color: Color, state: KnowledgeRecordState, selected: Boolean, onClick: () -> Unit) {
    Surface(
        modifier = modifier.height(72.dp).clickable(onClick = onClick),
        color = if (selected) color.copy(alpha = .14f) else if (isKnowledgeDarkTheme()) MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .34f) else Color(0xFFFCFBFF),
        border = null,
        shape = RoundedCornerShape(12.dp),
    ) {
        Row(Modifier.fillMaxSize().padding(horizontal = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Surface(Modifier.size(28.dp), color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = .82f), shape = CircleShape) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = when (state) {
                            KnowledgeRecordState.Ingested -> Icons.Rounded.Cloud
                            KnowledgeRecordState.Pending -> Icons.Rounded.CloudUpload
                            KnowledgeRecordState.Failed -> Icons.Rounded.PriorityHigh
                        },
                        contentDescription = null,
                        tint = color,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
            Spacer(Modifier.width(5.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    label,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    softWrap = false,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(value?.toString() ?: "—", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Black, color = color)
            }
        }
    }
}

@Composable
private fun RemoteKnowledgeSkeleton() {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        repeat(3) {
            Surface(
                Modifier.fillMaxWidth().height(108.dp),
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .38f),
                shape = RoundedCornerShape(18.dp),
            ) {}
        }
    }
}

internal object KnowledgeMemoryCardPolicy {
    fun localTopicLabels(record: UploadRecord): List<String> =
        MemoryDetailTopicPolicy.fromLocal(record).labels

    fun remoteTopicLabels(assignment: ClipTopicAssignment): List<String> =
        MemoryDetailTopicPolicy.fromRemote(assignment).labels

    private val TimeFormatter = DateTimeFormatter.ofPattern("HH:mm", Locale.CHINA)
    private val DateFormatter = DateTimeFormatter.ofPattern("M月d日", Locale.CHINA)

    fun localDateLabel(
        createdAtEpochMs: Long,
        nowEpochMs: Long = System.currentTimeMillis(),
        zoneId: ZoneId = ZoneId.systemDefault(),
    ): String {
        if (createdAtEpochMs <= 0L) return "时间未知"
        return formatDate(Instant.ofEpochMilli(createdAtEpochMs), nowEpochMs, zoneId)
    }

    fun remoteDateLabel(
        capturedAt: String,
        nowEpochMs: Long = System.currentTimeMillis(),
        zoneId: ZoneId = ZoneId.systemDefault(),
    ): String {
        val instant = runCatching { Instant.parse(capturedAt) }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(capturedAt).toInstant() }.getOrNull()
            ?: return capturedAt.take(10)
        return formatDate(instant, nowEpochMs, zoneId)
    }

    private fun formatDate(instant: Instant, nowEpochMs: Long, zoneId: ZoneId): String {
        val captured = instant.atZone(zoneId)
        val today = Instant.ofEpochMilli(nowEpochMs).atZone(zoneId).toLocalDate()
        return if (captured.toLocalDate() == today) {
            captured.format(TimeFormatter)
        } else {
            captured.format(DateFormatter)
        }
    }
}

internal object KnowledgeUnifiedListPolicy {
    fun <T> remoteItems(items: List<T>, status: KnowledgeRecordState?): List<T> =
        if (status == null || status == KnowledgeRecordState.Ingested) items else emptyList()

    fun visibleCount(localCount: Int, remoteCount: Int): Int = localCount + remoteCount

    fun statusCount(
        status: KnowledgeRecordState?,
        remoteMatchingCount: Int,
        pendingCount: Int,
        failedCount: Int,
        unconfirmedUploadedCount: Int,
    ): Int = when (status) {
        null -> remoteMatchingCount + pendingCount + failedCount + unconfirmedUploadedCount
        KnowledgeRecordState.Ingested -> remoteMatchingCount + unconfirmedUploadedCount
        KnowledgeRecordState.Pending -> pendingCount
        KnowledgeRecordState.Failed -> failedCount
    }

    fun countLabel(status: KnowledgeRecordState?, count: Int): String =
        status?.let { "${it.label} · $count 条" } ?: "共 $count 条"
}

internal object KnowledgeEmptyAuthoritativeCount {
    fun forStatus(status: KnowledgeRecordState?, remoteMatchingCount: Int?): Int? =
        when (status) {
            KnowledgeRecordState.Pending, KnowledgeRecordState.Failed -> 0
            KnowledgeRecordState.Ingested, null -> remoteMatchingCount
        }
}

internal object KnowledgeCountLabelPolicy {
    fun cloudTotal(mode: KnowledgeReadMode, authoritativeTotal: Int?): Int? =
        authoritativeTotal.takeIf { mode == KnowledgeReadMode.V2_LOCAL_FIRST }

    fun listLabel(
        mode: KnowledgeReadMode,
        status: KnowledgeRecordState?,
        authoritativeMatchingCount: Int?,
        visibleCount: Int,
    ): String = when (mode) {
        KnowledgeReadMode.V2_LOCAL_FIRST -> when {
            status == KnowledgeRecordState.Pending || status == KnowledgeRecordState.Failed ->
                KnowledgeUnifiedListPolicy.countLabel(status, visibleCount)
            authoritativeMatchingCount == null -> "读取中"
            else -> KnowledgeUnifiedListPolicy.countLabel(status, visibleCount)
        }
        KnowledgeReadMode.LEGACY_QUALITY_READ -> when (status) {
            KnowledgeRecordState.Pending, KnowledgeRecordState.Failed ->
                KnowledgeUnifiedListPolicy.countLabel(status, visibleCount)
            else -> "已加载 $visibleCount 条"
        }
        KnowledgeReadMode.LOCAL_ONLY -> status?.let { "${it.label} · $visibleCount 条" } ?: "本机 $visibleCount 条"
    }
}

@Composable
private fun KnowledgeRecordCard(record: UploadRecord, onOpen: () -> Unit) {
    val model = ClipLibraryCardModelBuilder.from(record)
    val state = KnowledgeLibraryUiModel.state(record)
    val topicLabels = KnowledgeMemoryCardPolicy.localTopicLabels(record)
    val shape = RoundedCornerShape(18.dp)
    Card(
        Modifier
            .fillMaxWidth()
            .height(108.dp)
            .shadow(3.dp, shape)
            .semantics {
                stateDescription = state.label
            }
            .clickable(onClick = onOpen),
        colors = CardDefaults.cardColors(containerColor = knowledgeSurfaceColor()),
        border = BorderStroke(1.dp, if (state == KnowledgeRecordState.Failed) Color(0xFFD75C6A) else knowledgeBorderColor()),
        shape = shape,
    ) {
        Box(Modifier.fillMaxSize()) {
            Box(
                Modifier.offset(x = 20.dp, y = 30.dp).size(56.dp),
                contentAlignment = Alignment.Center,
            ) {
                PerClipSourceIcon(record.clip.sourceApp, Modifier.size(48.dp), record.clip.url)
            }
            Column(
                Modifier.fillMaxWidth().padding(start = 88.dp, end = 20.dp, top = 21.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(model.title, modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurface)
                    Spacer(Modifier.width(8.dp))
                    Text(KnowledgeMemoryCardPolicy.localDateLabel(record.createdAtEpochMs), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                Text(model.summary, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    FlowRow(
                        modifier = Modifier.weight(1f),
                        horizontalArrangement = Arrangement.spacedBy(5.dp),
                        maxItemsInEachRow = 2,
                    ) {
                        topicLabels.forEach { KnowledgeTopicPill(it) }
                    }
                    Spacer(Modifier.width(8.dp))
                    KnowledgeCardStateIcon(state)
                }
            }
        }
    }
}

@Composable
private fun KnowledgeServerTopicCard(
    clip: KnowledgeTopicClip,
    onOpen: () -> Unit,
) {
    val assignment = clip.topicAssignment
    val topicLabels = KnowledgeMemoryCardPolicy.remoteTopicLabels(assignment)
    val shape = RoundedCornerShape(18.dp)
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .height(108.dp)
            .shadow(3.dp, shape)
            .clickable(onClick = onOpen),
        shape = shape,
        colors = CardDefaults.cardColors(containerColor = knowledgeSurfaceColor()),
        border = BorderStroke(1.dp, knowledgeBorderColor()),
    ) {
        Box(Modifier.fillMaxSize()) {
            Box(
                Modifier.offset(x = 20.dp, y = 30.dp).size(56.dp),
                contentAlignment = Alignment.Center,
            ) {
                PerClipSourceIcon(clip.source, Modifier.size(48.dp), clip.safeDisplayUrl)
            }
            Column(
                Modifier.fillMaxWidth().padding(start = 88.dp, end = 20.dp, top = 21.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(clip.title, modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurface, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.width(8.dp))
                    Text(KnowledgeMemoryCardPolicy.remoteDateLabel(clip.capturedAt), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                if (clip.summary.isNotBlank()) {
                    Text(
                        clip.summary,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    FlowRow(
                        modifier = Modifier.weight(1f),
                        horizontalArrangement = Arrangement.spacedBy(5.dp),
                        maxItemsInEachRow = 2,
                    ) {
                        topicLabels.forEach { KnowledgeTopicPill(it, disabled = assignment.topicDisabled) }
                    }
                    Spacer(Modifier.width(8.dp))
                    KnowledgeCardStateIcon(KnowledgeRecordState.Ingested)
                }
            }
        }
    }
}

@Composable
private fun KnowledgeCardStateIcon(state: KnowledgeRecordState) {
    val (icon, color) = when (state) {
        KnowledgeRecordState.Ingested -> Icons.Rounded.Cloud to Color(0xFF2E8B61)
        KnowledgeRecordState.Pending -> Icons.Rounded.CloudUpload to MaterialTheme.colorScheme.primary
        KnowledgeRecordState.Failed -> Icons.Rounded.PriorityHigh to Color(0xFFB83A4D)
    }
    Icon(icon, contentDescription = state.label, tint = color, modifier = Modifier.size(16.dp))
}

@Composable
private fun KnowledgeTopicPill(label: String, disabled: Boolean = false) {
    Surface(
        color = if (disabled) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.primaryContainer,
        shape = CircleShape,
        border = BorderStroke(
            1.dp,
            MaterialTheme.colorScheme.outline,
        ),
    ) {
        Text(
            label,
            Modifier.padding(horizontal = 9.dp, vertical = 3.dp),
            style = MaterialTheme.typography.labelSmall,
            color = if (disabled) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.primary,
            maxLines = 1,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun FilterSheet(filters: KnowledgeHomeFilters, sources: List<String>, onChange: (KnowledgeHomeFilters) -> Unit, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) { Text("筛选记忆", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black); Spacer(Modifier.weight(1f)); TextButton(onClick = { onChange(KnowledgeHomeFilters()) }) { Text("清除 ${filters.activeCount}") } }
            FilterGroup("状态", listOf<Pair<String, KnowledgeRecordState?>>("全部" to null) + KnowledgeRecordState.entries.map { it.label to it }, filters.status) { onChange(filters.copy(status = it)) }
            FilterGroup("平台", listOf("全部" to "") + sources.map { it to it }, filters.source) { onChange(filters.copy(source = it)) }
            FilterGroup("类型", ClipLibraryTypeFilter.entries.map { typeLabel(it) to it }, filters.type) { onChange(filters.copy(type = it)) }
            FilterGroup("附件", KnowledgeAttachmentFilter.entries.map { it.label to it }, filters.attachment) { onChange(filters.copy(attachment = it)) }
            FilterGroup("时间", KnowledgeTimeFilter.entries.map { it.label to it }, filters.time) { onChange(filters.copy(time = it)) }
            TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text("完成", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold) }
        }
    }
}

@Composable private fun <T> FilterGroup(title: String, choices: List<Pair<String, T>>, selected: T, onSelect: (T) -> Unit) {
    Text(title, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurface)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(7.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) { choices.forEach { (label, value) -> FilterChip(selected = selected == value, onClick = { onSelect(value) }, label = { Text(label) }) } }
}

private fun typeLabel(type: ClipLibraryTypeFilter) = when (type) { ClipLibraryTypeFilter.All -> "全部"; ClipLibraryTypeFilter.Text -> "文字"; ClipLibraryTypeFilter.Url -> "链接"; ClipLibraryTypeFilter.Image -> "图片"; ClipLibraryTypeFilter.File -> "文件"; ClipLibraryTypeFilter.ScreenClip -> "屏幕闪记" }
