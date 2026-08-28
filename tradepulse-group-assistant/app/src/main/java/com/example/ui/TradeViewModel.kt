package com.example.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.data.local.AppDatabase
import com.example.data.model.AlertRule
import com.example.data.model.GroupMonitor
import com.example.data.model.ParsedTradeItem
import com.example.data.model.PriceHistoryRecord
import com.example.data.repository.GeminiParserService
import com.example.data.repository.TradeRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class TradeUiState(
    val tradeItems: List<ParsedTradeItem> = emptyList(),
    val filteredTradeItems: List<ParsedTradeItem> = emptyList(),
    val adItems: List<ParsedTradeItem> = emptyList(),
    val matchedAlertItems: List<ParsedTradeItem> = emptyList(),
    val alertRules: List<AlertRule> = emptyList(),
    val groupMonitors: List<GroupMonitor> = emptyList(),
    val priceHistoryRecords: List<PriceHistoryRecord> = emptyList(),
    // Filter parameters
    val searchQuery: String = "",
    val selectedCategory: String = "全部", // "全部", "电动车", "二手教材", "3C数码", "宿舍用品", "运动健身", "服饰美妆", "其他"
    val selectedPlatform: String = "全部", // "全部", "WeChat", "QQ"
    val selectedTradeType: String = "全部", // "全部", "出售", "求购"
    val showAdsOnly: Boolean = false,
    // Assistant Floating State
    val isFloatingAssistantActive: Boolean = true,
    val isProcessing: Boolean = false,
    val lastSimulatedItem: ParsedTradeItem? = null,
    val quickContactItem: ParsedTradeItem? = null
)

class TradeViewModel(application: Application) : AndroidViewModel(application) {

    private val db = AppDatabase.getDatabase(application)
    private val repository = TradeRepository(db.tradeDao(), GeminiParserService())

    private val _searchQuery = MutableStateFlow("")
    private val _selectedCategory = MutableStateFlow("全部")
    private val _selectedPlatform = MutableStateFlow("全部")
    private val _selectedTradeType = MutableStateFlow("全部")
    private val _showAdsOnly = MutableStateFlow(false)
    private val _isFloatingAssistantActive = MutableStateFlow(true)
    private val _isProcessing = MutableStateFlow(false)
    private val _lastSimulatedItem = MutableStateFlow<ParsedTradeItem?>(null)
    private val _quickContactItem = MutableStateFlow<ParsedTradeItem?>(null)

    val uiState: StateFlow<TradeUiState> = combine(
        repository.allTradeItems,
        repository.validTradeItems,
        repository.adTradeItems,
        repository.matchedAlertItems,
        repository.alertRules,
        repository.groupMonitors,
        repository.priceHistoryRecords,
        _searchQuery,
        _selectedCategory,
        _selectedPlatform,
        _selectedTradeType,
        _showAdsOnly,
        _isFloatingAssistantActive,
        _isProcessing,
        _lastSimulatedItem,
        _quickContactItem
    ) { arrayOfValues ->
        val allItems = arrayOfValues[0] as List<ParsedTradeItem>
        val validItems = arrayOfValues[1] as List<ParsedTradeItem>
        val adItems = arrayOfValues[2] as List<ParsedTradeItem>
        val alertItems = arrayOfValues[3] as List<ParsedTradeItem>
        val rules = arrayOfValues[4] as List<AlertRule>
        val groups = arrayOfValues[5] as List<GroupMonitor>
        val prices = arrayOfValues[6] as List<PriceHistoryRecord>
        val query = arrayOfValues[7] as String
        val category = arrayOfValues[8] as String
        val platform = arrayOfValues[9] as String
        val tradeType = arrayOfValues[10] as String
        val showAds = arrayOfValues[11] as Boolean
        val floatingActive = arrayOfValues[12] as Boolean
        val processing = arrayOfValues[13] as Boolean
        val lastSimulated = arrayOfValues[14] as ParsedTradeItem?
        val quickContact = arrayOfValues[15] as ParsedTradeItem?

        val sourceList = if (showAds) adItems else validItems

        val filtered = sourceList.filter { item ->
            val matchesQuery = query.isBlank() ||
                    item.title.contains(query, ignoreCase = true) ||
                    item.rawMessage.contains(query, ignoreCase = true) ||
                    item.category.contains(query, ignoreCase = true) ||
                    item.contactInfo.contains(query, ignoreCase = true)

            val matchesCategory = category == "全部" || item.category == category
            val matchesPlatform = platform == "全部" || item.platform == platform
            val matchesType = tradeType == "全部" || item.tradeType == tradeType

            matchesQuery && matchesCategory && matchesPlatform && matchesType
        }

        TradeUiState(
            tradeItems = allItems,
            filteredTradeItems = filtered,
            adItems = adItems,
            matchedAlertItems = alertItems,
            alertRules = rules,
            groupMonitors = groups,
            priceHistoryRecords = prices,
            searchQuery = query,
            selectedCategory = category,
            selectedPlatform = platform,
            selectedTradeType = tradeType,
            showAdsOnly = showAds,
            isFloatingAssistantActive = floatingActive,
            isProcessing = processing,
            lastSimulatedItem = lastSimulated,
            quickContactItem = quickContact
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5000),
        initialValue = TradeUiState()
    )

    init {
        viewModelScope.launch {
            repository.seedInitialDataIfEmpty()
        }
    }

    fun onSearchQueryChanged(query: String) {
        _searchQuery.value = query
    }

    fun onCategorySelected(category: String) {
        _selectedCategory.value = category
    }

    fun onPlatformSelected(platform: String) {
        _selectedPlatform.value = platform
    }

    fun onTradeTypeSelected(tradeType: String) {
        _selectedTradeType.value = tradeType
    }

    fun onToggleShowAds(showAds: Boolean) {
        _showAdsOnly.value = showAds
    }

    fun onToggleFloatingAssistant(active: Boolean) {
        _isFloatingAssistantActive.value = active
    }

    fun onSelectQuickContact(item: ParsedTradeItem?) {
        _quickContactItem.value = item
    }

    fun onAddAlertRule(keyword: String, category: String, maxPrice: Double?, platformFilter: String) {
        viewModelScope.launch {
            repository.addAlertRule(
                AlertRule(
                    keyword = keyword,
                    category = category,
                    maxPrice = maxPrice,
                    platformFilter = platformFilter
                )
            )
        }
    }

    fun onDeleteAlertRule(id: Int) {
        viewModelScope.launch {
            repository.deleteAlertRule(id)
        }
    }

    fun onToggleAlertRule(rule: AlertRule) {
        viewModelScope.launch {
            repository.toggleAlertRule(rule)
        }
    }

    fun onToggleFavorite(item: ParsedTradeItem) {
        viewModelScope.launch {
            repository.toggleFavorite(item)
        }
    }

    fun onSimulateMessage(rawMessage: String, groupName: String, platform: String, senderName: String) {
        if (rawMessage.isBlank()) return
        viewModelScope.launch {
            _isProcessing.value = true
            val parsed = repository.processAndSaveMessage(rawMessage, groupName, platform, senderName)
            _lastSimulatedItem.value = parsed
            _isProcessing.value = false
        }
    }

    fun clearLastSimulatedItem() {
        _lastSimulatedItem.value = null
    }

    fun generateQuickReplyMessage(item: ParsedTradeItem): String {
        val actionText = if (item.tradeType == "出售") "看货/看车" else "出你需要的物品"
        return "你好！在群【${item.groupName}】中看到你的【${item.title}】消息。请问还在吗？关于价格【${item.priceText}】，是否方便交流试用/交割？"
    }
}
