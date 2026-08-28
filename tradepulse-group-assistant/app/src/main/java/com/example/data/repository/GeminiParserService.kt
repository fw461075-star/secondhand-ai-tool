package com.example.data.repository

import android.util.Log
import com.example.BuildConfig
import com.example.data.model.ParsedTradeItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

class GeminiParserService {

    private val okHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .build()

    suspend fun parseGroupMessage(
        rawMessage: String,
        groupName: String,
        platform: String,
        senderName: String
    ): ParsedTradeItem = withContext(Dispatchers.IO) {
        val apiKey = BuildConfig.GEMINI_API_KEY
        if (!apiKey.isNullOrBlank() && apiKey != "MY_GEMINI_API_KEY") {
            try {
                val aiParsed = callGeminiForParsing(apiKey, rawMessage)
                if (aiParsed != null) {
                    return@withContext aiParsed.copy(
                        rawMessage = rawMessage,
                        groupName = groupName,
                        platform = platform,
                        senderName = senderName
                    )
                }
            } catch (e: Exception) {
                Log.e("GeminiParserService", "Gemini API parsing failed, falling back to regex: ${e.message}")
            }
        }
        // Fallback to local rule-based parsing
        return@withContext parseWithLocalRules(rawMessage, groupName, platform, senderName)
    }

    private fun callGeminiForParsing(apiKey: String, messageText: String): ParsedTradeItem? {
        val url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=$apiKey"

        val prompt = """
            你是一个校园二手交易群消息智能解析小助手。请解析以下群聊天消息，识别是否为垃圾广告，并提取二手交易的关键字段。
            
            消息原文：
            "$messageText"
            
            请严格输出标准的JSON格式，包含以下字段：
            {
              "isAd": true或false,
              "adReason": "如果为广告则填写过滤原因（如代写/兼职/涉黄/虚假推广），否则填写null",
              "title": "物品简洁名称（如：九号电动车N70C / 考研数学一复习全书 / iPad Air 5）",
              "category": "类别（必须是以下之一：电动车、二手教材、3C数码、宿舍用品、运动健身、服饰美妆、其他）",
              "tradeType": "出售 或 求购",
              "price": 提取出的数字价格（如850.0，若面议或未指明填0.0）,
              "priceText": "价格描述（如：850元可小刀 / 12元/本 / 面议）",
              "condition": "成色描述（如：九成新 / 仅拆封 / 八成新 / 闲置）",
              "contactInfo": "提取出的微信号/QQ号/手机号/交易方式",
              "contactType": "WeChat 或 QQ 或 Phone 或 Unknown",
              "location": "校区楼栋或交易地点（如：紫金港翠柏5舍 / 玉泉食堂门口，若未指明填校区内面交）"
            }
        """.trimIndent()

        val jsonPayload = JSONObject().apply {
            put("contents", org.json.JSONArray().apply {
                put(JSONObject().apply {
                    put("parts", org.json.JSONArray().apply {
                        put(JSONObject().apply { put("text", prompt) })
                    })
                })
            })
            put("generationConfig", JSONObject().apply {
                put("responseMimeType", "application/json")
                put("temperature", 0.1)
            })
        }

        val request = Request.Builder()
            .url(url)
            .post(jsonPayload.toString().toRequestBody("application/json".toMediaType()))
            .build()

        val response = okHttpClient.newCall(request).execute()
        val responseBody = response.body?.string() ?: return null

        if (!response.isSuccessful) return null

        val responseJson = JSONObject(responseBody)
        val candidates = responseJson.optJSONArray("candidates") ?: return null
        if (candidates.length() == 0) return null

        val content = candidates.getJSONObject(0).optJSONObject("content") ?: return null
        val parts = content.optJSONArray("parts") ?: return null
        if (parts.length() == 0) return null

        val text = parts.getJSONObject(0).optString("text")
        val parsedJson = JSONObject(text)

        val isAd = parsedJson.optBoolean("isAd", false)
        val adReason = if (parsedJson.isNull("adReason")) null else parsedJson.optString("adReason")
        val title = parsedJson.optString("title", "二手物品")
        val category = parsedJson.optString("category", "其他")
        val tradeType = parsedJson.optString("tradeType", "出售")
        val price = parsedJson.optDouble("price", 0.0)
        val priceText = parsedJson.optString("priceText", if (price > 0) "${price.toInt()}元" else "面议")
        val condition = parsedJson.optString("condition", "良好")
        val contactInfo = parsedJson.optString("contactInfo", "群内私信联系")
        val contactType = parsedJson.optString("contactType", "Unknown")
        val location = parsedJson.optString("location", "校内面交")

        return ParsedTradeItem(
            rawMessage = messageText,
            groupName = "",
            platform = "",
            senderName = "",
            title = title,
            category = category,
            tradeType = tradeType,
            price = price,
            priceText = priceText,
            condition = condition,
            contactInfo = contactInfo,
            contactType = contactType,
            location = location,
            isAd = isAd,
            adReason = adReason
        )
    }

