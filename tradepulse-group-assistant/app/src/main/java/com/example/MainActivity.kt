package com.example

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddComment
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShowChart
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.example.ui.TradeViewModel
import com.example.ui.components.QuickContactDialog
import com.example.ui.components.SimulateMessageDialog
import com.example.ui.screens.AlertPushScreen
import com.example.ui.screens.LiveFeedScreen
import com.example.ui.screens.MonitorDashboardScreen
import com.example.ui.screens.PriceTrendsScreen
import com.example.ui.screens.SettingsBotScreen
import com.example.ui.theme.SecondHandAssistantTheme

sealed class Screen(val route: String, val title: String, val icon: ImageVector) {
    object Dashboard : Screen("dashboard", "监控后台", Icons.Default.Dashboard)
    object LiveFeed : Screen("live_feed", "交易盘单", Icons.Default.Forum)
    object Alerts : Screen("alerts", "推送提醒", Icons.Default.NotificationsActive)
    object PriceTrends : Screen("price_trends", "比价报表", Icons.Default.ShowChart)
    object Settings : Screen("settings", "小助手", Icons.Default.Settings)
}

class MainActivity : ComponentActivity() {

    private val viewModel: TradeViewModel by viewModels()

    @OptIn(ExperimentalMaterial3Api::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            SecondHandAssistantTheme {
                val navController = rememberNavController()
                val uiState by viewModel.uiState.collectAsStateWithLifecycle()
                val navBackStackEntry by navController.currentBackStackEntryAsState()
                val currentRoute = navBackStackEntry?.destination?.route ?: Screen.Dashboard.route

                var showSimulateDialog by remember { mutableStateOf(false) }

                Scaffold(
                    topBar = {
                        TopAppBar(
                            title = {
                                Text(
                                    text = "二手交易小助手",
                                    fontWeight = FontWeight.ExtraBold,
                                    fontSize = 19.sp
                                )
                            },
                            actions = {
                                IconButton(onClick = { showSimulateDialog = true }) {
                                    Icon(
                                        imageVector = Icons.Default.AddComment,
                                        contentDescription = "模拟抓取",
                                        tint = MaterialTheme.colorScheme.primary
                                    )
                                }
                            },
                            colors = TopAppBarDefaults.topAppBarColors(
                                containerColor = MaterialTheme.colorScheme.surface
                            )
                        )
                    },
                    bottomBar = {
                        NavigationBar(
                            containerColor = MaterialTheme.colorScheme.surface
                        ) {
                            val items = listOf(
                                Screen.Dashboard,
                                Screen.LiveFeed,
                                Screen.Alerts,
                                Screen.PriceTrends,
                                Screen.Settings
                            )

                            items.forEach { screen ->
                                NavigationBarItem(
                                    icon = { Icon(screen.icon, contentDescription = screen.title) },
                                    label = { Text(screen.title) },
                                    selected = currentRoute == screen.route,
                                    onClick = {
                                        navController.navigate(screen.route) {
                                            popUpTo(navController.graph.findStartDestination().id) {
                                                saveState = true
                                            }
                                            launchSingleTop = true
                                            restoreState = true
                                        }
                                    }
                                )
                            }
                        }
                    }
                ) { innerPadding ->
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(innerPadding)
                    ) {
                        NavHost(
                            navController = navController,
                            startDestination = Screen.Dashboard.route
                        ) {
                            composable(Screen.Dashboard.route) {
                                MonitorDashboardScreen(
                                    uiState = uiState,
                                    onSimulateClick = { showSimulateDialog = true }
                                )
                            }

                            composable(Screen.LiveFeed.route) {
                                LiveFeedScreen(
                                    uiState = uiState,
                                    onSearchChange = { viewModel.onSearchQueryChanged(it) },
                                    onCategoryChange = { viewModel.onCategorySelected(it) },
                                    onPlatformChange = { viewModel.onPlatformSelected(it) },
                                    onTradeTypeChange = { viewModel.onTradeTypeSelected(it) },
                                    onShowAdsToggle = { viewModel.onToggleShowAds(it) },
                                    onContactClick = { viewModel.onSelectQuickContact(it) },
                                    onFavoriteToggle = { viewModel.onToggleFavorite(it) },
                                    onSimulateClick = { showSimulateDialog = true }
                                )
                            }

                            composable(Screen.Alerts.route) {
                                AlertPushScreen(
                                    uiState = uiState,
                                    onAddRule = { kw, cat, maxP, plat ->
                                        viewModel.onAddAlertRule(kw, cat, maxP, plat)
                                    },
                                    onDeleteRule = { viewModel.onDeleteAlertRule(it) },
                                    onToggleRule = { viewModel.onToggleAlertRule(it) },
                                    onContactClick = { viewModel.onSelectQuickContact(it) },
                                    onFavoriteToggle = { viewModel.onToggleFavorite(it) }
                                )
                            }

                            composable(Screen.PriceTrends.route) {
                                PriceTrendsScreen(uiState = uiState)
                            }

                            composable(Screen.Settings.route) {
                                SettingsBotScreen(
                                    uiState = uiState,
                                    onToggleFloatingAssistant = { viewModel.onToggleFloatingAssistant(it) },
                                    onSimulateClick = { showSimulateDialog = true }
                                )
                            }
                        }
                    }

                    // Quick Contact Dialog
                    uiState.quickContactItem?.let { item ->
                        QuickContactDialog(
                            item = item,
                            quickMessageTemplate = viewModel.generateQuickReplyMessage(item),
                            onDismiss = { viewModel.onSelectQuickContact(null) }
                        )
                    }

                    // Message Simulation Dialog
                    if (showSimulateDialog) {
                        SimulateMessageDialog(
                            onSimulate = { rawMsg, group, platform, sender ->
                                viewModel.onSimulateMessage(rawMsg, group, platform, sender)
                            },
                            onDismiss = { showSimulateDialog = false }
                        )
                    }
                }
            }
        }
    }
}
