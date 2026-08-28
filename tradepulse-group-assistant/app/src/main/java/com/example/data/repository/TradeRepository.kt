package com.example.data.repository

import com.example.data.local.TradeDao
import com.example.data.model.AlertRule
import com.example.data.model.GroupMonitor
import com.example.data.model.ParsedTradeItem
import com.example.data.model.PriceHistoryRecord
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first

class TradeRepository(
    private val tradeDao: TradeDao,
    private val parserService: GeminiParserService
) {

    val allTradeItems: Flow<List<ParsedTradeItem>> = tradeDao.getAllTradeItems()
    val validTradeItems: Flow<List<ParsedTradeItem>> = tradeDao.getValidTradeItems()
    val adTradeItems: Flow<List<ParsedTradeItem>> = tradeDao.getAdTradeItems()
    val matchedAlertItems: Flow<List<ParsedTradeItem>> = tradeDao.getMatchedAlertItems()

    val alertRules: Flow<List<AlertRule>> = tradeDao.getAllRules()
    val groupMonitors: Flow<List<GroupMonitor>> = tradeDao.getAllGroupMonitors()
    val priceHistoryRecords: Flow<List<PriceHistoryRecord>> = tradeDao.getAllPriceHistory()

    suspend fun processAndSaveMessage(
        rawMessage: String,
        groupName: String,
        platform: String,
        senderName: String
    ): ParsedTradeItem {
        val parsed = parserService.parseGroupMessage(rawMessage, groupName, platform, senderName)

        // Check if matches active alert rules
        val activeRules = tradeDao.getActiveRulesSync()
        var matchedKeyword: String? = null

        if (!parsed.isAd) {
            for (rule in activeRules) {
                val matchesKeyword = parsed.rawMessage.contains(rule.keyword, ignoreCase = true) ||
                        parsed.title.contains(rule.keyword, ignoreCase = true)
                val matchesCategory = rule.category == "全部" || parsed.category == rule.category
                val matchesPlatform = rule.platformFilter == "全部" || parsed.platform == rule.platformFilter
                val matchesMaxPrice = rule.maxPrice == null || parsed.price <= rule.maxPrice
                val matchesMinPrice = rule.minPrice == null || parsed.price >= rule.minPrice

                if (matchesKeyword && matchesCategory && matchesPlatform && matchesMaxPrice && matchesMinPrice) {
                    matchedKeyword = rule.keyword
                    break
                }
            }
        }

        val finalItem = parsed.copy(matchedRuleKeyword = matchedKeyword)
        val insertedId = tradeDao.insertTradeItem(finalItem)

        // Update group statistics
        tradeDao.updateGroupStats(
            groupName = groupName,
            isTrade = if (!parsed.isAd) 1 else 0,
            isAd = if (parsed.isAd) 1 else 0
        )

        return finalItem.copy(id = insertedId.toInt())
    }

    suspend fun addAlertRule(rule: AlertRule) {
        tradeDao.insertRule(rule)
    }

    suspend fun deleteAlertRule(id: Int) {
        tradeDao.deleteRule(id)
    }

    suspend fun toggleAlertRule(rule: AlertRule) {
        tradeDao.updateRule(rule.copy(isEnabled = !rule.isEnabled))
    }

    suspend fun toggleFavorite(item: ParsedTradeItem) {
        tradeDao.updateTradeItem(item.copy(isFavorite = !item.isFavorite))
    }

    suspend fun addGroupMonitor(group: GroupMonitor) {
        tradeDao.insertGroupMonitor(group)
    }

    suspend fun addPriceHistoryRecord(record: PriceHistoryRecord) {
        tradeDao.insertPriceHistory(record)
    }

    suspend fun seedInitialDataIfEmpty() {
        val existingItems = tradeDao.getAllTradeItems().first()
        if (existingItems.isNotEmpty()) return

        // 1. Initial Group Monitors
        val initialGroups = listOf(
            GroupMonitor(
                groupName = "浙大紫金港二手电车交流①群",
                platform = "WeChat",
                memberCount = 498,
                totalMessages = 1240,
                tradeMessages = 890,
                adMessages = 350
            ),
            GroupMonitor(
                groupName = "清华/北大二手教材软硬件QQ置换群",
                platform = "QQ",
                memberCount = 1890,
                totalMessages = 3420,
                tradeMessages = 2800,
                adMessages = 620
            ),
            GroupMonitor(
                groupName = "复旦毕业季数码电工大甩卖微信群",
                platform = "WeChat",
                memberCount = 475,
                totalMessages = 980,
                tradeMessages = 710,
                adMessages = 270
            ),
            GroupMonitor(
                groupName = "上交大宿舍神器&电瓶车转让②群",
                platform = "WeChat",
                memberCount = 500,
                totalMessages = 1560,
                tradeMessages = 1120,
                adMessages = 440
            )
        )
        for (g in initialGroups) {
            tradeDao.insertGroupMonitor(g)
        }

        // 2. Initial Alert Rules
        val initialRules = listOf(
            AlertRule(keyword = "二手电动车", category = "电动车", maxPrice = 1200.0, platformFilter = "全部"),
            AlertRule(keyword = "考研教材", category = "二手教材", maxPrice = 80.0, platformFilter = "全部"),
            AlertRule(keyword = "iPad", category = "3C数码", maxPrice = 2200.0, platformFilter = "WeChat")
        )
        for (r in initialRules) {
            tradeDao.insertRule(r)
        }

        // 3. Initial Price History Records
        val initialPriceHistory = listOf(
            PriceHistoryRecord(
                keyword = "二手电动车",
                category = "电动车",
                avgPrice = 820.0,
                minPrice = 450.0,
                maxPrice = 1800.0,
                sampleCount = 342,
                trendTag = "供需两旺 价格小幅上涨 3%",
                priceHistoryData = "780,790,810,800,830,820,850"
            ),
            PriceHistoryRecord(
                keyword = "高数/考研教材",
                category = "二手教材",
                avgPrice = 35.0,
                minPrice = 10.0,
                maxPrice = 85.0,
                sampleCount = 612,
                trendTag = "开学季热销 均价35元",
                priceHistoryData = "25,30,32,38,42,36,35"
            ),
            PriceHistoryRecord(
                keyword = "iPad Air/Pro",
                category = "3C数码",
                avgPrice = 2150.0,
                minPrice = 1200.0,
                maxPrice = 4500.0,
                sampleCount = 188,
                trendTag = "保值率高 低于2000元极速成交",
                priceHistoryData = "2300,2250,2200,2180,2150,2120,2150"
            ),
            PriceHistoryRecord(
                keyword = "人体工学椅/宿舍椅",
                category = "宿舍用品",
                avgPrice = 95.0,
                minPrice = 30.0,
                maxPrice = 280.0,
                sampleCount = 215,
                trendTag = "毕业季大降价 适合捡漏",
                priceHistoryData = "140,130,120,110,100,90,95"
            )
        )
        for (ph in initialPriceHistory) {
            tradeDao.insertPriceHistory(ph)
        }

        // 4. Sample Group Messages (Simulated real-time parsed campus records)
        val sampleMessages = listOf(
            Quadruple(
                "[出售] 九号N70C电动车，95新，跑了1200公里，电池健康98%，带原装充电器和头盔。850元可小刀，紫金港翠柏5舍看车自提。微信: wxid_ebike998",
                "浙大紫金港二手电车交流①群",
                "WeChat",
                "学长小王"
            ),
            Quadruple(
                "出全套考研数学一复习全书+张宇1000题（仅写了几页）+李永乐线代讲义，打包45元，附赠电子版讲义。玉泉3舍自取。QQ: 849201938",
                "清华/北大二手教材软硬件QQ置换群",
                "QQ",
                "研一学姐"
            ),
            Quadruple(
                "【代写论文/网课刷课】专业高校团队，低至30元/千字，加微领10元无门槛优惠券！微: lw_daixie666",
                "浙大紫金港二手电车交流①群",
                "WeChat",
                "论文助手小张"
            ),
            Quadruple(
                "求购一个二手iPad Air 5 64G或者256G，预算2000左右，要求无修无拆，面交。微信: ipad_seeker",
                "复旦毕业季数码电工大甩卖微信群",
                "WeChat",
                "张同学"
            ),
            Quadruple(
                "出宿舍小冰箱一个，冷藏冷冻正常，夏天冻可乐神器，80块钱拿走，自提。电话: <PHONE_EXAMPLE>",
                "上交大宿舍神器&电瓶车转让②群",
                "WeChat",
                "毕业生老刘"
            ),
            Quadruple(
                "出九成新雅马哈折叠电动车，含发票电瓶，原价2200现出650元，急出！微信: yamaha_zju",
                "浙大紫金港二手电车交流①群",
                "WeChat",
                "陈学长"
            ),
            Quadruple(
                "兼职刷单，每日日赚200-500元，手机操作即时到账，无门槛加入QQ群：98120391",
                "清华/北大二手教材软硬件QQ置换群",
                "QQ",
                "兼职客服"
            ),
            Quadruple(
                "出9成新尤尼克斯羽毛球拍弓11，拉线25磅，无塌无撞，280元，西溪校区面交。微信: badmint_pro",
                "复旦毕业季数码电工大甩卖微信群",
                "WeChat",
                "体育委员"
            )
        )

        for ((msg, group, platform, sender) in sampleMessages) {
            processAndSaveMessage(msg, group, platform, sender)
        }
    }
}

private data class Quadruple<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)