    fun parseWithLocalRules(
        rawMessage: String,
        groupName: String,
        platform: String,
        senderName: String
    ): ParsedTradeItem {
        // 1. Ad Detection Rules
        val adKeywords = listOf(
            "代写", "论文", "网课", "刷单", "日赚", "兼职", "高薪", "加微领", "免费领取",
            "彩票", "网赚", "挂机", "搬砖", "创业", "开店", "无门槛", "贷款", "花呗", "信用卡"
        )
        var isAd = false
        var adReason: String? = null

        for (kw in adKeywords) {
            if (rawMessage.contains(kw)) {
                isAd = true
                adReason = "匹配广告违规关键词: 【$kw】"
                break
            }
        }

        // 2. Category & Title Detection
        var category = "其他"
        var title = "二手物品"

        when {
            rawMessage.containsAny("电动车", "电瓶车", "小牛", "九号", "爱玛", "雅马哈", "折叠车", "电驴", "头盔", "充电器") -> {
                category = "电动车"
                title = extractTitleByKeywords(rawMessage, listOf("小牛", "九号", "爱玛", "雅马哈", "电动车", "电瓶车")) ?: "二手电动车/配件"
            }
            rawMessage.containsAny("教材", "高数", "考研", "英语四六级", "课本", "考公", "资料", "笔记", "复习", "全书", "线性代数", "概率论") -> {
                category = "二手教材"
                title = extractTitleByKeywords(rawMessage, listOf("高数", "考研", "四六级", "线性代数", "概率论", "考公", "教材", "课本")) ?: "二手教材复习资料"
            }
            rawMessage.containsAny("iPad", "MacBook", "iPhone", "耳机", "显卡", "键盘", "充电宝", "平板", "电脑", "PS5", "Switch", "显示器", "鼠标") -> {
                category = "3C数码"
                title = extractTitleByKeywords(rawMessage, listOf("iPad", "MacBook", "iPhone", "PS5", "Switch", "显示器", "耳机", "键盘", "充电宝")) ?: "3C数码电子设备"
            }
            rawMessage.containsAny("台灯", "宿舍", "风扇", "收纳盒", "洗衣机", "晾衣架", "电热毯", "烧水壶", "椅子", "桌子", "窗帘") -> {
                category = "宿舍用品"
                title = extractTitleByKeywords(rawMessage, listOf("台灯", "风扇", "洗衣机", "收纳盒", "电热毯", "椅子", "桌子")) ?: "宿舍生活用品"
            }
            rawMessage.containsAny("羽毛球", "篮球", "健身", "哑铃", "滑板", "瑜伽", "网球", "球拍", "网球拍") -> {
                category = "运动健身"
                title = extractTitleByKeywords(rawMessage, listOf("羽毛球拍", "篮球", "哑铃", "滑板", "瑜伽垫", "球拍")) ?: "运动健身器材"
            }
            rawMessage.containsAny("羽绒服", "球鞋", "外套", "护肤品", "面膜", "香水", "口红", "包包", "衣服") -> {
                category = "服饰美妆"
                title = extractTitleByKeywords(rawMessage, listOf("羽绒服", "球鞋", "外套", "面膜", "香水", "包包")) ?: "二手服饰美妆"
            }
        }

        if (title == "二手物品" && rawMessage.length > 4) {
            title = rawMessage.take(20).replace("\n", " ")
        }

        // 3. Trade Type
        val tradeType = if (rawMessage.containsAny("求购", "收一个", "需要", "有卖的吗", "重金求", "收二手的")) "求购" else "出售"

        // 4. Price Extraction
        var price = 0.0
        var priceText = "面议"

        val pricePattern = Pattern.compile("(\\d+(\\.\\d+)?)\\s*(元|块|RMB|rmb|¥|💰)")
        val matcher = pricePattern.matcher(rawMessage)
        if (matcher.find()) {
            price = matcher.group(1)?.toDoubleOrNull() ?: 0.0
            priceText = "${price.toInt()}元"
            if (rawMessage.contains("小刀")) priceText += " (可小刀)"
        } else {
            val symbolPattern = Pattern.compile("[¥💰]\\s*(\\d+(\\.\\d+)?)")
            val symMatcher = symbolPattern.matcher(rawMessage)
            if (symMatcher.find()) {
                price = symMatcher.group(1)?.toDoubleOrNull() ?: 0.0
                priceText = "${price.toInt()}元"
            } else {
                val num出Pattern = Pattern.compile("(\\d{2,5})\\s*出")
                val numMatcher = num出Pattern.matcher(rawMessage)
                if (numMatcher.find()) {
                    price = numMatcher.group(1)?.toDoubleOrNull() ?: 0.0
                    priceText = "${price.toInt()}元"
                }
            }
        }

        // 5. Condition
        val condition = when {
            rawMessage.containsAny("全新", "未拆", "仅拆") -> "全新"
            rawMessage.containsAny("九成新", "9成新", "95新", "99新") -> "九成新"
            rawMessage.containsAny("八成新", "8成新", "85新") -> "八成新"
            else -> "良好"
        }

        // 6. Contact Extraction
        var contactInfo = "群内联系: $senderName"
        var contactType = "Unknown"

        val wxPattern = Pattern.compile("(微信|vx|WX|Wx|wx):?\\s*([a-zA-Z0-9_-]{5,20})")
        val wxMatcher = wxPattern.matcher(rawMessage)
        if (wxMatcher.find()) {
            val wxId = wxMatcher.group(2)
            contactInfo = "微信: $wxId"
            contactType = "WeChat"
        } else {
            val qqPattern = Pattern.compile("(QQ|qq|扣扣):?\\s*([1-9][0-9]{4,11})")
            val qqMatcher = qqPattern.matcher(rawMessage)
            if (qqMatcher.find()) {
                val qqId = qqMatcher.group(2)
                contactInfo = "QQ: $qqId"
                contactType = "QQ"
            } else {
                val phonePattern = Pattern.compile("(1[3-9]\\d{9})")
                val phoneMatcher = phonePattern.matcher(rawMessage)
                if (phoneMatcher.find()) {
                    val phone = phoneMatcher.group(1)
                    contactInfo = "电话: $phone"
                    contactType = "Phone"
                }
            }
        }

        // 7. Location
        val location = when {
            rawMessage.contains("紫金港") -> "紫金港校区"
            rawMessage.contains("玉泉") -> "玉泉校区"
            rawMessage.contains("西溪") -> "西溪校区"
            rawMessage.contains("华家池") -> "华家池校区"
            rawMessage.contains("宿舍") || rawMessage.contains("舍") -> "校内宿舍面交"
            else -> "校内面交/自提"
        }

        return ParsedTradeItem(
            rawMessage = rawMessage,
            groupName = groupName,
            platform = platform,
            senderName = senderName,
            title = title,
            category = category,
            tradeType = tradeType,
            price = price,
            priceText = priceText,
            condition = condition,
            contactInfo = contactInfo,
            contactType = contactType,
            location = location,
            isAd = isAd,
            adReason = adReason
        )
    }

    private fun extractTitleByKeywords(text: String, keywords: List<String>): String? {
        val lines = text.split("\n", "，", ",", "。")
        for (line in lines) {
            for (kw in keywords) {
                if (line.contains(kw)) {
                    val clean = line.trim().take(22)
                    if (clean.length >= 3) return clean
                }
            }
        }
        return null
    }

    private fun String.containsAny(vararg keywords: String): Boolean {
        return keywords.any { this.contains(it, ignoreCase = true) }
    }
}
