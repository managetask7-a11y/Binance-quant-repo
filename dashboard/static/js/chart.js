function renderEquityChart(canvasId, data) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var emptyEl = document.getElementById("chartEmpty");

    if (!data || data.length === 0) {
        if (emptyEl) emptyEl.style.display = "flex";
        return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    var ctx = canvas.getContext("2d");
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    
    canvas.width = rect.width * dpr;
    canvas.height = (rect.height - 10) * dpr;
    canvas.style.width = rect.width + "px";
    canvas.style.height = (rect.height - 10) + "px";
    ctx.scale(dpr, dpr);

    var w = rect.width;
    var h = rect.height - 10;
    var pad = { top: 30, right: 20, bottom: 40, left: 70 };
    var chartW = w - pad.left - pad.right;
    var chartH = h - pad.top - pad.bottom;

    var values = data.map(function (d) { return parseFloat(d.balance); });
    var rawMin = Math.min.apply(null, values);
    var rawMax = Math.max.apply(null, values);
    var rawRange = rawMax - rawMin;
    
    // Improved Scaling: Ensure we always have some room to see movements
    var padding = rawRange < 1.0 ? 5.0 : rawRange * 0.15;
    var minV = rawMin - padding;
    var maxV = rawMax + padding;
    var rangeV = maxV - minV || 1;

    function xPos(i) { return pad.left + (i / (data.length - 1 || 1)) * chartW; }
    function yPos(v) { return pad.top + (1 - (v - minV) / rangeV) * chartH; }

    ctx.clearRect(0, 0, w, h);

    // --- Grid Lines ---
    ctx.strokeStyle = "rgba(255,255,255,0.06)";
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 5]);
    for (var gi = 0; gi <= 4; gi++) {
        var gy = pad.top + (gi / 4) * chartH;
        ctx.beginPath();
        ctx.moveTo(pad.left, gy);
        ctx.lineTo(w - pad.right, gy);
        ctx.stroke();

        var gv = maxV - (gi / 4) * rangeV;
        ctx.fillStyle = "rgba(255,255,255,0.3)";
        ctx.font = "12px 'Inter', sans-serif";
        ctx.textAlign = "right";
        ctx.fillText("$" + gv.toFixed(1), pad.left - 12, gy + 4);
    }
    ctx.setLineDash([]);

    // --- Gradient Area ---
    var grad = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
    var isProfitable = values[values.length - 1] >= values[0];
    var mainColor = isProfitable ? "#00f0ff" : "#ff4d4d"; // Cyan for profit, Red for loss
    
    grad.addColorStop(0, isProfitable ? "rgba(0, 240, 255, 0.15)" : "rgba(255, 77, 77, 0.15)");
    grad.addColorStop(1, "rgba(0,0,0,0)");

    ctx.beginPath();
    ctx.moveTo(xPos(0), h - pad.bottom);
    for (var fi = 0; fi < data.length; fi++) {
        ctx.lineTo(xPos(fi), yPos(values[fi]));
    }
    ctx.lineTo(xPos(data.length - 1), h - pad.bottom);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // --- Main Line Glow ---
    ctx.shadowBlur = 15;
    ctx.shadowColor = mainColor;
    ctx.beginPath();
    for (var li = 0; li < data.length; li++) {
        if (li === 0) ctx.moveTo(xPos(li), yPos(values[li]));
        else ctx.lineTo(xPos(li), yPos(values[li]));
    }
    ctx.strokeStyle = mainColor;
    ctx.lineWidth = 3;
    ctx.lineJoin = "round";
    ctx.stroke();
    ctx.shadowBlur = 0; // Reset shadow

    // --- Current Point Marker ---
    var lastX = xPos(data.length - 1);
    var lastY = yPos(values[values.length - 1]);
    
    // Outer Ring
    ctx.beginPath();
    ctx.arc(lastX, lastY, 8, 0, Math.PI * 2);
    ctx.fillStyle = mainColor + "33";
    ctx.fill();
    
    // Inner Dot
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.fill();
    ctx.strokeStyle = mainColor;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Time Labels (Start and End)
    ctx.fillStyle = "rgba(255,255,255,0.4)";
    ctx.font = "10px 'Inter', sans-serif";
    ctx.textAlign = "left";
    var startTime = new Date(data[0].timestamp).toLocaleDateString();
    ctx.fillText(startTime, pad.left, h - 15);
    
    ctx.textAlign = "right";
    var endTime = "Now";
    ctx.fillText(endTime, w - pad.right, h - 15);
}
