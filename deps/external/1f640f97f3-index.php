<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=0, viewport-fit=cover">
    <meta name="theme-color" content="#070a12">
    <title>羽路均沾 - 影视聚合导航 · 节点健康监测</title>
    <link rel="dns-prefetch" href="//bing.com">
    <link rel="dns-prefetch" href="//api.uptimerobot.com">
    <link rel="preconnect" href="https://bing.com" crossorigin>
    <style>
        :root {
            --glass: rgba(11, 16, 28, 0.38);
            --blur: 20px;
            --border: rgba(255, 255, 255, 0.14);
            --border-hover: rgba(56, 189, 248, 0.6);
            --btn: rgba(255, 255, 255, 0.05);
            --btn-hover: rgba(255, 255, 255, 0.11);
            --text-main: #ffffff;
            --text-sub: rgba(255, 255, 255, 0.86);
            --text-mute: rgba(255, 255, 255, 0.52);
            --text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
            --ok: #10b981;
            --down: #f43f5e;
            --warn: #f59e0b;
            --none: rgba(148, 163, 184, 0.24);
            --brand: #38bdf8;
            --brand-grad: linear-gradient(135deg, #38bdf8 0%, #3b82f6 50%, #818cf8 100%);
        }
        * { padding: 0; margin: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body {
            background-color: #070a12;
            background-image: radial-gradient(circle at 50% 0%, rgba(56,189,248,0.22) 0%, transparent 64%), url('https://www.bing.com/th?id=OHR.BearsEars_JA-JP8214752036_1920x1080.jpg');
            background-repeat: no-repeat;
            background-position: center;
            background-size: cover;
            background-attachment: fixed;
            min-height: 100vh;
            min-height: 100dvh;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
            color: var(--text-main);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: clamp(12px, 2.5vw, 32px) clamp(10px, 2vw, 24px);
            padding-bottom: calc(clamp(12px, 2.5vw, 32px) + env(safe-area-inset-bottom, 0px));
            -webkit-font-smoothing: antialiased;
        }
        .page-box {
            width: 100%;
            max-width: min(1200px, 95vw);
            margin: auto;
            transition: max-width 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(12px) scale(0.99); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }
        .card {
            background: var(--glass);
            backdrop-filter: blur(var(--blur)) saturate(180%);
            -webkit-backdrop-filter: blur(var(--blur)) saturate(180%);
            border: 1px solid var(--border);
            border-radius: clamp(20px, 3.2vw, 30px);
            padding: clamp(18px, 3vw, 32px) clamp(12px, 2.6vw, 26px);
            box-shadow: 0 32px 64px -16px rgba(0,0,0,0.8), inset 0 1px 0 rgba(255,255,255,0.2);
            text-align: center;
            animation: fadeIn .35s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        .brand-icon {
            width: 50px;
            height: 50px;
            border-radius: 15px;
            background: var(--brand-grad);
            border: 1px solid rgba(255,255,255,0.35);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: #fff;
            margin-bottom: 8px;
            box-shadow: 0 8px 24px rgba(56,189,248,0.36);
            will-change: transform;
            transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        .brand-icon:hover { transform: rotate(8deg) scale(1.06); }
        .brand-title {
            font-size: clamp(1.45rem, 3.6vw, 1.95rem);
            font-weight: 800;
            letter-spacing: 0.5px;
            background: linear-gradient(135deg, #ffffff 40%, rgba(255,255,255,0.8) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 3px;
        }
        .brand-sub {
            font-size: clamp(0.78rem, 1.8vw, 0.88rem);
            color: var(--text-sub);
            margin-bottom: 15px;
            text-shadow: var(--text-shadow);
        }
        .stats-summary-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: clamp(6px, 1.2vw, 10px);
            margin-bottom: 14px;
        }
        .stat-badge {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 8px 4px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 2px;
            text-shadow: var(--text-shadow);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .stat-badge:hover { transform: translateY(-1.5px); border-color: rgba(255,255,255,0.28); }
        .stat-badge .num {
            font-size: clamp(0.95rem, 2.2vw, 1.15rem);
            font-weight: 800;
            line-height: 1.1;
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        }
        .stat-badge .label {
            font-size: 0.68rem;
            font-weight: 600;
            color: var(--text-mute);
        }
        .health-bar {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 9px 15px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.82rem;
            font-weight: 700;
            margin-bottom: 15px;
            text-shadow: var(--text-shadow);
        }
        .health-status { display: flex; align-items: center; gap: 8px; }
        .health-status.ok { color: var(--ok); }
        .health-status.down { color: var(--down); }
        .health-refresh {
            color: var(--text-mute);
            cursor: pointer;
            font-size: 0.76rem;
            transition: color 0.2s, transform 0.2s;
            display: flex;
            align-items: center;
            gap: 5px;
            user-select: none;
        }
        .health-refresh:hover { color: var(--text-main); }
        .health-refresh:active { transform: scale(0.94); }
        .health-refresh.rotating svg { animation: spin 0.8s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        .list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), 1fr));
            gap: clamp(11px, 1.6vw, 16px);
        }
        .item {
            display: flex;
            flex-direction: column;
            gap: 9px;
            background: var(--btn);
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 12px 14px;
            border-radius: 17px;
            text-decoration: none;
            transition: transform .22s cubic-bezier(0.25, 0.8, 0.25, 1), background .22s, border-color .22s, box-shadow .22s;
            cursor: pointer;
            position: relative;
            box-shadow: 0 4px 14px rgba(0,0,0,0.25);
            will-change: transform;
            contain: layout style;
        }
        .item:hover {
            background: var(--btn-hover);
            border-color: var(--border-hover);
            transform: translateY(-2.5px);
            box-shadow: 0 12px 28px rgba(0,0,0,0.5), 0 0 14px rgba(56, 189, 248, 0.16);
        }
        .item:active { transform: scale(0.988); }
        .item-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }
        .item-left {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
            text-align: left;
        }
        .item-ico {
            width: 40px;
            height: 40px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid rgba(255,255,255,0.18);
            flex-shrink: 0;
            transition: transform 0.2s;
        }
        .item:hover .item-ico { transform: scale(1.05); }
        .item-meta { display: flex; flex-direction: column; min-width: 0; gap: 3px; }
        .item-name {
            font-size: .94rem;
            font-weight: 800;
            color: var(--text-main);
            text-shadow: var(--text-shadow);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .item-domain-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.32);
            padding: 1.5px 6.5px;
            border-radius: 6px;
            font-size: 0.72rem;
            font-weight: 700;
            color: #7dd3fc;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
            letter-spacing: 0.3px;
            width: fit-content;
            transition: all 0.2s ease;
        }
        .item:hover .item-domain-badge {
            background: rgba(56, 189, 248, 0.22);
            border-color: rgba(56, 189, 248, 0.65);
            color: #bae6fd;
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.28);
        }
        .item-right {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-shrink: 0;
        }
        .visit-badge {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.18);
            padding: 3px 7px;
            border-radius: 8px;
            font-size: 0.70rem;
            font-weight: 700;
            color: rgba(255, 255, 255, 0.85);
            transition: all 0.2s ease;
            user-select: none;
            letter-spacing: 0.2px;
        }
        .visit-arrow {
            font-size: 0.85rem;
            transition: transform 0.2s ease;
        }
        .item:hover .visit-badge {
            background: rgba(56, 189, 248, 0.22);
            border-color: rgba(56, 189, 248, 0.6);
            color: #ffffff;
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.26);
        }
        .item:hover .visit-arrow {
            transform: translate(2px, -2px);
            color: var(--brand);
        }
        .meta-chip {
            font-size: 0.68rem;
            font-weight: 800;
            padding: 3px 6.5px;
            border-radius: 6px;
            border: 1px solid transparent;
            text-shadow: var(--text-shadow);
            user-select: none;
            display: inline-flex;
            align-items: center;
            gap: 3px;
            transition: transform 0.15s ease;
            cursor: pointer;
        }
        .meta-chip:hover { transform: scale(1.08); }
        .meta-chip.ssl-ok { background: rgba(16, 185, 129, 0.16); color: var(--ok); border-color: rgba(16, 185, 129, 0.38); }
        .meta-chip.ssl-expiring { background: rgba(245, 158, 11, 0.16); color: var(--warn); border-color: rgba(245, 158, 11, 0.38); }
        .meta-chip.ssl-expired, .meta-chip.ssl-error { background: rgba(244, 63, 94, 0.16); color: var(--down); border-color: rgba(244, 63, 94, 0.38); }
        .meta-chip.ssl-loading { background: rgba(255, 255, 255, 0.08); color: var(--text-mute); }
        .pulse-dot { width: 8px; height: 8px; border-radius: 50%; position: relative; }
        .pulse-dot.ok { background: var(--ok); box-shadow: 0 0 8px var(--ok); }
        .pulse-dot.down { background: var(--down); box-shadow: 0 0 8px var(--down); }
        .pulse-dot.unknow { background: var(--none); }
        .pulse-dot.ok::after, .pulse-dot.down::after {
            content: ""; position: absolute; top: 0; left: 0; width: 100%; height: 100%;
            border-radius: 50%; animation: pulse 2s infinite ease-out;
        }
        .pulse-dot.ok::after { background: var(--ok); }
        .pulse-dot.down::after { background: var(--down); }
        @keyframes pulse {
            0% { transform: scale(1); opacity: 0.85; }
            100% { transform: scale(2.6); opacity: 0; }
        }
        .item-timeline-row {
            display: flex;
            flex-direction: column;
            gap: 6px;
            padding: 7px 8px 6px 8px;
            background: rgba(0, 0, 0, 0.22);
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            cursor: default;
            user-select: none;
            transition: border-color 0.2s;
        }
        .item-timeline-row:hover { border-color: rgba(255, 255, 255, 0.12); }
        .timeline-grid {
            display: flex;
            gap: 2.2px;
            align-items: center;
            width: 100%;
            height: 16px;
        }
        .timeline-grid span {
            flex: 1;
            min-width: 0;
            height: 100%;
            border-radius: 2.5px;
            background: var(--none);
            transition: transform 0.15s ease, filter 0.15s ease;
            cursor: pointer;
            position: relative;
        }
        .timeline-grid span.stat-100 { background: var(--ok); }
        .timeline-grid span.stat-warn { background: var(--warn); }
        .timeline-grid span.stat-down { background: var(--down); }
        .timeline-grid span.stat-none { background: var(--none); }
        .timeline-grid span:hover, .timeline-grid span.active {
            transform: scaleY(1.4);
            filter: brightness(1.3);
            z-index: 5;
        }
        .timeline-meta {
            display: flex;
            justify-content: space-between;
            font-size: 0.68rem;
            color: var(--text-mute);
            text-shadow: var(--text-shadow);
            font-weight: 600;
        }
        .timeline-tip-live {
            font-size: 0.68rem;
            color: #7dd3fc;
            background: rgba(15, 23, 42, 0.7);
            border-radius: 6px;
            padding: 3px 6px;
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
            text-align: center;
            display: none;
            animation: fadeIn 0.2s ease;
        }
        .foot { margin-top: 20px; font-size: .76rem; color: var(--text-mute); text-shadow: var(--text-shadow); }
        .foot a { color: var(--text-sub); font-weight: 700; text-decoration: none; transition: color 0.2s; }
        .foot a:hover { color: var(--brand); }
        [data-tip] { position: relative; }
        [data-tip]:hover::after {
            content: attr(data-tip);
            position: absolute;
            bottom: calc(100% + 7px);
            left: 50%;
            transform: translateX(-50%);
            padding: 5px 8px;
            background: rgba(15, 23, 42, 0.96);
            color: #ffffff;
            font-size: 11px;
            font-weight: 700;
            border-radius: 6px;
            white-space: nowrap;
            pointer-events: none;
            z-index: 9999;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.65);
            border: 1px solid rgba(255,255,255,0.18);
            backdrop-filter: blur(6px);
            animation: fadeIn .15s ease-out;
        }
        .modal-mask {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(0, 0, 0, 0.68);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 99999;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.22s ease;
        }
        .modal-mask.show { opacity: 1; pointer-events: auto; }
        .modal-box {
            background: rgba(15, 23, 42, 0.93);
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8), inset 0 1px 0 rgba(255, 255, 255, 0.15);
            border-radius: 20px;
            width: 100%;
            max-width: 360px;
            padding: 22px;
            text-align: left;
            animation: fadeIn 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 15px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding-bottom: 10px;
        }
        .modal-title {
            font-size: 1rem;
            font-weight: 800;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .modal-close {
            background: none;
            border: none;
            color: var(--text-mute);
            cursor: pointer;
            font-size: 1.1rem;
            padding: 4px;
            transition: color 0.2s;
        }
        .modal-close:hover { color: #fff; }
        .modal-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            margin-bottom: 10px;
            color: var(--text-sub);
        }
        .modal-row:last-child { margin-bottom: 0; }
        .modal-val {
            font-weight: 700;
            color: #fff;
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        }
        .svg-icon { width: 1em; height: 1em; fill: currentColor; display: inline-block; vertical-align: -0.125em; }
        @media (max-width: 480px) {
            .timeline-grid { gap: 1.5px; height: 13px; }
            .timeline-grid span { border-radius: 1.5px; }
            .item-name { max-width: 130px; }
            .stats-summary-grid { gap: 4px; }
            .stat-badge .num { font-size: 0.90rem; }
            .stat-badge .label { font-size: 0.62rem; }
            .visit-badge { padding: 2.5px 6px; font-size: 0.65rem; }
        }
    </style>
</head>
<body>
    <svg style="display:none">
        <symbol id="icon-film" viewBox="0 0 16 16"><path d="M0 1a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H1a1 1 0 0 1-1-1zm4 0v6h8V1zm8 8H4v6h8zM1 1v2h2V1zm2 3H1v2h2zM1 7v2h2V7zm2 3H1v2h2zm-2 3v2h2v-2zM15 1h-2v2h2zm-2 3v2h2V4zm2 3h-2v2h2zm-2 3v2h2v-2zm2 3h-2v2h2z"/></symbol>
        <symbol id="icon-search" viewBox="0 0 16 16"><path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001q.044.06.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1 1 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0"/></symbol>
        <symbol id="icon-cloud" viewBox="0 0 16 16"><path d="M4.406 3.342A5.53 5.53 0 0 1 8 2c2.69 0 4.923 2 5.166 4.57A4.5 4.5 0 0 1 13 15H3a4 4 0 0 1-.595-7.956 5.5 5.5 0 0 1 2-3.702"/></symbol>
        <symbol id="icon-server" viewBox="0 0 16 16"><path d="M1.5 0A1.5 1.5 0 0 0 0 1.5v2A1.5 1.5 0 0 0 1.5 5h13A1.5 1.5 0 0 0 16 3.5v-2A1.5 1.5 0 0 0 14.5 0zm1 2a.5.5 0 1 1 0-1 .5.5 0 0 1 0 1m2 0a.5.5 0 1 1 0-1 .5.5 0 0 1 0 1M0 7a1.5 1.5 0 0 1 1.5-1.5h13A1.5 1.5 0 0 1 16 7v2a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 0 9zm2.5 2a.5.5 0 1 0 0-1 .5.5 0 0 0 0 1m2 0a.5.5 0 1 0 0-1 .5.5 0 0 0 0 1M0 12.5A1.5 1.5 0 0 1 1.5 11h13a1.5 1.5 0 0 1 1.5 1.5v2a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 0 14.5zm2.5 2a.5.5 0 1 0 0-1 .5.5 0 0 0 0 1m2 0a.5.5 0 1 0 0-1 .5.5 0 0 0 0 1"/></symbol>
        <symbol id="icon-play" viewBox="0 0 16 16"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14m0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16"/><path d="M6.271 5.055a.5.5 0 0 1 .52.038l3.5 2.5a.5.5 0 0 1 0 .814l-3.5 2.5A.5.5 0 0 1 6 10.5v-5a.5.5 0 0 1 .271-.445"/></symbol>
        <symbol id="icon-refresh" viewBox="0 0 16 16"><path d="M11.534 7h3.932a.25.25 0 0 1 .192.41l-1.966 2.36a.25.25 0 0 1-.384 0l-1.966-2.36a.25.25 0 0 1 .192-.41m-11 2h3.932a.25.25 0 0 0 .192-.41L2.692 6.23a.25.25 0 0 0-.384 0L.342 8.59A.25.25 0 0 0 .534 9"/><path fill-rule="evenodd" d="M8 3c-1.552 0-2.94.707-3.857 1.818a.5.5 0 1 1-.771-.636A6.002 6.002 0 0 1 13.917 7H12.9A5 5 0 0 0 8 3M3.1 9a5.002 5.002 0 0 0 8.757 2.182.5.5 0 1 1 .771.636A6.002 6.002 0 0 1 2.083 9z"/></symbol>
        <symbol id="icon-link" viewBox="0 0 16 16"><path d="M4.715 6.542 3.343 7.914a3 3 0 1 0 4.243 4.243l1.828-1.829A3 3 0 0 0 8.586 5.5L8 6.086a1 1 0 0 0-.154.199 2 2 0 0 1 .861 3.337L7.343 10.99a2 2 0 1 1-2.83-2.83l.793-.792a4 4 0 0 1-.128-1.287z"/><path d="M6.586 4.672A3 3 0 0 0 7.414 9.5l.775-.776a2 2 0 0 1-.896-3.346L9.12 3.55a2 2 0 1 1 2.83 2.83l-.793.792c.112.42.155.855.128 1.287l1.372-1.372a3 3 0 0 0-4.243-4.243z"/></symbol>
        <symbol id="icon-external" viewBox="0 0 16 16"><path fill-rule="evenodd" d="M8.636 3.5a.5.5 0 0 0-.5-.5H1.5A1.5 1.5 0 0 0 0 4.5v10A1.5 1.5 0 0 0 1.5 16h10a1.5 1.5 0 0 0 1.5-1.5V7.864a.5.5 0 0 0-1 0V14.5a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-10a.5.5 0 0 1 .5-.5h6.636a.5.5 0 0 0 .5-.5"/><path fill-rule="evenodd" d="M16 .5a.5.5 0 0 0-.5-.5h-5a.5.5 0 0 0 0 1h3.793L6.146 9.146a.5.5 0 1 0 .708.708L15 1.707V5.5a.5.5 0 0 0 1 0z"/></symbol>
        <symbol id="icon-shield" viewBox="0 0 16 16"><path d="M5.338 1.59a61.44 61.44 0 0 0-2.837.856.481.481 0 0 0-.328.39c-.554 4.157.726 7.19 2.253 9.188a10.725 10.725 0 0 0 2.287 2.233c.346.244.652.42.893.533.12.057.218.095.293.118a.55.55 0 0 0 .101.025.615.615 0 0 0 .1-.025c.076-.023.174-.061.294-.118.24-.113.547-.29.893-.533a10.726 10.726 0 0 0 2.287-2.233c1.527-1.997 2.807-5.031 2.253-9.188a.48.48 0 0 0-.328-.39c-.651-.213-1.75-.56-2.837-.855C9.552 1.29 8.531 1.067 8 1.067c-.53 0-1.552.223-2.662.524zM5.072.56C6.157.265 7.31 0 8 0s1.843.265 2.928.56c1.11.3 2.229.655 2.887.87a1.54 1.54 0 0 1 1.044 1.262c.596 4.477-.787 7.795-2.465 9.99a11.775 11.775 0 0 1-2.517 2.453 7.159 7.159 0 0 1-1.048.625c-.28.132-.581.24-.829.24s-.548-.108-.829-.24a7.158 7.158 0 0 1-1.048-.625 11.777 11.777 0 0 1-2.517-2.453C1.978 10.487.595 7.169 1.191 2.691A1.54 1.54 0 0 1 2.236 1.43 62.202 62.202 0 0 1 5.072.56z"/><path d="M10.854 5.146a.5.5 0 0 1 0 .708l-3 3a.5.5 0 0 1-.708 0l-1.5-1.5a.5.5 0 1 1 .708-.708L7.5 7.793l2.646-2.647a.5.5 0 0 1 .708 0z"/></symbol>
        <symbol id="icon-x" viewBox="0 0 16 16"><path d="M2.146 2.854a.5.5 0 1 1 .708-.708L8 7.293l5.146-5.147a.5.5 0 0 1 .708.708L8.707 8l5.147 5.146a.5.5 0 0 1-.708.708L8 8.707l-5.146 5.147a.5.5 0 0 1-.708-.708L7.293 8z"/></symbol>
    </svg>
    <main class="page-box">
        <section class="card">
            <header>
                <div class="brand-icon"><svg class="svg-icon" style="font-size:1.6rem"><use xlink:href="#icon-film"/></svg></div>
                <h1 class="brand-title">羽路均沾</h1>
                <p class="brand-sub">影视聚合导航 · 节点健康监测</p>
            </header>
            <div class="stats-summary-grid">
                <div class="stat-badge">
                    <span class="num" id="stat-total" style="color: var(--brand);">0</span>
                    <span class="label">全部站点</span>
                </div>
                <div class="stat-badge">
                    <span class="num" id="stat-up" style="color: var(--ok);">0</span>
                    <span class="label">正常运行</span>
                </div>
                <div class="stat-badge">
                    <span class="num" id="stat-down" style="color: var(--down);">0</span>
                    <span class="label">失效/异常</span>
                </div>
                <div class="stat-badge">
                    <span class="num" id="stat-avg" style="color: #a78bfa;">100%</span>
                    <span class="label">30天可用率</span>
                </div>
            </div>
            <div class="health-bar">
                <div class="health-status ok" id="global-health">
                    <span class="pulse-dot ok"></span>
                    <span id="health-text">节点就绪中...</span>
                </div>
                <div class="health-refresh" id="btn-refresh" title="点击立即刷新健康状态">
                    <svg class="svg-icon"><use xlink:href="#icon-refresh"/></svg> <span id="timer-text">60s</span>
                </div>
            </div>
            <div class="list" id="site-list"></div>
            <footer class="foot">
                Copyright © 2026 <a href="https://ylu.cc" target="_blank" rel="noopener noreferrer">Ylu.cc</a>
            </footer>
        </section>
    </main>
    <div class="modal-mask" id="ssl-modal">
        <div class="modal-box">
            <div class="modal-header">
                <div class="modal-title"><svg class="svg-icon" style="color:var(--brand)"><use xlink:href="#icon-shield"/></svg> 证书健康详情</div>
                <button class="modal-close" id="btn-close-modal" aria-label="关闭"><svg class="svg-icon"><use xlink:href="#icon-x"/></svg></button>
            </div>
            <div id="ssl-modal-body"></div>
        </div>
    </div>
    <script>
        window.Config = {"SiteName":"羽路均沾","SubTitle":"影视聚合导航 · 节点健康监测","BrandIcon":"icon-film","ApiUrl":"https:\/\/api.uptimerobot.com\/v2\/getMonitors","CountDays":30,"CacheTTL":60,"ShowSSL":true,"CardOpacity":"0.38","BlurIntensity":"20px","FooterText":"Ylu.cc","FooterUrl":"https:\/\/ylu.cc"};
        window.__INITIAL_DATA__ = {"updated_at":1790492638,"monitors":[{"id":798570119,"name":"❶羽路影视搜搜","url":"https:\/\/ysss.cf","average":"99.93","daily":[{"date":"2026-09-27","uptime":"100.00"},{"date":"2026-09-26","uptime":"100.00"},{"date":"2026-09-25","uptime":"100.00"},{"date":"2026-09-24","uptime":"100.00"},{"date":"2026-09-23","uptime":"100.00"},{"date":"2026-09-22","uptime":"100.00"},{"date":"2026-09-21","uptime":"100.00"},{"date":"2026-09-20","uptime":"100.00"},{"date":"2026-09-19","uptime":"100.00"},{"date":"2026-09-18","uptime":"100.00"},{"date":"2026-09-17","uptime":"100.00"},{"date":"2026-09-16","uptime":"100.00"},{"date":"2026-09-15","uptime":"100.00"},{"date":"2026-09-14","uptime":"100.00"},{"date":"2026-09-13","uptime":"100.00"},{"date":"2026-09-12","uptime":"100.00"},{"date":"2026-09-11","uptime":"100.00"},{"date":"2026-09-10","uptime":"97.77"},{"date":"2026-09-09","uptime":"100.00"},{"date":"2026-09-08","uptime":"100.00"},{"date":"2026-09-07","uptime":"100.00"},{"date":"2026-09-06","uptime":"100.00"},{"date":"2026-09-05","uptime":"100.00"},{"date":"2026-09-04","uptime":"100.00"},{"date":"2026-09-03","uptime":"100.00"},{"date":"2026-09-02","uptime":"100.00"},{"date":"2026-09-01","uptime":"100.00"},{"date":"2026-08-31","uptime":"100.00"},{"date":"2026-08-30","uptime":"100.00"},{"date":"2026-08-29","uptime":"100.00"}],"status":"ok"},{"id":798570495,"name":"❷羽路影视搜搜","url":"https:\/\/ysss.cc.cd","average":"99.94","daily":[{"date":"2026-09-27","uptime":"100.00"},{"date":"2026-09-26","uptime":"99.29"},{"date":"2026-09-25","uptime":"100.00"},{"date":"2026-09-24","uptime":"100.00"},{"date":"2026-09-23","uptime":"100.00"},{"date":"2026-09-22","uptime":"100.00"},{"date":"2026-09-21","uptime":"100.00"},{"date":"2026-09-20","uptime":"100.00"},{"date":"2026-09-19","uptime":"100.00"},{"date":"2026-09-18","uptime":"100.00"},{"date":"2026-09-17","uptime":"100.00"},{"date":"2026-09-16","uptime":"100.00"},{"date":"2026-09-15","uptime":"100.00"},{"date":"2026-09-14","uptime":"100.00"},{"date":"2026-09-13","uptime":"100.00"},{"date":"2026-09-12","uptime":"100.00"},{"date":"2026-09-11","uptime":"100.00"},{"date":"2026-09-10","uptime":"100.00"},{"date":"2026-09-09","uptime":"100.00"},{"date":"2026-09-08","uptime":"99.65"},{"date":"2026-09-07","uptime":"100.00"},{"date":"2026-09-06","uptime":"100.00"},{"date":"2026-09-05","uptime":"100.00"},{"date":"2026-09-04","uptime":"100.00"},{"date":"2026-09-03","uptime":"100.00"},{"date":"2026-09-02","uptime":"99.29"},{"date":"2026-09-01","uptime":"100.00"},{"date":"2026-08-31","uptime":"100.00"},{"date":"2026-08-30","uptime":"100.00"},{"date":"2026-08-29","uptime":"100.00"}],"status":"ok"},{"id":798567167,"name":"❸羽路影视搜搜","url":"https:\/\/yss.pp.ua","average":"99.80","daily":[{"date":"2026-09-27","uptime":"100.00"},{"date":"2026-09-26","uptime":"100.00"},{"date":"2026-09-25","uptime":"100.00"},{"date":"2026-09-24","uptime":"100.00"},{"date":"2026-09-23","uptime":"100.00"},{"date":"2026-09-22","uptime":"100.00"},{"date":"2026-09-21","uptime":"100.00"},{"date":"2026-09-20","uptime":"100.00"},{"date":"2026-09-19","uptime":"100.00"},{"date":"2026-09-18","uptime":"100.00"},{"date":"2026-09-17","uptime":"100.00"},{"date":"2026-09-16","uptime":"100.00"},{"date":"2026-09-15","uptime":"99.65"},{"date":"2026-09-14","uptime":"100.00"},{"date":"2026-09-13","uptime":"100.00"},{"date":"2026-09-12","uptime":"100.00"},{"date":"2026-09-11","uptime":"99.65"},{"date":"2026-09-10","uptime":"100.00"},{"date":"2026-09-09","uptime":"100.00"},{"date":"2026-09-08","uptime":"100.00"},{"date":"2026-09-07","uptime":"100.00"},{"date":"2026-09-06","uptime":"100.00"},{"date":"2026-09-05","uptime":"100.00"},{"date":"2026-09-04","uptime":"94.57"},{"date":"2026-09-03","uptime":"100.00"},{"date":"2026-09-02","uptime":"100.00"},{"date":"2026-09-01","uptime":"100.00"},{"date":"2026-08-31","uptime":"100.00"},{"date":"2026-08-30","uptime":"100.00"},{"date":"2026-08-29","uptime":"100.00"}],"status":"ok"},{"id":798567274,"name":"❹看啥片搜一搜","url":"https:\/\/ksp.pp.ua","average":"99.94","daily":[{"date":"2026-09-27","uptime":"100.00"},{"date":"2026-09-26","uptime":"100.00"},{"date":"2026-09-25","uptime":"100.00"},{"date":"2026-09-24","uptime":"100.00"},{"date":"2026-09-23","uptime":"100.00"},{"date":"2026-09-22","uptime":"100.00"},{"date":"2026-09-21","uptime":"100.00"},{"date":"2026-09-20","uptime":"100.00"},{"date":"2026-09-19","uptime":"100.00"},{"date":"2026-09-18","uptime":"100.00"},{"date":"2026-09-17","uptime":"100.00"},{"date":"2026-09-16","uptime":"100.00"},{"date":"2026-09-15","uptime":"100.00"},{"date":"2026-09-14","uptime":"100.00"},{"date":"2026-09-13","uptime":"100.00"},{"date":"2026-09-12","uptime":"100.00"},{"date":"2026-09-11","uptime":"100.00"},{"date":"2026-09-10","uptime":"98.20"},{"date":"2026-09-09","uptime":"100.00"},{"date":"2026-09-08","uptime":"100.00"},{"date":"2026-09-07","uptime":"100.00"},{"date":"2026-09-06","uptime":"100.00"},{"date":"2026-09-05","uptime":"100.00"},{"date":"2026-09-04","uptime":"100.00"},{"date":"2026-09-03","uptime":"100.00"},{"date":"2026-09-02","uptime":"100.00"},{"date":"2026-09-01","uptime":"100.00"},{"date":"2026-08-31","uptime":"100.00"},{"date":"2026-08-30","uptime":"100.00"},{"date":"2026-08-29","uptime":"100.00"}],"status":"ok"}]};
        window.__FALLBACK_SITES__ = [{"name":"羽路影视搜搜","domain":"ysss.cf","url":"https:\/\/ysss.cf\/","icon":"icon-search","color":"#38bdf8"},{"name":"羽路影视搜搜","domain":"ysss.cc.cd","url":"https:\/\/ysss.cc.cd\/","icon":"icon-cloud","color":"#818cf8"},{"name":"羽路影视搜搜","domain":"yss.pp.ua","url":"https:\/\/yss.pp.ua\/","icon":"icon-server","color":"#34d399"},{"name":"看啥片搜一搜","domain":"ksp.pp.ua","url":"https:\/\/ksp.pp.ua\/","icon":"icon-play","color":"#fbbf24"}];
        (function () {
            'use strict';
            var config = window.Config || {};
            var showSSL = config.ShowSSL !== false;
            var LOCAL_CACHE_KEY = 'mjj_nav_monitors_safe_v3';
            var cachedLocal = null;
            try {
                var raw = localStorage.getItem(LOCAL_CACHE_KEY);
                if (raw) cachedLocal = JSON.parse(raw);
            } catch (e) {}
            var initialMonitors = (window.__INITIAL_DATA__ && window.__INITIAL_DATA__.monitors && window.__INITIAL_DATA__.monitors.length > 0)
                ? window.__INITIAL_DATA__.monitors
                : (cachedLocal || []);
            var state = {
                monitors: initialMonitors,
                sslMap: {},
                countdown: Number(config.CacheTTL) || 60,
                timer: null,
                isRefreshing: false
            };
            function getHostname(url) {
                try { return (new URL(url)).hostname; } catch (e) { return ''; }
            }
            function loadSSLInfo(domain) {
                if (!domain || state.sslMap[domain]) return;
                var cacheKey = 'ssl_cache_' + domain;
                var cached = localStorage.getItem(cacheKey);
                var today = new Date().toISOString().split('T')[0];
                if (cached) {
                    try {
                        var p = JSON.parse(cached);
                        if (p.date === today && p.data) {
                            state.sslMap[domain] = p.data;
                            updateSSLDOM(domain);
                            return;
                        }
                    } catch (e) {}
                }
                fetch('?action=get_ssl&domain=' + encodeURIComponent(domain))
                    .then(function (res) { return res.json(); })
                    .then(function (json) {
                        if (json && json.code === 200) {
                            state.sslMap[domain] = json;
                            try { localStorage.setItem(cacheKey, JSON.stringify({ date: today, data: json })); } catch(e) {}
                        } else {
                            state.sslMap[domain] = { status: 'error' };
                        }
                        updateSSLDOM(domain);
                    })
                    .catch(function () {
                        state.sslMap[domain] = { status: 'error' };
                        updateSSLDOM(domain);
                    });
            }
            function updateSSLDOM(domain) {
                var els = document.querySelectorAll('.ssl-tag[data-domain="' + domain + '"]');
                var ssl = state.sslMap[domain];
                if (!ssl) return;
                for (var i = 0; i < els.length; i++) {
                    if (ssl.status === 'ok') {
                        els[i].className = 'meta-chip ssl-tag ssl-ok';
                        els[i].setAttribute('data-tip', '点击查看证书详情 (剩余 ' + ssl.days + ' 天)');
                        els[i].innerHTML = '🔒 ' + ssl.days + 'd';
                    } else if (ssl.status === 'expiring') {
                        els[i].className = 'meta-chip ssl-tag ssl-expiring';
                        els[i].setAttribute('data-tip', '证书即将到期，点击查看详情');
                        els[i].innerHTML = '⚠️ ' + ssl.days + 'd';
                    } else {
                        els[i].className = 'meta-chip ssl-tag ssl-expired';
                        els[i].setAttribute('data-tip', '证书状态异常，点击查看详情');
                        els[i].innerHTML = '❌ 异常';
                    }
                }
            }
            function showSSLModal(domain) {
                var modal = document.getElementById('ssl-modal');
                var body = document.getElementById('ssl-modal-body');
                var ssl = state.sslMap[domain];
                if (!modal || !body) return;
                if (!ssl || ssl.status === 'loading') {
                    body.innerHTML = '<div style="text-align:center;padding:16px 0;color:var(--text-sub);">正在安全读取证书凭证，请稍候...</div>';
                } else if (ssl.status === 'error') {
                    body.innerHTML = '<div style="text-align:center;padding:16px 0;color:var(--down);font-weight:700;">该域名证书无法建立安全握手或已失效</div>';
                } else {
                    var statusColor = ssl.status === 'ok' ? 'var(--ok)' : 'var(--warn)';
                    var statusText = ssl.status === 'ok' ? '安全有效' : (ssl.status === 'expiring' ? '即将到期' : '已过期');
                    body.innerHTML = '<div class="modal-row"><span>绑定域名</span><span class="modal-val">' + (ssl.domain || domain) + '</span></div>' +
                        '<div class="modal-row"><span>颁发机构</span><span class="modal-val">' + ssl.issuer + '</span></div>' +
                        '<div class="modal-row"><span>生效日期</span><span class="modal-val">' + (ssl.valid_from || '--') + '</span></div>' +
                        '<div class="modal-row"><span>到期日期</span><span class="modal-val">' + (ssl.valid_to || '--') + '</span></div>' +
                        '<div class="modal-row"><span>剩余天数</span><span class="modal-val" style="color:' + statusColor + '">' + ssl.days + ' 天 (' + statusText + ')</span></div>';
                }
                modal.classList.add('show');
            }
            function render() {
                var container = document.getElementById('site-list');
                if (!container) return;
                var list = state.monitors;
                if (!list || list.length === 0) list = window.__FALLBACK_SITES__ || [];
                var upCount = 0;
                var downCount = 0;
                var totalAvg = 0;
                var avgCalcCount = 0;
                var html = list.map(function (s, index) {
                    var isMonitor = s.daily !== undefined && s.daily.length > 0;
                    var url = s.url;
                    var name = s.name;
                    var domain = s.domain || getHostname(url);
                    var status = isMonitor ? s.status : 'ok';
                    if (status === 'ok') upCount++;
                    else if (status === 'down') downCount++;
                    if (isMonitor && s.average) {
                        totalAvg += parseFloat(s.average);
                        avgCalcCount++;
                    }
                    var iconId = s.icon || (index === 0 ? 'icon-film' : 'icon-play');
                    var iconBg = s.color ? s.color + '1a' : 'rgba(56,189,248,0.15)';
                    var iconColor = s.color || '#38bdf8';
                    var sslTag = '';
                    if (showSSL && domain) {
                        var ssl = state.sslMap[domain];
                        if (ssl && ssl.status === 'ok') {
                            sslTag = '<span class="meta-chip ssl-tag ssl-ok" data-domain="' + domain + '" data-tip="点击查看证书详情 (剩余 ' + ssl.days + ' 天)">🔒 ' + ssl.days + 'd</span>';
                        } else {
                            sslTag = '<span class="meta-chip ssl-tag ssl-loading" data-domain="' + domain + '" data-tip="正在探测证书...">SSL...</span>';
                            setTimeout(function () { loadSSLInfo(domain); }, 30);
                        }
                    }
                    var timelineRowHtml = '';
                    if (isMonitor) {
                        var dailySorted = s.daily.slice(0, 30).reverse();
                        var bars = dailySorted.map(function (d) {
                            var uptimeVal = parseFloat(d.uptime);
                            var cls = 'stat-100';
                            if (uptimeVal >= 99.9) cls = 'stat-100';
                            else if (uptimeVal >= 90.0) cls = 'stat-warn';
                            else if (uptimeVal > 0) cls = 'stat-down';
                            else cls = 'stat-none';
                            return '<span class="' + cls + '" data-date="' + d.date + '" data-uptime="' + d.uptime + '" data-tip="' + d.date + ' 可用率 ' + d.uptime + '%"></span>';
                        }).join('');
                        timelineRowHtml = '<div class="item-timeline-row" title="30天可用率概览（点击色块查看单日详情，不跳转）">' +
                            '<div class="timeline-grid">' + bars + '</div>' +
                            '<div class="timeline-meta">' +
                                '<span>30天前</span>' +
                                '<span>30天可用率 ' + s.average + '%</span>' +
                                '<span>今天</span>' +
                            '</div>' +
                            '<div class="timeline-tip-live"></div>' +
                        '</div>';
                    }
                    return '<a href="' + url + '" target="_blank" rel="noopener noreferrer" class="item" title="点击进入 ' + name + ' (直达官方网站)">' +
                        '<div class="item-top">' +
                            '<div class="item-left">' +
                                '<div class="item-ico" style="background:' + iconBg + ';color:' + iconColor + ';"><svg class="svg-icon" style="font-size:1.3rem"><use xlink:href="#' + iconId + '"/></svg></div>' +
                                '<div class="item-meta">' +
                                    '<span class="item-name">' + name + '</span>' +
                                    '<span class="item-domain-badge"><svg class="svg-icon" style="font-size:0.85rem"><use xlink:href="#icon-link"/></svg>' + domain + '</span>' +
                                '</div>' +
                            '</div>' +
                            '<div class="item-right">' +
                                sslTag +
                                '<span class="pulse-dot ' + status + '"></span>' +
                                '<div class="visit-badge" title="点击进入此网站">' +
                                    '<span>访问</span>' +
                                    '<svg class="svg-icon visit-arrow"><use xlink:href="#icon-external"/></svg>' +
                                '</div>' +
                            '</div>' +
                        '</div>' +
                        timelineRowHtml +
                    '</a>';
                }).join('');
                container.innerHTML = html;
                var elTotal = document.getElementById('stat-total');
                var elUp = document.getElementById('stat-up');
                var elDown = document.getElementById('stat-down');
                var elAvg = document.getElementById('stat-avg');
                if (elTotal) elTotal.textContent = list.length;
                if (elUp) elUp.textContent = upCount;
                if (elDown) elDown.textContent = downCount;
                if (elAvg) elAvg.textContent = avgCalcCount > 0 ? (totalAvg / avgCalcCount).toFixed(2) + '%' : '100%';
                var healthEl = document.getElementById('global-health');
                var healthText = document.getElementById('health-text');
                if (healthEl && healthText) {
                    if (downCount > 0) {
                        healthEl.className = 'health-status down';
                        healthText.textContent = '检测到 ' + downCount + ' 个站点出现故障/离线';
                    } else {
                        healthEl.className = 'health-status ok';
                        healthText.textContent = '所有受控节点运行正常';
                    }
                }
            }
            function refreshData(force) {
                if (state.isRefreshing) return;
                state.isRefreshing = true;
                var refreshBtn = document.getElementById('btn-refresh');
                if (refreshBtn) refreshBtn.classList.add('rotating');
                fetch('?action=get_status' + (force ? '&refresh=1' : ''))
                    .then(function (res) { return res.json(); })
                    .then(function (json) {
                        if (json && json.monitors && json.monitors.length > 0) {
                            state.monitors = json.monitors;
                            state.countdown = Number(config.CacheTTL) || 60;
                            try { localStorage.setItem(LOCAL_CACHE_KEY, JSON.stringify(json.monitors)); } catch (e) {}
                            render();
                        }
                    })
                    .catch(function () {})
                    .finally(function () {
                        state.isRefreshing = false;
                        if (refreshBtn) refreshBtn.classList.remove('rotating');
                    });
            }
            function startTimer() {
                if (state.timer) clearInterval(state.timer);
                state.timer = setInterval(function () {
                    state.countdown--;
                    var t = document.getElementById('timer-text');
                    if (t) t.textContent = state.countdown + 's';
                    if (state.countdown <= 0) {
                        state.countdown = Number(config.CacheTTL) || 60;
                        refreshData(false);
                    }
                }, 1000);
            }
            function bindEvents() {
                var listEl = document.getElementById('site-list');
                if (listEl) {
                    listEl.addEventListener('click', function (e) {
                        var sslBtn = e.target.closest('.ssl-tag');
                        if (sslBtn) {
                            e.preventDefault();
                            e.stopPropagation();
                            var domain = sslBtn.getAttribute('data-domain');
                            if (domain) showSSLModal(domain);
                            return;
                        }
                        var timelineRow = e.target.closest('.item-timeline-row');
                        if (timelineRow) {
                            e.preventDefault();
                            e.stopPropagation();
                            var spanBar = e.target.closest('span[data-date]');
                            if (spanBar) {
                                var date = spanBar.getAttribute('data-date');
                                var uptime = spanBar.getAttribute('data-uptime');
                                var liveTip = timelineRow.querySelector('.timeline-tip-live');
                                if (liveTip) {
                                    liveTip.style.display = 'block';
                                    var statusDesc = parseFloat(uptime) >= 99.9 ? '正常运行' : (parseFloat(uptime) >= 90 ? '轻微波动' : '异常/故障');
                                    liveTip.innerHTML = '📅 ' + date + ' · 可用率 <strong>' + uptime + '%</strong> (' + statusDesc + ')';
                                }
                                var allBars = timelineRow.querySelectorAll('.timeline-grid span');
                                for (var i = 0; i < allBars.length; i++) allBars[i].classList.remove('active');
                                spanBar.classList.add('active');
                            }
                            return;
                        }
                    });
                }
                var modal = document.getElementById('ssl-modal');
                var closeBtn = document.getElementById('btn-close-modal');
                if (closeBtn && modal) {
                    closeBtn.addEventListener('click', function () {
                        modal.classList.remove('show');
                    });
                }
                if (modal) {
                    modal.addEventListener('click', function (e) {
                        if (e.target === modal) modal.classList.remove('show');
                    });
                }
                var refreshBtn = document.getElementById('btn-refresh');
                if (refreshBtn) {
                    refreshBtn.addEventListener('click', function () {
                        refreshData(true);
                    });
                }
            }
            function init() {
                render();
                bindEvents();
                startTimer();
                if (!state.monitors || state.monitors.length === 0 || !state.monitors[0].daily) {
                    refreshData(false);
                }
            }
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', init);
            } else {
                init();
            }
        })();
    </script>
<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js/v31edd6df95cf4e85bb4c19e7a9bdbcba1788362987495" integrity="sha512-iIg7k2xntmwu6/uSb5tpc/hySgZc4eoL31yB29W6tJFo2akwjPWcEqnCEdJvGexCL0KEQwVYv5BlowfhVz26hg==" data-cf-beacon='{"version":"2024.11.0","token":"4efb3f5d6946428d8f6fa29c2b582da9","r":1,"spa":2}' crossorigin="anonymous"></script>
</body>
</html>