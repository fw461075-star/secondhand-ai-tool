package com.example.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import com.example.data.model.AlertRule
import com.example.data.model.GroupMonitor
import com.example.data.model.ParsedTradeItem
import com.example.data.model.PriceHistoryRecord
import kotlinx.coroutines.flow.Flow

@Dao
interface TradeDao {
    // Parsed Trade Items
    @Query("SELECT * FROM trade_items ORDER BY timestamp DESC")
    fun getAllTradeItems(): Flow<List<ParsedTradeItem>>

    @Query("SELECT * FROM trade_items WHERE isAd = 0 ORDER BY timestamp DESC")
    fun getValidTradeItems(): Flow<List<ParsedTradeItem>>

    @Query("SELECT * FROM trade_items WHERE isAd = 1 ORDER BY timestamp DESC")
    fun getAdTradeItems(): Flow<List<ParsedTradeItem>>

    @Query("SELECT * FROM trade_items WHERE matchedRuleKeyword IS NOT NULL ORDER BY timestamp DESC")
    fun getMatchedAlertItems(): Flow<List<ParsedTradeItem>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertTradeItem(item: ParsedTradeItem): Long

    @Update
    suspend fun updateTradeItem(item: ParsedTradeItem)

    @Query("DELETE FROM trade_items WHERE id = :id")
    suspend fun deleteTradeItem(id: Int)

    @Query("DELETE FROM trade_items")
    suspend fun clearAllTradeItems()

    // Alert Rules
    @Query("SELECT * FROM alert_rules ORDER BY createdAt DESC")
    fun getAllRules(): Flow<List<AlertRule>>

    @Query("SELECT * FROM alert_rules WHERE isEnabled = 1")
    suspend fun getActiveRulesSync(): List<AlertRule>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertRule(rule: AlertRule): Long

    @Query("DELETE FROM alert_rules WHERE id = :id")
    suspend fun deleteRule(id: Int)

    @Update
    suspend fun updateRule(rule: AlertRule)

    // Group Monitors
    @Query("SELECT * FROM group_monitors ORDER BY lastActiveTime DESC")
    fun getAllGroupMonitors(): Flow<List<GroupMonitor>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertGroupMonitor(group: GroupMonitor): Long

    @Query("UPDATE group_monitors SET totalMessages = totalMessages + 1, tradeMessages = tradeMessages + :isTrade, adMessages = adMessages + :isAd, lastActiveTime = :now WHERE groupName = :groupName")
    suspend fun updateGroupStats(groupName: String, isTrade: Int, isAd: Int, now: Long = System.currentTimeMillis())

    // Price History
    @Query("SELECT * FROM price_history ORDER BY sampleCount DESC")
    fun getAllPriceHistory(): Flow<List<PriceHistoryRecord>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertPriceHistory(record: PriceHistoryRecord): Long

    @Query("SELECT * FROM price_history WHERE keyword LIKE '%' || :query || '%' LIMIT 1")
    suspend fun findPriceHistoryByKeyword(query: String): PriceHistoryRecord?
}
