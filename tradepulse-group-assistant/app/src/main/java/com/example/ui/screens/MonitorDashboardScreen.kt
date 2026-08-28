package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Message
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.RadioButtonChecked
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.ShoppingBag
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.data.model.GroupMonitor
import com.example.ui.TradeUiState
import com.example.ui.components.FloatingAssistantOverlay
import com.example.ui.components.StatCard
import com.example.ui.theme.AmberAlert
import com.example.ui.theme.GreenTrade
import com.example.ui.theme.PrimaryBlue
import com.example.ui.theme.QQBlue
import com.example.ui.theme.RedAdAlert
import com.example.ui.theme.WeChatGreen

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MonitorDashboardScreen(
    uiState: TradeUiState,
    onSimulateClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val totalMessages = uiState.tradeItems.size
    val validMessages = uiState.filteredTradeItems.size
    val adMessagesCount = uiState.adItems.size
    val adRatioPercent = if (totalMessages > 0) (adMessagesCount * 100 / totalMessages) else 0
    val matchedAlertsCount = uiState.matchedAlertItems.size

    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            Spacer(modifier = Modifier.height(8.dp))
            // Floating Assistant Status Bar Banner
            FloatingAssistantOverlay(
                isListening = uiState.isFloatingAssistantActive,
                totalMessagesCount = totalMessages,
                adFilteredCount = adMessagesCount,
                onSimulateClick = onSimulateClick
            )
        }

        // Section Title: KPI Stats
        item {
            Text(
                text = "可视化监控看板",
                style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold)
            )
            Text(
                text = "微信与QQ群消息实时抓取、智能清洗及交易匹配概览",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        // KPI Grid
        item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    StatCard(
                        title = "解析群消息总数",
                        value = "$totalMessages 条",
                        subtitle = "包含微信/QQ 4个社群",
                        icon = Icons.Default.Message,
                        iconTint = PrimaryBlue,
                        containerColor = PrimaryBlue.copy(alpha = 0.15f),
                        modifier = Modifier.weight(1f)
                    )
                    StatCard(
                        title = "清除广告比率",
                        value = "$adRatioPercent %",
                        subtitle = "共拦截 $adMessagesCount 条垃圾信息",
                        icon = Icons.Default.Block,
                        iconTint = RedAdAlert,
                        containerColor = RedAdAlert.copy(alpha = 0.15f),
                        modifier = Modifier.weight(1f)
                    )
                }

                Row(
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    StatCard(
                        title = "二手有效盘单",
                        value = "${uiState.tradeItems.size - adMessagesCount} 单",
                        subtitle = "可直接一键私信交易",
                        icon = Icons.Default.ShoppingBag,
                        iconTint = GreenTrade,
                        containerColor = GreenTrade.copy(alpha = 0.15f),
                        modifier = Modifier.weight(1f)
                    )
                    StatCard(
                        title = "触发实时提醒",
                        value = "$matchedAlertsCount 次",
                        subtitle = "包含电动车/考研教材等",
                        icon = Icons.Default.NotificationsActive,
                        iconTint = AmberAlert,
                        containerColor = AmberAlert.copy(alpha = 0.15f),
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        }

        // Section: Monitored Groups
        item {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = "受控微信与QQ社群列表 (${uiState.groupMonitors.size})",
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                )
                Surface(
                    color = MaterialTheme.colorScheme.primaryContainer,
                    shape = RoundedCornerShape(6.dp)
                ) {
                    Text(
                        text = "自动对接中",
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                    )
                }
            }
        }

        items(uiState.groupMonitors) { group ->
            GroupMonitorCard(group = group)
        }

        // Hot Categories Heatmap
        item {
            Card(
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "热门二手关键词分布",
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                    )
                    Spacer(modifier = Modifier.height(10.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        val hotTags = listOf(
                            "二手电动车 (34%)" to PrimaryBlue,
                            "考研/高数教材 (28%)" to GreenTrade,
                            "iPad/MacBook (18%)" to AmberAlert,
                            "宿舍风扇/台灯 (12%)" to Color(0xFF8E24AA),
                            "羽毛球拍/健身 (8%)" to Color(0xFFD81B60)
                        )

                        hotTags.forEach { (tag, color) ->
                            Surface(
                                color = color.copy(alpha = 0.15f),
                                shape = RoundedCornerShape(8.dp)
                            ) {
                                Text(
                                    text = tag,
                                    color = color,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                                )
                            }
                        }
                    }
                }
            }
        }

        item { Spacer(modifier = Modifier.height(16.dp)) }
    }
}

@Composable
fun GroupMonitorCard(group: GroupMonitor) {
    Card(
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.weight(1f)) {
                val platformColor = if (group.platform == "WeChat") WeChatGreen else QQBlue
                val platformName = if (group.platform == "WeChat") "微信" else "QQ"

                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(platformColor.copy(alpha = 0.15f)),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        imageVector = Icons.Default.Groups,
                        contentDescription = "群聊",
                        tint = platformColor,
                        modifier = Modifier.size(22.dp)
                    )
                }

                Spacer(modifier = Modifier.width(12.dp))

                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = group.groupName,
                            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                            maxLines = 1
                        )
                    }
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "成员: ${group.memberCount}人 | 消息: ${group.totalMessages}条 | 广告拦截: ${group.adMessages}条",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            Surface(
                color = if (group.isListening) GreenTrade.copy(alpha = 0.15f) else Color.Gray.copy(alpha = 0.15f),
                shape = RoundedCornerShape(6.dp)
            ) {
                Text(
                    text = if (group.isListening) "监听中" else "已关停",
                    color = if (group.isListening) GreenTrade else Color.Gray,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                )
            }
        }
    }
}
