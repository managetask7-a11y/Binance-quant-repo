(function () {
    var REFRESH_MS = 5000;
    var nextScanISO = null;
    var countdownInterval = null;

    function $(id) { return document.getElementById(id); }

    function formatUSD(v) {
        var n = parseFloat(v);
        if (isNaN(n)) return "$--";
        return (n >= 0 ? "+$" : "-$") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    window.formatUSD = formatUSD;

    function formatPrice(v) {
        var n = parseFloat(v);
        if (isNaN(n)) return "--";
        if (n >= 1000) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        if (n >= 1) return n.toFixed(4);
        return n.toFixed(6);
    }

    function formatPct(v) {
        var n = parseFloat(v);
        if (isNaN(n)) return "--%";
        return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
    }

    function pnlClass(v) {
        var n = parseFloat(v);
        if (isNaN(n)) return "";
        return n >= 0 ? "pnl-positive" : "pnl-negative";
    }

    function metricClass(v) {
        var n = parseFloat(v);
        if (isNaN(n)) return "";
        return n >= 0 ? "positive" : "negative";
    }

    function reasonTag(reason) {
        if (!reason) return "";
        var r = reason.toUpperCase();
        var cls = "reason-tag ";
        if (r.includes("TAKE_PROFIT")) cls += "reason-tp";
        else if (r.includes("BREAKEVEN")) cls += "reason-be";
        else if (r.includes("MANUAL")) cls += "reason-manual";
        else if (r.includes("TRAILING")) cls += "reason-trailing";
        else if (r.includes("STOP_LOSS")) cls += "reason-sl";
        else if (r.includes("MAX_HOLD")) cls += "reason-time";
        else cls += "reason-stop";
        return '<span class="' + cls + '">' + reason + '</span>';
    }

    function strategyTags(str) {
        if (!str) return "";
        return str.split(",").map(function (s) {
            return '<span class="strat-tag">' + s.trim() + '</span>';
        }).join("");
    }

    function timeAgo(isoStr) {
        if (!isoStr) return "--";
        var diff = Date.now() - new Date(isoStr).getTime();
        var mins = Math.floor(diff / 60000);
        if (mins < 1) return "just now";
        if (mins < 60) return mins + "m ago";
        var hrs = Math.floor(mins / 60);
        if (hrs < 24) return hrs + "h " + (mins % 60) + "m ago";
        return Math.floor(hrs / 24) + "d ago";
    }

    function startCountdown() {
        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(function () {
            if (!nextScanISO) {
                $("nextScanCountdown").textContent = "--:--";
                return;
            }
            var remain = new Date(nextScanISO).getTime() - Date.now();
            if (remain <= 0) {
                $("nextScanCountdown").textContent = "SCANNING...";
                return;
            }
            var m = Math.floor(remain / 60000);
            var s = Math.floor((remain % 60000) / 1000);
            $("nextScanCountdown").textContent = String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
        }, 1000);
    }

    async function closeTrade(symbol) {
        var btn = document.querySelector('[data-symbol="' + symbol + '"]');
        if (btn) { btn.disabled = true; btn.textContent = "Closing..."; }
        var result = await postJSON("/api/trades/close", { symbol: symbol });
        if (result && result.success) {
            refresh();
        } else {
            if (btn) { btn.disabled = false; btn.textContent = "EXIT"; }
            alert("Failed to close " + symbol + ": " + (result ? result.error : "Network error"));
        }
    }

    window.closeTrade = closeTrade;

    async function logoutUser() {
        if (!confirm("Are you sure you want to log out?")) return;
        var res = await fetch("/auth/logout", { method: "POST" });
        if (res.ok) {
            window.location.href = "/auth/login";
        }
    }

    window.logoutUser = logoutUser;

    function selectMode(mode) {
        var dryBtn = $("setModeDry");
        var liveBtn = $("setModeLive");
        var input = $("selectedMode");

        input.value = mode;
        if (mode === "live") {
            liveBtn.className = "py-2.5 rounded-[10px] text-sm font-semibold border border-accent-cyan transition-all cursor-pointer bg-accent-cyan/10 text-accent-cyan";
            dryBtn.className = "py-2.5 rounded-[10px] text-sm font-semibold border border-white/[0.12] transition-all cursor-pointer bg-white/[0.04] text-gray-400";
        } else {
            dryBtn.className = "py-2.5 rounded-[10px] text-sm font-semibold border border-warn transition-all cursor-pointer bg-warn/10 text-warn";
            liveBtn.className = "py-2.5 rounded-[10px] text-sm font-semibold border border-white/[0.12] transition-all cursor-pointer bg-white/[0.04] text-gray-400";
        }
    }

    window.selectMode = selectMode;
    
    function togglePassword(id) {
        var input = $(id);
        if (!input) return;
        if (input.type === "password") {
            input.type = "text";
        } else {
            input.type = "password";
        }
    }
    
    window.togglePassword = togglePassword;

    async function manualResetDaily() {
        if (!confirm("Are you sure you want to reset today's P&L and start a fresh session?")) return;
        
        const btn = $("resetDailyBtn");
        const originalText = btn.innerText;
        btn.disabled = true;
        btn.innerText = "RESETTING...";
        
        try {
            const res = await postJSON("/api/trading/reset_daily", {});
            if (res && res.success) {
                if (window.showToast) window.showToast("Daily stats reset successfully!");
                else alert("Daily stats reset successfully!");
                
                $("targetModalOverlay").classList.remove("active");
                refresh();
            } else {
                alert(res ? res.error : "Reset failed");
            }
        } catch (e) {
            alert("Connection error");
        } finally {
            btn.disabled = false;
            btn.innerText = originalText;
        }
    }
    window.manualResetDaily = manualResetDaily;

    async function manualResetAll() {
        if (!confirm("🚨 WARNING: This will PERMANENTLY WIPE all trade history and equity logs for this account. This cannot be undone.\n\nAre you sure you want to hard reset everything?")) return;
        
        const btn = $("hardResetBtn");
        const originalText = btn.innerText;
        btn.disabled = true;
        btn.innerText = "WIPING EVERYTHING...";
        
        try {
            const res = await postJSON("/api/trading/reset_all", {});
            if (res && res.success) {
                alert("🔥 Total history wiped successfully. Starting with a fresh slate!");
                $("configModalOverlay").classList.remove("active");
                location.reload(); // Hard reload to clear all charts and tables
            } else {
                alert(res ? res.error : "Wipe failed");
            }
        } catch (e) {
            alert("Connection error");
        } finally {
            btn.disabled = false;
            btn.innerText = originalText;
        }
    }
    window.manualResetAll = manualResetAll;

    async function togglePause() {
        var btn = $("pauseResumeBtn");
        var isPaused = btn.textContent.includes("Resume");
        btn.disabled = true;
        
        var url = isPaused ? "/api/trading/resume" : "/api/trading/pause";
        var res = await postJSON(url, {});
        
        if (res && res.success) {
            refresh();
        } else {
            alert("Failed to " + (isPaused ? "resume" : "pause") + " trading.");
        }
        btn.disabled = false;
    }
    window.togglePause = togglePause;

    async function connectBinance() {
        var apiKey = $("connApiKey").value.trim();
        var apiSecret = $("connApiSecret").value.trim();
        var testnet = $("connTestnet").checked;
        var btn = $("connSubmitBtn");
        var err = $("connError");

        if (!apiKey || !apiSecret) {
            err.textContent = "API Key and Secret are required.";
            err.classList.remove("hidden");
            return;
        }

        err.classList.add("hidden");
        btn.disabled = true;
        btn.textContent = "Connecting...";

        var res = await postJSON("/api/broker/connect", {
            api_key: apiKey,
            api_secret: apiSecret,
            testnet: testnet
        });

        btn.disabled = false;
        btn.textContent = "Connect";

        if (res && res.success) {
            $("connApiKey").value = "";
            $("connApiSecret").value = "";
            refreshBrokerStatus();
            refresh();
        } else {
            err.textContent = res ? res.error : "Connection failed.";
            if (res && res.detail) err.textContent += " (" + res.detail + ")";
            err.classList.remove("hidden");
        }
    }
    window.connectBinance = connectBinance;

    async function disconnectBinance() {
        if (!confirm("Disconnect Binance? You will be switched to Dry Run mode.")) return;
        
        var btn = $("connDisconnectBtn");
        btn.disabled = true;
        btn.textContent = "Disconnecting...";

        var res = await postJSON("/api/broker/disconnect", {});
        
        btn.disabled = false;
        btn.textContent = "Disconnect";

        if (res && res.success) {
            refreshBrokerStatus();
            refresh();
        } else {
            alert("Failed to disconnect.");
        }
    }
    window.disconnectBinance = disconnectBinance;

    async function refreshBrokerStatus() {
        var res = await fetchJSON("/api/broker/status");
        if (!res) return;

        var dot = $("connDot");
        var status = $("connStatus");
        var info = $("connLiveInfo");
        var bal = $("connBalance");
        var badge = $("connTestnetBadge");
        var form = $("connForm");
        var disBtn = $("connDisconnectBtn");

        if (res.is_live) {
            dot.style.background = "#10b981"; // profit
            status.textContent = "Connected";
            status.style.color = "#10b981";
            form.classList.add("hidden");
            disBtn.classList.remove("hidden");
            info.classList.remove("hidden");
            bal.textContent = formatUSD(res.live_balance || 0);
            if (res.testnet) {
                badge.textContent = "TESTNET";
            } else {
                badge.textContent = "";
            }
        } else {
            dot.style.background = "#4a5568";
            status.textContent = "Not Connected";
            status.style.color = "#9ca3af";
            form.classList.remove("hidden");
            disBtn.classList.add("hidden");
            info.classList.add("hidden");
        }
    }


    function setupConfigModal() {
        var overlay = $("configModalOverlay");
        var openBtn = $("openConfigModal");
        var closeBtn = $("closeConfigModal");
        var cancelBtn = $("cancelConfig");
        var saveBtn = $("saveConfig");
        var error = $("configError");

        async function openModal() {
            error.classList.add("hidden");
            overlay.classList.add("visible");
            
            // Fetch current config
            var data = await fetchJSON("/api/settings/config");
            if (data) {
                $("cfgTpRatio").value = data.tp_rr_ratio || "";
                $("cfgAtrMult").value = data.atr_mult || "";
                $("cfgRisk").value = data.risk_per_trade || "";
                $("cfgLeverage").value = data.leverage || "";
                $("cfgTgToken").value = data.telegram_bot_token || "";
                $("cfgTgChat").value = data.telegram_chat_id || "";
                $("cfgTopCoins").value = data.top_n_coins || "15";
                $("cfgDailyProfitTarget").value = data.daily_profit_target || "0";
                $("cfgDailyLossLimit").value = data.prop_daily_loss_pct || "25";
            }
        }
        function closeModal() { overlay.classList.remove("visible"); }

        openBtn.addEventListener("click", openModal);
        closeBtn.addEventListener("click", closeModal);
        cancelBtn.addEventListener("click", closeModal);
        overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });

        var defaultBtn = $("useDefaultConfig");
        if (defaultBtn) {
            defaultBtn.addEventListener("click", async function(e) {
                e.preventDefault();
                if (confirm("Reset strategy fields to code defaults? (You must click Save to apply)")) {
                    const resp = await fetch("/api/config/defaults");
                    const data = await resp.json();
                    if (!data.error) {
                        $("cfgTpRatio").value = data.tp_rr_ratio;
                        $("cfgAtrMult").value = data.atr_mult;
                        $("cfgRisk").value = data.risk_per_trade;
                        $("cfgLeverage").value = data.leverage;
                        $("cfgTopCoins").value = data.top_n_coins;
                        if(data.prop_daily_loss_pct) $("cfgDailyLossLimit").value = data.prop_daily_loss_pct;
                        
                        // Flash success text
                        var oldText = this.textContent;
                        this.textContent = "✅ Values loaded (Click Save)";
                        setTimeout(() => { this.textContent = oldText; }, 3000);
                    }
                }
            });
        }

        saveBtn.addEventListener("click", async function () {
            var payload = {
                tp_rr_ratio: $("cfgTpRatio").value,
                atr_mult: $("cfgAtrMult").value,
                risk_per_trade: $("cfgRisk").value,
                leverage: $("cfgLeverage").value,
                top_n_coins: $("cfgTopCoins").value,
                daily_profit_target: $("cfgDailyProfitTarget").value,
                prop_daily_loss_pct: $("cfgDailyLossLimit").value,
                telegram_bot_token: $("cfgTgToken").value,
                telegram_chat_id: $("cfgTgChat").value
            };

            saveBtn.disabled = true;
            saveBtn.textContent = "Saving...";
            
            var res = await postJSON("/api/settings/config", payload);
            
            saveBtn.disabled = false;
            saveBtn.textContent = "Save Strategy";

            if (res && res.success) {
                closeModal();
            } else {
                error.textContent = res ? res.error : "Failed to save configuration.";
                error.classList.remove("hidden");
            }
        });
    }

    function setupSettingsModal() {
        var overlay = $("settingsModalOverlay");
        var openBtn = $("openSettingsModal");
        var closeBtn = $("closeSettingsModal");
        var cancelBtn = $("cancelSettings");
        var saveBtn = $("saveSettings");
        var error = $("settingsError");

        function openModal() {
            overlay.classList.add("visible");
            error.classList.add("hidden");
            var currentMode = $("modeLabel").textContent.trim();
            if (currentMode.includes("LIVE") || currentMode.includes("PAUSED")) {
                selectMode("live");
            } else {
                selectMode("dry_run");
            }
            refreshBrokerStatus();
        }
        function closeModal() { overlay.classList.remove("visible"); }

        openBtn.addEventListener("click", openModal);
        closeBtn.addEventListener("click", closeModal);
        cancelBtn.addEventListener("click", closeModal);
        overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });

        saveBtn.addEventListener("click", async function () {
            var mode = $("selectedMode").value;

            saveBtn.disabled = true;
            saveBtn.textContent = "Applying...";
            
            var res = await postJSON("/api/settings/mode", {
                mode: mode,
                api_key: "",
                api_secret: ""
            });

            saveBtn.disabled = false;
            saveBtn.textContent = "Apply Changes";

            if (res && res.success) {
                closeModal();
                refresh();
            } else {
                error.textContent = res ? res.error : "Failed to update settings.";
                error.classList.remove("hidden");
            }
        });
    }

    function setupTargetModal() {
        var overlay = $("targetModalOverlay");
        var openBtn = $("openTargetModal");
        var closeBtn = $("closeTargetModal");
        var cancelBtn = $("cancelTarget");
        var saveBtn = $("saveTarget");
        var input = $("dailyTargetInput");

        function openModal() { overlay.classList.add("visible"); input.focus(); }
        function closeModal() { overlay.classList.remove("visible"); }

        openBtn.addEventListener("click", openModal);
        closeBtn.addEventListener("click", closeModal);
        cancelBtn.addEventListener("click", closeModal);
        overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });

        saveBtn.addEventListener("click", async function () {
            var val = parseFloat(input.value);
            if (isNaN(val) || val < 0) { input.style.borderColor = "#ef4444"; return; }
            input.style.borderColor = "";
            await postJSON("/api/daily_target", { target: val });
            closeModal();
            refresh();
        });

        input.addEventListener("keydown", function (e) { if (e.key === "Enter") saveBtn.click(); });
    }

    async function updateStatus() {
        var data = await fetchJSON("/api/status");
        if (!data) return;

        $("metricBalance").textContent = "$" + parseFloat(data.balance).toLocaleString("en-US", { minimumFractionDigits: 2 });
        $("metricBalance").className = "metric-value";

        if (data.live_balance !== null && data.live_balance !== undefined) {
            $("metricLiveBalance").textContent = formatUSD(data.live_balance);
            $("metricLiveBalance").className = "metric-value text-accent-cyan";
        } else {
            $("metricLiveBalance").textContent = "N/A";
            $("metricLiveBalance").className = "metric-value text-gray-500";
        }

        var dpnl = parseFloat(data.daily_pnl);
        $("metricDailyPnl").textContent = formatUSD(dpnl);
        $("metricDailyPnl").className = "metric-value " + metricClass(dpnl);

        var modalPnl = $("modalCurrentPnl");
        if (modalPnl) {
            modalPnl.textContent = formatUSD(dpnl);
            modalPnl.className = "font-mono text-base font-bold " + (dpnl >= 0 ? "text-profit" : "text-loss");
        }



        $("metricOpenCount").textContent = data.open_count + "/" + (data.order_cap || data.max_trades);
        $("metricClosedCount").textContent = data.closed_count;
        $("metricLeverage").textContent = data.leverage + "x";
        $("metricRisk").textContent = (data.risk_per_trade * 100).toFixed(0) + "%";

        var pill = $("openSettingsModal"); 
        var label = $("modeLabel");
        var dot = $("statusDot");
        var statusText = "Scanning " + data.scan_limit;
        
        // Update Personality display
        if ($("currentPersonality")) {
            const pers = data.personality || "N/A";
            const reg = data.regime || "N/A";
            $("currentPersonality").textContent = `${reg.toUpperCase()} (${pers})`;
        }

        var pauseBtn = $("pauseResumeBtn");
        pauseBtn.style.display = "flex";
        if (data.paused) {
            pauseBtn.innerHTML = "▶️ Resume";
            pauseBtn.className = "flex items-center gap-1.5 bg-white/[0.04] border border-profit/30 rounded-full px-4 py-[7px] text-[0.75rem] font-semibold tracking-wide text-profit cursor-pointer transition-all hover:bg-profit/10 hover:-translate-y-px";
            
            pill.className = "flex items-center gap-2 bg-surface-700 border border-warn/30 rounded-full px-4 py-1.5 text-[0.75rem] font-semibold tracking-wider text-warn cursor-pointer hover:bg-surface-600 transition-all hover:border-white/20";
            dot.className = "w-2 h-2 rounded-full bg-warn";
            dot.style.animation = "none";
            label.textContent = "PAUSED";
        } else {
            pauseBtn.innerHTML = "⏸ Pause";
            pauseBtn.className = "flex items-center gap-1.5 bg-white/[0.04] border border-warn/30 rounded-full px-4 py-[7px] text-[0.75rem] font-semibold tracking-wide text-warn cursor-pointer transition-all hover:bg-warn/10 hover:-translate-y-px";
            
            var modeStr = data.dry_run ? "DRY RUN | " : (data.testnet ? "TESTNET | " : "LIVE | ");
            if (data.daily_target_reached) {
                pill.className = "flex items-center gap-2 bg-surface-700 border border-warn/30 rounded-full px-4 py-1.5 text-[0.75rem] font-semibold tracking-wider text-warn cursor-pointer hover:bg-surface-600 transition-all hover:border-white/20";
                dot.className = "w-2 h-2 rounded-full bg-warn";
                dot.style.animation = "pulse-anim 2s ease-in-out infinite";
                label.textContent = modeStr + "TARGET MET | " + statusText;
            } else if (data.dry_run) {
                pill.className = "flex items-center gap-2 bg-surface-700 border border-warn/30 rounded-full px-4 py-1.5 text-[0.75rem] font-semibold tracking-wider text-warn cursor-pointer hover:bg-surface-600 transition-all hover:border-white/20";
                dot.className = "w-2 h-2 rounded-full bg-warn";
                dot.style.animation = "pulse-anim 2s ease-in-out infinite";
                label.textContent = modeStr + statusText;
            } else {
                pill.className = "flex items-center gap-2 bg-surface-700 border border-profit/30 rounded-full px-4 py-1.5 text-[0.75rem] font-semibold tracking-wider text-profit cursor-pointer hover:bg-surface-600 transition-all hover:border-white/20";
                dot.className = "w-2 h-2 rounded-full bg-profit";
                dot.style.animation = "pulse-anim 2s ease-in-out infinite";
                label.textContent = modeStr + statusText;
            }
        }

        nextScanISO = data.next_scan;



        var dailyLimit = data.initial_balance * data.prop_daily_loss / 100;
        var dailyUsed = Math.abs(Math.min(dpnl, 0));
        var dailyPct = Math.min(dailyUsed / dailyLimit * 100, 100);
        $("propDailyFill").style.width = dailyPct + "%";
        $("propDailyValue").textContent = "$" + dailyUsed.toFixed(0) + " / $" + dailyLimit.toLocaleString("en-US", { maximumFractionDigits: 0 });

        var targetBar = $("dailyTargetBar");
        var targetBtn = $("openTargetModal");
        var targetBtnLabel = $("targetBtnLabel");
        if (data.daily_profit_target > 0) {
            targetBar.style.display = "block";
            targetBar.classList.remove("hidden");

            var targetPct = Math.min(Math.max(dpnl, 0) / data.daily_profit_target * 100, 100);
            $("propTargetFill").style.width = targetPct + "%";
            $("propTargetValue").textContent = "$" + Math.max(dpnl, 0).toFixed(2) + " / $" + data.daily_profit_target.toFixed(2);

            if (data.daily_target_reached) {
                targetBar.style.borderColor = "rgba(16, 185, 129, 0.3)";
            } else {
                targetBar.style.borderColor = "";
            }

            targetBtnLabel.textContent = "$" + data.daily_profit_target.toFixed(2);
        } else {
            targetBar.style.display = "none";
            targetBtnLabel.textContent = "Set Target";
        }

        $("lastUpdate").textContent = "Last update: " + new Date().toLocaleTimeString();
    }

    async function updateOpenTrades() {
        var trades = await fetchJSON("/api/trades/open");
        if (!trades) return;

        $("openBadge").textContent = trades.length;
        var tbody = $("openTradesBody");

        if (trades.length === 0) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="10">No open positions</td></tr>';
            return;
        }

        tbody.innerHTML = trades.map(function (t) {
            var sideClass = t.direction === "LONG" ? "side-long" : "side-short";
            var pnlCls = pnlClass(t.pnl_pct);
            var distPct = t.sl_dist_pct || 2.0;
            var triggerPrice = t.direction === "LONG"
                ? t.entry_price * (1 + distPct / 100)
                : t.entry_price * (1 - distPct / 100);

            var slSubtext = "";
            if (t.pnl_pct >= distPct) {
                slSubtext = "<div style='font-size:0.65rem; margin-top: 2px; color:#00f0ff; font-weight:bold;'>⚡ Trailing Active</div>";
            } else {
                slSubtext = "<div style='font-size:0.65rem; margin-top: 2px; color:#5a6478;'>Triggers @ " + formatPrice(triggerPrice) + "</div>";
            }

            return '<tr class="data-flash">' +
                "<td>" + t.symbol + "</td>" +
                '<td><span class="' + sideClass + '">' + t.direction + "</span></td>" +
                "<td>" + formatUSD(t.notional) + "</td>" +
                "<td>" + formatPrice(t.entry_price) + "</td>" +
                "<td>" + formatPrice(t.live_price) + "</td>" +
                '<td class="' + pnlCls + '">' + formatPct(t.pnl_pct) + " (" + formatUSD(t.pnl_usd) + ")</td>" +
                "<td>" + formatUSD(t.current_value) + "</td>" +
                "<td><div>" + formatPrice(t.sl_price) + "</div>" + slSubtext + "</td>" +
                "<td>" + formatPrice(t.tp_price) + "</td>" +
                '<td><div class="strategies-tags">' + strategyTags(t.strategies) + "</div></td>" +
                "<td>" + t.scan_count + "/" + t.max_hold + "</td>" +
                '<td><button class="exit-btn" data-symbol="' + t.symbol + '" onclick="closeTrade(\'' + t.symbol + '\')">EXIT</button></td>' +
                "</tr>";
        }).join("");
    }

    async function updateClosedTrades() {
        var trades = await fetchJSON("/api/trades/closed");
        if (!trades) return;

        $("closedBadge").textContent = trades.length;
        var tbody = $("closedTradesBody");

        var closedData = trades;
        if (closedData && closedData.length > 0) {
            var wins = closedData.filter(function (t) { return parseFloat(t.pnl_usd) > 0; }).length;
            var validTrades = closedData.filter(function (t) { return Math.abs(parseFloat(t.pnl_usd)) > 0.001; }).length || 1;
            var wr = (wins / validTrades * 100);
            $("metricWinRate").textContent = wr.toFixed(1) + "%";
            $("metricWinRate").className = "metric-value " + (wr >= 50 ? "positive" : "negative");
        }

        if (trades.length === 0) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="11">No closed trades yet</td></tr>';
            return;
        }

        var recent = trades.slice(-50).reverse();
        tbody.innerHTML = recent.map(function (t) {
            var sideClass = t.direction === "LONG" ? "side-long" : "side-short";
            return "<tr>" +
                "<td>" + t.symbol + "</td>" +
                '<td><span class="' + sideClass + '">' + t.direction + "</span></td>" +
                "<td>" + formatUSD(t.notional) + "</td>" +
                "<td>" + formatPrice(t.entry_price) + "</td>" +
                "<td>" + formatPrice(t.exit_price) + "</td>" +
                "<td style='color:#5a6478'>" + (t.sl_price ? formatPrice(t.sl_price) : "--") + "</td>" +
                "<td style='color:#5a6478'>" + (t.tp_price ? formatPrice(t.tp_price) : "--") + "</td>" +
                '<td class="' + pnlClass(t.pnl_pct) + '">' + formatPct(t.pnl_pct) + "</td>" +
                '<td class="' + pnlClass(t.pnl_usd) + '">' + formatUSD(t.pnl_usd) + "</td>" +
                "<td>" + formatUSD(t.exit_value) + "</td>" +
                "<td>" + reasonTag(t.reason) + "</td>" +
                '<td><div class="strategies-tags">' + strategyTags(t.strategies) + "</div></td>" +
                "<td>" + timeAgo(t.exit_time) + "</td>" +
                "</tr>";
        }).join("");
    }

    async function fetchServerIP() {
        var display = $("serverIpDisplay");
        if (!display) return;
        display.textContent = "Fetching...";
        display.classList.remove("hidden");
        try {
            var res = await fetch("/api/server/ip");
            var data = await res.json();
            if (data.ip) {
                display.textContent = "IP: " + data.ip;
            } else {
                display.textContent = "Error: " + (data.error || "Failed to fetch");
            }
        } catch (e) {
            display.textContent = "Error: " + e.message;
        }
    }

    window.fetchServerIP = fetchServerIP;

    async function updateEquityChart() {
        var data = await fetchJSON("/api/equity");
        renderEquityChart("equityChart", data);
    }

    async function refresh() {
        await Promise.all([
            updateStatus(),
            updateOpenTrades(),
            updateClosedTrades(),
            updateEquityChart(),
        ]);
    }

    setupConfigModal();
    setupSettingsModal();
    setupTargetModal();
    setupCalendarModal();
    startCountdown();
    refresh();
    setInterval(refresh, REFRESH_MS);
})();
