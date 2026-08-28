package com.example.data.model

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "trade_items")
data class ParsedTradeItem(
    @PrimaryKey(autoGenerate = true) val id: Int = 0,
    val rawMessage: String,
    val groupName: String,
    val platform: String, // "WeChat" or "QQ"
    val senderName: String,
    val title: String,
    val category: String, // "电动车", "二手教材", "3C数码", "宿舍用品", "运动健身", "服饰美妆", "其他"
    val tradeType: String, // "出售", "求购"
    val price: Double,
    val priceText: String,
    val condition: String, // "九成新", "全新", "七成新", "闲置"
    val contactInfo: String,
    val contactType: String, // "WeChat", "QQ", "Phone", "Unknown"
    val location: String,
    val isAd: Boolean,
    val adReason: String? = null,
    val timestamp: Long = System.currentTimeMillis(),
    val matchedRuleKeyword: String? = null,
    val isFavorite: Boolean = false
)

@Entity(tableName = "alert_rules")
data class AlertRule(
    @PrimaryKey(autoGenerate = true) val id: Int = 0,
    val keyword: String,
    val category: String = "全部",
    val maxPrice: Double? = null,
    val minPrice: Double? = null,
    val platformFilter: String = "全部", // "全部", "WeChat", "QQ"
    val isEnabled: Boolean = true,
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(tableName = "group_monitors")
data class GroupMonitor(
    @PrimaryKey(autoGenerate = true) val id: Int = 0,
    val groupName: String,
    val platform: String, // "WeChat" or "QQ"
    val memberCount: Int,
    val totalMessages: Int,
    val tradeMessages: Int,
    val adMessages: Int,
    val isListening: Boolean = true,
    val lastActiveTime: Long = System.currentTimeMillis()
)

@Entity(tableName = "price_history")
data class PriceHistoryRecord(
    @PrimaryKey(autoGenerate = true) val id: Int = 0,
    val keyword: String, // e.g. "二手电动车", "高数教材", "iPad"
    val category: String,
    val avgPrice: Double,
    val minPrice: Double,
    val maxPrice: Double,
    val sampleCount: Int,
    val trendTag: String, // "价格稳定", "近期降价 12%", "热门抢手"
    val priceHistoryData: String // JSON or comma separated e.g. "850,820,800,780,750"
)
