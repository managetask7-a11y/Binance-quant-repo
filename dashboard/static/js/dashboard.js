(function () {
    var REFRESH_MS = 3000;
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
        var apiArea = $("apiSettingsArea");
        var input = $("selectedMode");

        input.value = mode;
        if (mode === "live") {
            liveBtn.className = "py-2.5 rounded-[10px] text-sm font-semibold border border-accent-cyan transition-all cursor-pointer bg-accent-cyan/10 text-accent-cyan";
            dryBtn.className = "py-2.5 rounded-[10px] text-sm font-semibold border border-white/[0.12] transition-all cursor-pointer bg-white/[0.04] text-gray-400";
            apiArea.classList.remove("hidden");
        } else {
            dryBtn.className = "py-2.5 rounded-[10px] text-sm font-semibold border border-warn transition-all cursor-pointer bg-warn/10 text-warn";
            liveBtn.className = "py-2.5 rounded-[10px] text-sm font-semibold border border-white/[0.12] transition-all cursor-pointer bg-white/[0.04] text-gray-400";
            apiArea.classList.add("hidden");
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
            // Highlight current mode based on label text
            var currentMode = $("modeLabel").textContent.trim();
            if (currentMode === "LIVE") selectMode("live");
            else selectMode("dry_run");
        }
        function closeModal() { overlay.classList.remove("visible"); }

        openBtn.addEventListener("click", openModal);
        closeBtn.addEventListener("click", closeModal);
        cancelBtn.addEventListener("click", closeModal);
        overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });

        saveBtn.addEventListener("click", async function () {
            var mode = $("selectedMode").value;
            var apiKey = $("settingsApiKey").value;
            var apiSecret = $("settingsApiSecret").value;

            if (mode === "live" && (!apiKey || !apiSecret)) {
                error.textContent = "API Key and Secret are required for Live mode.";
                error.classList.remove("hidden");
                return;
            }

            saveBtn.disabled = true;
            saveBtn.textContent = "Applying...";
            
            var res = await postJSON("/api/settings/mode", {
                mode: mode,
                api_key: apiKey,
                api_secret: api_secret
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

        var dpnl = parseFloat(data.daily_pnl);
        $("metricDailyPnl").textContent = formatUSD(dpnl);
        $("metricDailyPnl").className = "metric-value " + metricClass(dpnl);

        var modalPnl = $("modalCurrentPnl");
        if (modalPnl) {
            modalPnl.textContent = formatUSD(dpnl);
            modalPnl.className = "font-mono text-base font-bold " + (dpnl >= 0 ? "text-profit" : "text-loss");
        }

        var dd = parseFloat(data.drawdown_pct);
        $("metricDrawdown").textContent = dd.toFixed(2) + "%";
        $("metricDrawdown").className = "metric-value " + (dd > 20 ? "negative" : "");

        $("metricOpenCount").textContent = data.open_count + "/" + data.max_trades;
        $("metricClosedCount").textContent = data.closed_count;
        $("metricLeverage").textContent = data.leverage + "x";
        $("metricRisk").textContent = (data.risk_per_trade * 100).toFixed(0) + "%";

        var pill = $("openSettingsModal"); // Updated from statusPill
        var label = $("modeLabel");
        var dot = $("statusDot");
        var statusText = "Scanning " + data.scan_limit;

        if (data.daily_target_reached) {
            pill.className = "flex items-center gap-2 bg-surface-700 border border-warn/30 rounded-full px-4 py-1.5 text-[0.75rem] font-semibold tracking-wider text-warn cursor-pointer hover:bg-surface-600 transition-all hover:border-white/20";
            dot.className = "w-2 h-2 rounded-full bg-warn";
            dot.style.animation = "pulse-anim 2s ease-in-out infinite";
            label.textContent = "TARGET MET | " + statusText;
        } else if (data.dry_run) {
            pill.className = "flex items-center gap-2 bg-surface-700 border border-warn/30 rounded-full px-4 py-1.5 text-[0.75rem] font-semibold tracking-wider text-warn cursor-pointer hover:bg-surface-600 transition-all hover:border-white/20";
            dot.className = "w-2 h-2 rounded-full bg-warn";
            dot.style.animation = "pulse-anim 2s ease-in-out infinite";
            label.textContent = "DRY RUN | " + statusText;
        } else {
            pill.className = "flex items-center gap-2 bg-surface-700 border border-profit/30 rounded-full px-4 py-1.5 text-[0.75rem] font-semibold tracking-wider text-profit cursor-pointer hover:bg-surface-600 transition-all hover:border-white/20";
            dot.className = "w-2 h-2 rounded-full bg-profit";
            dot.style.animation = "pulse-anim 2s ease-in-out infinite";
            label.textContent = "LIVE | " + statusText;
        }

        nextScanISO = data.next_scan;

        var ddPct = Math.min(dd / data.prop_max_dd * 100, 100);
        $("propDdFill").style.width = ddPct + "%";
        $("propDdValue").textContent = dd.toFixed(1) + "% / " + data.prop_max_dd + "%";

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
