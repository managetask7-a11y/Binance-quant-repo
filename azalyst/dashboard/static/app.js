(function () {
    const REFRESH_MS = 3000;
    let equityChartInstance = null;
    let nextScanISO = null;
    let countdownInterval = null;

    function $(id) {
        return document.getElementById(id);
    }

    function formatUSD(v) {
        const n = parseFloat(v);
        if (isNaN(n)) return "$--";
        return (n >= 0 ? "+$" : "-$") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function formatPrice(v) {
        const n = parseFloat(v);
        if (isNaN(n)) return "--";
        if (n >= 1000) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        if (n >= 1) return n.toFixed(4);
        return n.toFixed(6);
    }

    function formatPct(v) {
        const n = parseFloat(v);
        if (isNaN(n)) return "--%";
        return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
    }

    function pnlClass(v) {
        const n = parseFloat(v);
        if (isNaN(n)) return "";
        return n >= 0 ? "pnl-positive" : "pnl-negative";
    }

    function metricClass(v) {
        const n = parseFloat(v);
        if (isNaN(n)) return "";
        return n >= 0 ? "positive" : "negative";
    }

    function reasonTag(reason) {
        if (!reason) return "";
        const r = reason.toUpperCase();
        let cls = "reason-tag ";
        if (r.includes("TAKE_PROFIT")) cls += "reason-tp";
        else if (r.includes("BREAKEVEN")) cls += "reason-be";
        else if (r.includes("MANUAL")) cls += "reason-manual";
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
        const diff = Date.now() - new Date(isoStr).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return "just now";
        if (mins < 60) return mins + "m ago";
        const hrs = Math.floor(mins / 60);
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
            const remain = new Date(nextScanISO).getTime() - Date.now();
            if (remain <= 0) {
                $("nextScanCountdown").textContent = "SCANNING...";
                return;
            }
            const m = Math.floor(remain / 60000);
            const s = Math.floor((remain % 60000) / 1000);
            $("nextScanCountdown").textContent = String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
        }, 1000);
    }

    async function fetchJSON(url) {
        try {
            const res = await fetch(url);
            if (!res.ok) return null;
            return await res.json();
        } catch (e) {
            return null;
        }
    }

    async function postJSON(url, body) {
        try {
            const res = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            return await res.json();
        } catch (e) {
            return null;
        }
    }

    // ─── Manual Close Trade ───
    async function closeTrade(symbol) {
        const btn = document.querySelector('[data-symbol="' + symbol + '"]');
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Closing...";
        }
        const result = await postJSON("/api/trades/close", { symbol: symbol });
        if (result && result.success) {
            refresh();
        } else {
            if (btn) {
                btn.disabled = false;
                btn.textContent = "EXIT";
            }
            alert("Failed to close " + symbol + ": " + (result ? result.error : "Network error"));
        }
    }

    // Make closeTrade available globally for inline onclick
    window.closeTrade = closeTrade;

    // ─── Daily Target Modal ───
    function setupModal() {
        var overlay = $("targetModalOverlay");
        var openBtn = $("openTargetModal");
        var closeBtn = $("closeTargetModal");
        var cancelBtn = $("cancelTarget");
        var saveBtn = $("saveTarget");
        var input = $("dailyTargetInput");

        function openModal() {
            overlay.classList.add("visible");
            input.focus();
        }

        function closeModal() {
            overlay.classList.remove("visible");
        }

        openBtn.addEventListener("click", openModal);
        closeBtn.addEventListener("click", closeModal);
        cancelBtn.addEventListener("click", closeModal);

        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) closeModal();
        });

        saveBtn.addEventListener("click", async function () {
            var val = parseFloat(input.value);
            if (isNaN(val) || val < 0) {
                input.style.borderColor = "var(--red)";
                return;
            }
            input.style.borderColor = "";
            await postJSON("/api/daily_target", { target: val });
            closeModal();
            refresh();
        });

        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") saveBtn.click();
        });
    }

    async function updateStatus() {
        const data = await fetchJSON("/api/status");
        if (!data) return;

        $("metricBalance").textContent = "$" + parseFloat(data.balance).toLocaleString("en-US", { minimumFractionDigits: 2 });
        $("metricBalance").className = "metric-value";

        const dpnl = parseFloat(data.daily_pnl);
        $("metricDailyPnl").textContent = formatUSD(dpnl);
        $("metricDailyPnl").className = "metric-value " + metricClass(dpnl);

        // Update modal's current PnL display
        var modalPnl = $("modalCurrentPnl");
        if (modalPnl) {
            modalPnl.textContent = formatUSD(dpnl);
            modalPnl.className = "modal-current-value " + metricClass(dpnl);
        }

        const dd = parseFloat(data.drawdown_pct);
        $("metricDrawdown").textContent = dd.toFixed(2) + "%";
        $("metricDrawdown").className = "metric-value " + (dd > 20 ? "negative" : "");

        $("metricOpenCount").textContent = data.open_count + "/" + data.max_trades;
        $("metricClosedCount").textContent = data.closed_count;
        $("metricLeverage").textContent = data.leverage + "x";
        $("metricRisk").textContent = (data.risk_per_trade * 100).toFixed(0) + "%";

        const pill = $("statusPill");
        const label = $("modeLabel");
        if (data.daily_target_reached) {
            pill.className = "status-pill dry";
            label.textContent = "TARGET MET";
        } else if (data.dry_run) {
            pill.className = "status-pill dry";
            label.textContent = "DRY RUN";
        } else {
            pill.className = "status-pill live";
            label.textContent = "LIVE";
        }

        nextScanISO = data.next_scan;

        const ddPct = Math.min(dd / data.prop_max_dd * 100, 100);
        $("propDdFill").style.width = ddPct + "%";
        $("propDdValue").textContent = dd.toFixed(1) + "% / " + data.prop_max_dd + "%";

        const dailyLimit = data.initial_balance * data.prop_daily_loss / 100;
        const dailyUsed = Math.abs(Math.min(dpnl, 0));
        const dailyPct = Math.min(dailyUsed / dailyLimit * 100, 100);
        $("propDailyFill").style.width = dailyPct + "%";
        $("propDailyValue").textContent = "$" + dailyUsed.toFixed(0) + " / $" + dailyLimit.toLocaleString("en-US", { maximumFractionDigits: 0 });

        // Daily Profit Target Bar
        var targetBar = $("dailyTargetBar");
        var propBar = $("propFirmBar");
        var targetBtn = $("openTargetModal");
        var targetBtnLabel = $("targetBtnLabel");
        if (data.daily_profit_target > 0) {
            targetBar.style.display = "block";
            propBar.classList.add("has-target");

            var targetPct = Math.min(Math.max(dpnl, 0) / data.daily_profit_target * 100, 100);
            $("propTargetFill").style.width = targetPct + "%";
            $("propTargetValue").textContent = "$" + Math.max(dpnl, 0).toFixed(2) + " / $" + data.daily_profit_target.toFixed(2);

            if (data.daily_target_reached) {
                targetBar.classList.add("reached");
            } else {
                targetBar.classList.remove("reached");
            }

            targetBtn.classList.add("active");
            targetBtnLabel.textContent = "$" + data.daily_profit_target.toFixed(2);
        } else {
            targetBar.style.display = "none";
            propBar.classList.remove("has-target");
            targetBtn.classList.remove("active");
            targetBtnLabel.textContent = "Set Target";
        }

        $("lastUpdate").textContent = "Last update: " + new Date().toLocaleTimeString();
    }

    async function updateOpenTrades() {
        const trades = await fetchJSON("/api/trades/open");
        if (!trades) return;

        $("openBadge").textContent = trades.length;
        const tbody = $("openTradesBody");

        if (trades.length === 0) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="10">No open positions</td></tr>';
            return;
        }

        tbody.innerHTML = trades.map(function (t) {
            const sideClass = t.direction === "LONG" ? "side-long" : "side-short";
            const pnlCls = pnlClass(t.pnl_pct);
            const distPct = t.sl_dist_pct || 2.0; // Fallback for older trades
            const triggerPrice = t.direction === "LONG" 
                ? t.entry_price * (1 + distPct / 100) 
                : t.entry_price * (1 - distPct / 100);
            
            let slSubtext = "";
            if (t.pnl_pct >= distPct) {
                slSubtext = "<div style='font-size:0.65rem; margin-top: 2px; color:var(--accent-cyan); font-weight:bold;'>⚡ Trailing Active</div>";
            } else {
                slSubtext = "<div style='font-size:0.65rem; margin-top: 2px; color:var(--text-muted);'>Triggers @ " + formatPrice(triggerPrice) + "</div>";
            }

            return '<tr class="data-flash">' +
                "<td>" + t.symbol + "</td>" +
                '<td><span class="' + sideClass + '">' + t.direction + "</span></td>" +
                "<td>" + formatPrice(t.entry_price) + "</td>" +
                "<td>" + formatPrice(t.live_price) + "</td>" +
                '<td class="' + pnlCls + '">' + formatPct(t.pnl_pct) + " (" + formatUSD(t.pnl_usd) + ")</td>" +
                "<td><div>" + formatPrice(t.sl_price) + "</div>" + slSubtext + "</td>" +
                "<td>" + formatPrice(t.tp_price) + "</td>" +
                '<td><div class="strategies-tags">' + strategyTags(t.strategies) + "</div></td>" +
                "<td>" + t.scan_count + "/" + t.max_hold + "</td>" +
                '<td><button class="exit-btn" data-symbol="' + t.symbol + '" onclick="closeTrade(\'' + t.symbol + '\')">EXIT</button></td>' +
                "</tr>";
        }).join("");
    }

    async function updateClosedTrades() {
        const trades = await fetchJSON("/api/trades/closed");
        if (!trades) return;

        $("closedBadge").textContent = trades.length;
        const tbody = $("closedTradesBody");

        const closedData = trades;
        if (closedData && closedData.length > 0) {
            const wins = closedData.filter(function (t) { return parseFloat(t.pnl_usd) > 0; }).length;
            const validTrades = closedData.filter(function (t) { return Math.abs(parseFloat(t.pnl_usd)) > 0.001; }).length || 1;
            const wr = (wins / validTrades * 100);
            $("metricWinRate").textContent = wr.toFixed(1) + "%";
            $("metricWinRate").className = "metric-value " + (wr >= 50 ? "positive" : "negative");
        }

        if (trades.length === 0) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="11">No closed trades yet</td></tr>';
            return;
        }

        const recent = trades.slice(-50).reverse();
        tbody.innerHTML = recent.map(function (t) {
            const sideClass = t.direction === "LONG" ? "side-long" : "side-short";
            return "<tr>" +
                "<td>" + t.symbol + "</td>" +
                '<td><span class="' + sideClass + '">' + t.direction + "</span></td>" +
                "<td>" + formatPrice(t.entry_price) + "</td>" +
                "<td>" + formatPrice(t.exit_price) + "</td>" +
                "<td class='text-muted'>" + (t.sl_price ? formatPrice(t.sl_price) : "--") + "</td>" +
                "<td class='text-muted'>" + (t.tp_price ? formatPrice(t.tp_price) : "--") + "</td>" +
                '<td class="' + pnlClass(t.pnl_pct) + '">' + formatPct(t.pnl_pct) + "</td>" +
                '<td class="' + pnlClass(t.pnl_usd) + '">' + formatUSD(t.pnl_usd) + "</td>" +
                "<td>" + reasonTag(t.reason) + "</td>" +
                '<td><div class="strategies-tags">' + strategyTags(t.strategies) + "</div></td>" +
                "<td>" + timeAgo(t.exit_time) + "</td>" +
                "</tr>";
        }).join("");
    }

    async function updateEquityChart() {
        const data = await fetchJSON("/api/equity");
        if (!data || data.length === 0) {
            $("chartEmpty").style.display = "block";
            return;
        }

        $("chartEmpty").style.display = "none";
        const canvas = $("equityChart");
        const ctx = canvas.getContext("2d");
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = (rect.height - 32) * dpr;
        canvas.style.width = rect.width + "px";
        canvas.style.height = (rect.height - 32) + "px";
        ctx.scale(dpr, dpr);

        const w = rect.width;
        const h = rect.height - 32;
        const pad = { top: 20, right: 16, bottom: 30, left: 60 };
        const chartW = w - pad.left - pad.right;
        const chartH = h - pad.top - pad.bottom;

        const values = data.map(function (d) { return d.balance; });
        const minV = Math.min.apply(null, values) * 0.998;
        const maxV = Math.max.apply(null, values) * 1.002;
        const rangeV = maxV - minV || 1;

        function xPos(i) { return pad.left + (i / (data.length - 1 || 1)) * chartW; }
        function yPos(v) { return pad.top + (1 - (v - minV) / rangeV) * chartH; }

        ctx.clearRect(0, 0, w, h);

        ctx.strokeStyle = "rgba(255,255,255,0.04)";
        ctx.lineWidth = 1;
        for (var gi = 0; gi <= 4; gi++) {
            var gy = pad.top + (gi / 4) * chartH;
            ctx.beginPath();
            ctx.moveTo(pad.left, gy);
            ctx.lineTo(w - pad.right, gy);
            ctx.stroke();

            var gv = maxV - (gi / 4) * rangeV;
            ctx.fillStyle = "rgba(255,255,255,0.25)";
            ctx.font = "11px 'JetBrains Mono'";
            ctx.textAlign = "right";
            ctx.fillText("$" + gv.toFixed(0), pad.left - 8, gy + 4);
        }

        var grad = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
        var lastVal = values[values.length - 1];
        var firstVal = values[0];
        if (lastVal >= firstVal) {
            grad.addColorStop(0, "rgba(16,185,129,0.2)");
            grad.addColorStop(1, "rgba(16,185,129,0)");
        } else {
            grad.addColorStop(0, "rgba(239,68,68,0.2)");
            grad.addColorStop(1, "rgba(239,68,68,0)");
        }

        ctx.beginPath();
        ctx.moveTo(xPos(0), h - pad.bottom);
        for (var fi = 0; fi < data.length; fi++) {
            ctx.lineTo(xPos(fi), yPos(values[fi]));
        }
        ctx.lineTo(xPos(data.length - 1), h - pad.bottom);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        ctx.beginPath();
        for (var li = 0; li < data.length; li++) {
            if (li === 0) ctx.moveTo(xPos(li), yPos(values[li]));
            else ctx.lineTo(xPos(li), yPos(values[li]));
        }
        ctx.strokeStyle = lastVal >= firstVal ? "#10b981" : "#ef4444";
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.stroke();

        var lastX = xPos(data.length - 1);
        var lastY = yPos(lastVal);
        ctx.beginPath();
        ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
        ctx.fillStyle = lastVal >= firstVal ? "#10b981" : "#ef4444";
        ctx.fill();
        ctx.beginPath();
        ctx.arc(lastX, lastY, 7, 0, Math.PI * 2);
        ctx.strokeStyle = lastVal >= firstVal ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)";
        ctx.lineWidth = 2;
        ctx.stroke();
    }

    // ─── Monthly Calendar Modal ───
    function setupCalendarModal() {
        var overlay = $("calendarModalOverlay");
        var openBtn = $("openCalendarModal");
        var closeBtn = $("closeCalendarModal");
        var closeBtn2 = $("closeCalendarBtn");

        function openModal() {
            overlay.classList.add("visible");
            buildCalendar();
        }

        function closeModal() {
            overlay.classList.remove("visible");
        }

        if (openBtn) openBtn.addEventListener("click", openModal);
        if (closeBtn) closeBtn.addEventListener("click", closeModal);
        if (closeBtn2) closeBtn2.addEventListener("click", closeModal);

        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) closeModal();
        });
    }

    async function buildCalendar() {
        const trades = await fetchJSON("/api/trades/closed");
        if (!trades) return;

        const now = new Date();
        const currentMonth = now.getMonth();
        const currentYear = now.getFullYear();

        const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
        $("calendarMonthTitle").textContent = "🗓️ " + monthNames[currentMonth] + " " + currentYear;

        // Group trades by day for current month
        let monthlyPnl = 0;
        let monthlyWins = 0;
        let monthlyTotal = 0;
        const dailyPnls = {};

        trades.forEach(t => {
            const exitDate = new Date(t.exit_time);
            if (exitDate.getMonth() === currentMonth && exitDate.getFullYear() === currentYear) {
                const day = exitDate.getDate();
                const pnl = parseFloat(t.pnl_usd) || 0;
                
                if (!dailyPnls[day]) dailyPnls[day] = { pnl: 0, count: 0 };
                dailyPnls[day].pnl += pnl;
                dailyPnls[day].count += 1;

                monthlyPnl += pnl;
                monthlyTotal++;
                if (pnl > 0) monthlyWins++;
            }
        });

        // Update stats
        $("calMonthlyPnl").textContent = formatUSD(monthlyPnl);
        $("calMonthlyPnl").className = monthlyPnl >= 0 ? "positive" : "negative";

        $("calTotalTrades").textContent = monthlyTotal;

        let winRate = 0;
        if (monthlyTotal > 0) winRate = (monthlyWins / monthlyTotal) * 100;
        $("calWinRate").textContent = winRate.toFixed(1) + "%";
        $("calWinRate").className = winRate >= 50 ? "positive" : "negative";

        // Build Grid
        const grid = document.querySelector(".calendar-grid");
        
        // Remove existing days (keep headers)
        const headers = Array.from(grid.querySelectorAll(".cal-day-label"));
        grid.innerHTML = "";
        headers.forEach(h => grid.appendChild(h));

        const firstDay = new Date(currentYear, currentMonth, 1).getDay();
        const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();

        // Empty slots before 1st of month
        for (let i = 0; i < firstDay; i++) {
            const emptyEl = document.createElement("div");
            emptyEl.className = "cal-day empty";
            grid.appendChild(emptyEl);
        }

        // Days of month
        for (let i = 1; i <= daysInMonth; i++) {
            const dayEl = document.createElement("div");
            dayEl.className = "cal-day";
            
            const dateNum = document.createElement("span");
            dateNum.className = "date-num";
            dateNum.textContent = i;
            
            dayEl.appendChild(dateNum);

            if (dailyPnls[i]) {
                const p = dailyPnls[i].pnl;
                const pnlEl = document.createElement("span");
                pnlEl.className = "day-pnl";
                pnlEl.textContent = formatUSD(p);
                dayEl.appendChild(pnlEl);

                if (p > 0) dayEl.classList.add("win");
                else if (p < 0) dayEl.classList.add("loss");
                else dayEl.classList.add("neutral");
            }

            grid.appendChild(dayEl);
        }
    }


    async function refresh() {
        await Promise.all([
            updateStatus(),
            updateOpenTrades(),
            updateClosedTrades(),
            updateEquityChart(),
        ]);
    }

    setupModal();
    setupCalendarModal();
    startCountdown();
    refresh();
    setInterval(refresh, REFRESH_MS);
})();
