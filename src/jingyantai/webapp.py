from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import urlparse

from jingyantai.cli import _default_budget, _persist_final_artifacts, build_controller
from jingyantai.config import Settings, hydrate_runtime_secret
from jingyantai.runtime.reporting import CitationAgent, Synthesizer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8091
PUBLIC_HOST = "0.0.0.0"

PHASE_LABELS = {
    "initialize": "初始化研究",
    "expand": "扩展候选",
    "deepen": "深入分析",
    "challenge": "交叉质疑",
    "decide": "判断是否继续",
    "stop": "结束",
    "queued": "排队中",
    "error": "运行出错",
}

STAGE_LABELS = {
    "start": "开始",
    "end": "完成",
}


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>竞研台 | 智能调研</title>
  <style>
    :root {
      --sk-focus-color: #0071e3;
      --sk-body-link-color: #0066cc;
      --apple-blue: #0071e3;
      --black: #000000;
      --near-black: #1d1d1f;
      --light-gray: #f5f5f7;
      --white: #ffffff;
      --card-shadow: rgba(0,0,0,0.22) 3px 5px 30px 0px;
      --dark-surface: #272729;
      --dark-surface-2: #262628;
      --dark-surface-3: #28282a;
      --dark-surface-4: #2a2a2d;
    }
    *, *::before, *::after {
      box-sizing: border-box;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }
    body {
      margin: 0;
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      background: var(--black);
      color: var(--white);
      overflow-x: hidden;
    }

    /* ── Navigation Glass ── */
    nav {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 48px;
      background: rgba(0,0,0,0.8);
      backdrop-filter: saturate(180%) blur(20px);
      -webkit-backdrop-filter: saturate(180%) blur(20px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 9999;
    }
    .nav-inner {
      max-width: 980px;
      width: 100%;
      padding: 0 24px;
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
    }
    .nav-logo {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      text-decoration: none;
      color: var(--white);
    }
    .nav-logo svg {
      width: 17px;
      height: 48px;
      fill: var(--white);
      display: block;
    }
    .nav-links {
      display: flex;
      gap: 20px;
      align-items: center;
      justify-content: center;
    }
    .nav-links a {
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 12px;
      font-weight: 400;
      letter-spacing: normal;
      color: #ffffff;
      text-decoration: none;
      transition: color 0.15s ease;
    }
    .nav-links a:hover { color: rgba(255,255,255,0.7); }
    .nav-links a:focus-visible {
      outline: 2px solid var(--sk-focus-color);
      outline-offset: 2px;
      border-radius: 4px;
    }
    .nav-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 20px;
    }
    .nav-icon-btn {
      background: none;
      border: none;
      cursor: pointer;
      padding: 0;
      color: #ffffff;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 48px;
      line-height: 1;
    }
    .nav-icon-btn svg {
      width: 15px;
      height: 15px;
      fill: #ffffff;
    }
    .nav-icon-btn:focus-visible {
      outline: 2px solid var(--sk-focus-color);
      outline-offset: 2px;
    }

    /* ── Hamburger ── */
    .nav-hamburger {
      display: none;
      flex-direction: column;
      justify-content: center;
      gap: 5px;
      width: 44px;
      height: 48px;
      background: none;
      border: none;
      cursor: pointer;
      padding: 0;
      align-items: center;
    }
    .nav-hamburger span {
      display: block;
      width: 18px;
      height: 1.5px;
      background: var(--white);
      border-radius: 2px;
      transition: transform 0.2s ease, opacity 0.2s ease;
    }
    .nav-hamburger:focus-visible {
      outline: 2px solid var(--sk-focus-color);
      outline-offset: 2px;
    }

    /* ── Mobile Overlay Menu ── */
    .mobile-menu {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.96);
      backdrop-filter: saturate(180%) blur(20px);
      -webkit-backdrop-filter: saturate(180%) blur(20px);
      z-index: 9998;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 40px;
    }
    .mobile-menu.open { display: flex; }
    .mobile-menu a {
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 24px;
      font-weight: 300;
      letter-spacing: normal;
      color: var(--white);
      text-decoration: none;
      line-height: 1.5;
    }
    .mobile-menu a:hover { color: rgba(255,255,255,0.7); }
    .mobile-menu-close {
      position: absolute;
      top: 16px;
      right: 14px;
      background: rgba(210,210,215,0.64);
      color: rgba(0,0,0,0.48);
      border: none;
      cursor: pointer;
      line-height: 1;
      border-radius: 50%;
      width: 44px;
      height: 44px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.15s ease;
      padding: 0;
    }
    .mobile-menu-close:hover { background: rgba(255,255,255,0.32); }
    .mobile-menu-close:focus-visible {
      outline: 2px solid var(--sk-focus-color);
      outline-offset: 2px;
    }
    .mobile-menu-close svg {
      width: 14px;
      height: 14px;
      fill: rgba(0,0,0,0.48);
    }

    /* ── Sections ── */
    section {
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }
    .dark-section { background: var(--black); color: var(--white); }
    .light-section { background: var(--light-gray); color: var(--near-black); }
    .section-inner {
      max-width: 980px;
      width: 100%;
      padding: 120px 24px;
      text-align: center;
    }
    .section-inner-sm {
      max-width: 980px;
      width: 100%;
      padding: 80px 24px;
      text-align: center;
    }

    /* ── Hero ── */
    .hero {
      min-height: 100vh;
    }
    .hero .section-inner {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding-top: calc(48px + 72px);
      padding-bottom: 120px;
    }

    /* ── Typography ── */
    h1 {
      font-family: "SF Pro Display", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 56px;
      font-weight: 600;
      line-height: 1.07;
      letter-spacing: -0.28px;
      margin: 0 0 10px;
      text-align: center;
    }
    h2.section-title {
      font-family: "SF Pro Display", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 40px;
      font-weight: 600;
      line-height: 1.10;
      letter-spacing: normal;
      margin: 0 0 10px;
      text-align: center;
    }
    .eyebrow {
      font-family: "SF Pro Display", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 21px;
      font-weight: 400;
      line-height: 1.19;
      letter-spacing: 0.231px;
      margin: 0 0 48px;
      text-align: center;
    }
    .dark-section .eyebrow { color: rgba(255,255,255,0.8); }
    .light-section .eyebrow { color: rgba(0,0,0,0.8); }

    /* ── Input Panel ── */
    .input-panel {
      width: 100%;
      max-width: 580px;
      margin: 0 auto;
    }
    .input-wrap { position: relative; width: 100%; }
    input[type="text"] {
      width: 100%;
      padding: 16px 22px;
      border-radius: 11px;
      border: 3px solid rgba(255,255,255,0.08);
      background: #272729;
      color: var(--white);
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 17px;
      font-weight: 400;
      letter-spacing: -0.374px;
      line-height: 1.47;
      outline: none;
      transition: outline 0.2s ease;
      text-align: left;
    }
    input[type="text"]::placeholder { color: rgba(255,255,255,0.48); }
    input[type="text"]:focus {
      outline: 2px solid var(--sk-focus-color);
      outline-offset: 2px;
    }
    .light-section input[type="text"] {
      border: 3px solid rgba(0,0,0,0.04);
      background: #fafafc;
      color: var(--near-black);
    }
    .light-section input[type="text"]::placeholder { color: rgba(29,29,31,0.48); }
    .light-section input[type="text"]:focus {
      outline: 2px solid var(--sk-focus-color);
      outline-offset: 2px;
    }

    /* ── Buttons ── */
    .btn-row {
      display: flex;
      gap: 14px;
      margin-top: 24px;
      justify-content: center;
      flex-wrap: wrap;
    }
    button {
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 17px;
      font-weight: 400;
      letter-spacing: normal;
      line-height: 1.0;
      border: none;
      cursor: pointer;
      transition: background 0.18s ease, color 0.18s ease, transform 0.1s ease;
      outline: none;
    }
    button:focus-visible {
      outline: 2px solid var(--sk-focus-color);
      outline-offset: 2px;
    }

    .btn-primary {
      background: var(--apple-blue);
      color: var(--white);
      border-radius: 8px;
      padding: 8px 15px;
      border: 1px solid transparent;
      line-height: 1.0;
    }
    .btn-primary:hover { background: #0077ed; }
    .btn-primary:active { background: #ededf2; color: var(--near-black); transform: scale(0.98); }

    .btn-pill-dark {
      background: transparent;
      color: #2997ff;
      border-radius: 980px;
      padding: 8px 15px;
      border: 1px solid #2997ff;
      line-height: 1.0;
      letter-spacing: normal;
    }
    .btn-pill-dark:hover { text-decoration: underline; }
    .btn-pill-dark:active { transform: scale(0.98); }

    .btn-pill-light {
      background: transparent;
      color: var(--sk-body-link-color);
      border-radius: 980px;
      padding: 8px 15px;
      border: 1px solid var(--sk-body-link-color);
      line-height: 1.0;
      letter-spacing: normal;
    }
    .btn-pill-light:hover { text-decoration: underline; }
    .btn-pill-light:active { transform: scale(0.98); }

    /* ── Cards ── */
    .card-grid {
      display: grid;
      gap: 24px;
      grid-template-columns: repeat(3, 1fr);
      margin-top: 40px;
      width: 100%;
      text-align: left;
    }
    .card-grid.two-col { grid-template-columns: repeat(2, 1fr); }
    .card {
      border-radius: 8px;
      padding: 24px;
      text-align: left;
      display: flex;
      flex-direction: column;
    }
    .dark-section .card { background: var(--dark-surface); color: var(--white); }
    .dark-section .card.elevated { background: var(--dark-surface-2); }
    .dark-section .card.elevated-2 { background: var(--dark-surface-3); }
    .light-section .card {
      background: var(--light-gray);
      color: var(--near-black);
      box-shadow: var(--card-shadow);
    }
    .card h3 {
      font-family: "SF Pro Display", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 21px;
      font-weight: 700;
      line-height: 1.19;
      letter-spacing: 0.231px;
      margin: 0 0 14px;
      color: inherit;
    }
    .card-body {
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 17px;
      font-weight: 400;
      line-height: 1.47;
      letter-spacing: -0.374px;
      color: inherit;
      white-space: pre-wrap;
      word-break: break-word;
      flex: 1;
    }
    .dark-section .card-body { color: rgba(255,255,255,0.8); }
    .light-section .card-body { color: rgba(0,0,0,0.8); }
    .card-body.empty-state { color: rgba(255,255,255,0.48); font-style: italic; }
    .light-section .card-body.empty-state { color: rgba(0,0,0,0.48); }

    /* ── Pill tags ── */
    .pill-tag {
      display: inline-block;
      padding: 5px 14px;
      border-radius: 5px;
      background: var(--dark-surface);
      color: var(--white);
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 14px;
      font-weight: 400;
      letter-spacing: -0.224px;
      line-height: 1.43;
      margin: 0 6px 6px 0;
    }
    .light-section .pill-tag {
      background: #ededf2;
      color: var(--near-black);
    }

    /* ── Raw data pre ── */
    pre#rawData {
      background: rgba(255,255,255,0.04);
      color: rgba(255,255,255,0.8);
      padding: 24px;
      border-radius: 8px;
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 12px;
      letter-spacing: -0.12px;
      line-height: 1.33;
      text-align: left;
      width: 100%;
      margin-top: 24px;
      overflow-x: auto;
      display: none;
    }

    /* ── Log items ── */
    #roundLog { margin-top: 40px; width: 100%; text-align: left; }
    .log-item {
      display: flex;
      gap: 14px;
      align-items: baseline;
      padding: 12px 0;
      font-family: "SF Pro Text", "SF Pro Icons", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 14px;
      font-weight: 400;
      letter-spacing: -0.224px;
      line-height: 1.43;
    }
    .log-time {
      font-size: 12px;
      letter-spacing: -0.12px;
      color: rgba(29,29,31,0.38);
      white-space: nowrap;
      flex-shrink: 0;
    }
    .dark-section .log-time { color: rgba(255,255,255,0.32); }
    .log-phase {
      color: var(--near-black);
      font-weight: 600;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .dark-section .log-phase { color: rgba(255,255,255,0.8); }
    .log-msg { color: rgba(0,0,0,0.8); }
    .dark-section .log-msg { color: rgba(255,255,255,0.8); }

    /* ── Action row ── */
    .action-row {
      display: flex;
      gap: 14px;
      margin-top: 24px;
      justify-content: center;
      flex-wrap: wrap;
    }

    /* ── Insights grid ── */
    .insights-grid {
      display: grid;
      gap: 24px;
      grid-template-columns: repeat(2, 1fr);
      margin-top: 40px;
      width: 100%;
      text-align: left;
    }
    .insights-grid .card.span-full {
      grid-column: 1 / -1;
    }

    /* ── Responsive ── */
    @media (max-width: 1024px) {
      .card-grid { grid-template-columns: repeat(2, 1fr); }
      .insights-grid { grid-template-columns: repeat(2, 1fr); }
    }
    @media (max-width: 834px) {
      h1 { font-size: 48px; }
      h2.section-title { font-size: 28px; letter-spacing: 0.196px; line-height: 1.14; }
      .card-grid { grid-template-columns: 1fr; }
      .insights-grid { grid-template-columns: 1fr; }
      .insights-grid .card.span-full { grid-column: 1; }
    }
    @media (max-width: 640px) {
      h1 { font-size: 40px; letter-spacing: 0.196px; line-height: 1.14; }
      h2.section-title { font-size: 28px; letter-spacing: 0.196px; line-height: 1.14; }
      .nav-links { display: none; }
      .nav-actions { display: none; }
      .nav-hamburger { display: flex; }
      .nav-inner { grid-template-columns: 1fr auto; }
      .nav-logo { justify-content: flex-start; }
    }
    @media (max-width: 480px) {
      .input-panel { max-width: 100%; }
      .eyebrow { font-size: 21px; margin-bottom: 48px; }
      .btn-row { gap: 10px; }
      .section-inner { padding: 80px 20px; }
      .section-inner-sm { padding: 60px 20px; }
    }
  </style>
</head>
<body>

  <!-- Navigation Glass -->
  <nav aria-label="主导航">
    <div class="nav-inner">
      <a href="/" class="nav-logo" aria-label="竞研台首页">
        <svg viewBox="0 0 17 20" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M14.05 10.47c-.02-2.17 1.77-3.22 1.85-3.27-1.01-1.48-2.58-1.68-3.14-1.7-1.34-.14-2.62.79-3.3.79-.68 0-1.73-.77-2.85-.75-1.46.02-2.81.85-3.56 2.16C1.6 10.5 2.7 14.5 4.2 16.65c.74 1.06 1.62 2.25 2.77 2.21 1.12-.05 1.54-.72 2.89-.72 1.35 0 1.73.72 2.91.7 1.2-.02 1.96-1.08 2.69-2.15.85-1.23 1.2-2.42 1.22-2.48-.03-.01-2.61-1-2.63-3.74zM11.9 3.9C12.5 3.17 12.9 2.16 12.78 1.13c-.87.04-1.92.58-2.54 1.3-.56.64-1.05 1.67-.92 2.65.97.07 1.96-.49 2.58-1.18z"/>
        </svg>
      </a>
      <div class="nav-links">
        <a href="#">研究</a>
        <a href="#">历史</a>
        <a href="#">设置</a>
      </div>
      <div class="nav-actions">
        <button class="nav-icon-btn" aria-label="搜索">
          <svg viewBox="0 0 15 15" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M14.78 13.72l-3.8-3.8a5.82 5.82 0 10-1.06 1.06l3.8 3.8a.75.75 0 001.06-1.06zM1.5 6.25a4.75 4.75 0 114.75 4.75A4.76 4.76 0 011.5 6.25z"/>
          </svg>
        </button>
        <button class="nav-icon-btn" aria-label="账户">
          <svg viewBox="0 0 15 15" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M7.5 8.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm0 1.5C4.46 10 0 11.54 0 14v.5h15V14c0-2.46-4.46-4-7.5-4z"/>
          </svg>
        </button>
      </div>
      <button class="nav-hamburger" id="hamburgerBtn" aria-label="打开菜单" aria-expanded="false">
        <span></span>
        <span></span>
        <span></span>
      </button>
    </div>
  </nav>

  <!-- Mobile Overlay Menu -->
  <div class="mobile-menu" id="mobileMenu" role="dialog" aria-modal="true" aria-label="导航菜单">
    <button class="mobile-menu-close" id="mobileMenuClose" aria-label="关闭菜单">
      <svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M13 1L1 13M1 1l12 12" stroke="rgba(0,0,0,0.48)" stroke-width="1.5" stroke-linecap="round" fill="none"/>
      </svg>
    </button>
    <a href="#" onclick="closeMobileMenu()">研究</a>
    <a href="#" onclick="closeMobileMenu()">历史</a>
    <a href="#" onclick="closeMobileMenu()">设置</a>
  </div>

  <!-- Hero: Dark Section -->
  <section class="dark-section hero" aria-labelledby="hero-title">
    <div class="section-inner">
      <h1 id="hero-title">竞研台</h1>
      <p class="eyebrow">智能 Agent 驱动的深度竞争分析系统</p>
      <div class="input-panel">
        <div class="input-wrap">
          <input
            id="target"
            type="text"
            value="Claude Code"
            placeholder="输入调研目标..."
            aria-label="调研目标"
          />
        </div>
        <div class="btn-row">
          <button class="btn-primary" id="startBtn">开始研究</button>
          <button class="btn-pill-dark" id="loadBtn">读取报告</button>
        </div>
      </div>
    </div>
  </section>

  <!-- Progress: Light Section -->
  <section class="light-section" aria-labelledby="progress-title">
    <div class="section-inner">
      <h2 class="section-title" id="progress-title">实时进度</h2>
      <p class="eyebrow">Agent 正在深度扫描全球信源</p>
      <div class="card-grid">
        <article class="card">
          <h3>运行状态</h3>
          <div id="status" class="card-body empty-state">等待任务...</div>
        </article>
        <article class="card">
          <h3>当前阶段</h3>
          <div id="progress" class="card-body empty-state">静默中</div>
        </article>
        <article class="card">
          <h3>判读结论</h3>
          <div id="outcome" class="card-body empty-state">暂无诊断</div>
        </article>
      </div>
    </div>
  </section>

  <!-- Insights: Dark Section -->
  <section class="dark-section" aria-labelledby="insights-title">
    <div class="section-inner">
      <h2 class="section-title" id="insights-title">深度洞察</h2>
      <p class="eyebrow">全链条竞争情报自动化生成</p>
      <div class="insights-grid">
        <article class="card elevated">
          <h3>确认竞品</h3>
          <div id="competitors" class="card-body empty-state">寻找中...</div>
        </article>
        <article class="card elevated">
          <h3>分析状态</h3>
          <div id="insightStatus" class="card-body empty-state">准备就绪</div>
        </article>
        <article class="card elevated span-full">
          <h3>调研摘要</h3>
          <div id="summary" class="card-body empty-state">准备生成深度报告</div>
        </article>
      </div>
      <div class="action-row">
        <button class="btn-pill-dark" id="refreshBtn">刷新</button>
        <button class="btn-pill-dark" id="rawReportBtn">报告原文</button>
        <button class="btn-pill-dark" id="rawStateBtn">状态快照</button>
        <button class="btn-pill-dark" id="rawProgressBtn">日志全集</button>
      </div>
      <pre id="rawData" aria-live="polite"></pre>
    </div>
  </section>

  <!-- Log: Light Section -->
  <section class="light-section" aria-labelledby="log-title">
    <div class="section-inner-sm">
      <h2 class="section-title" id="log-title">执行日志</h2>
      <p class="eyebrow">底层决策路径全量透明</p>
      <div id="roundLog">
        <div class="card-body empty-state" style="text-align:left;">无活动记录</div>
      </div>
    </div>
  </section>

  <script>
    let currentRunId = "";
    let poller = null;

    function openMobileMenu() {
      document.getElementById("mobileMenu").classList.add("open");
      document.getElementById("hamburgerBtn").setAttribute("aria-expanded", "true");
      document.body.style.overflow = "hidden";
    }
    function closeMobileMenu() {
      document.getElementById("mobileMenu").classList.remove("open");
      document.getElementById("hamburgerBtn").setAttribute("aria-expanded", "false");
      document.body.style.overflow = "";
    }
    document.getElementById("hamburgerBtn").addEventListener("click", openMobileMenu);
    document.getElementById("mobileMenuClose").addEventListener("click", closeMobileMenu);
    document.addEventListener("keydown", function(e) {
      if (e.key === "Escape") closeMobileMenu();
    });

    function setContent(id, text, isHtml) {
      var node = document.getElementById(id);
      if (!node) return;
      if (isHtml) { node.innerHTML = text; } else { node.textContent = text; }
      var isEmpty = !text || text.trim() === "" || text === "...";
      if (isEmpty) { node.classList.add("empty-state"); } else { node.classList.remove("empty-state"); }
    }

    function renderStatus(data) {
      if (!data) return;
      currentRunId = data.run_id || currentRunId;
      var lines = [
        "ID: " + (data.run_id || "-"),
        "目标: " + (data.target || "-"),"""


@dataclass
class JsonResponse:
    status: str
    body: bytes
    content_type: str = "application/json; charset=utf-8"


class WebApp:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress: dict[str, list[dict[str, Any]]] = {}
        self._status: dict[str, dict[str, Any]] = {}

    def get_response(self, path: str) -> JsonResponse:
        if path == "/":
            return JsonResponse(
                status="200 OK",
                body=INDEX_HTML.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )
        return self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def handle_request(self, method: str, path: str, body: bytes) -> JsonResponse:
        parsed = urlparse(path)
        if method == "GET" and parsed.path == "/":
            return self.get_response("/")
        if method == "HEAD" and parsed.path == "/":
            return JsonResponse(
                status="200 OK",
                body=b"",
                content_type="text/html; charset=utf-8",
            )
        if method == "POST" and parsed.path == "/api/run":
            payload = json.loads(body.decode("utf-8") or "{}")
            return self._start_run(str(payload.get("target", "")).strip())
        if method == "GET" and parsed.path.startswith("/api/run/"):
            run_id = parsed.path.rsplit("/", 1)[-1]
            return self._json_response(self._run_payload(run_id))
        if method == "GET" and parsed.path.startswith("/api/report/"):
            run_id = parsed.path.rsplit("/", 1)[-1]
            return self._json_response(load_report_summary(Settings().runs_dir, run_id))
        if method == "GET" and parsed.path.startswith("/api/raw/"):
            run_id = parsed.path.rsplit("/", 1)[-1]
            query = urlparse(path).query
            kind = "report"
            if "kind=" in query:
                kind = query.split("kind=", 1)[1].split("&", 1)[0]
            return self._json_response({"content": load_raw_artifact(Settings().runs_dir, run_id, kind)})
        return self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _start_run(self, target: str) -> JsonResponse:
        if not target:
            return self._json_response({"error": "target is required"}, status=HTTPStatus.BAD_REQUEST)
        run_id = self._spawn_run(target)
        with self._lock:
            status = dict(self._status[run_id])
        return self._json_response(
            {
                "status": status,
                "progress": [],
                "report": load_report_summary(Settings().runs_dir, run_id),
                "outcome": explain_status(status),
            }
        )

    def _run_payload(self, run_id: str) -> dict[str, Any]:
        settings = Settings()
        with self._lock:
            status = dict(self._status.get(run_id, {}))
            progress = list(self._progress.get(run_id, []))
        if not status:
            store = build_controller(settings).store
            state = store.load_state(run_id)
            status = summarize_state(state)
        return {
            "status": status,
            "progress": progress,
            "report": load_report_summary(settings.runs_dir, run_id),
            "outcome": explain_run_outcome(state) if "state" in locals() else explain_status(status),
        }

    def _spawn_run(self, target: str) -> str:
        run_id = f"web-{uuid4().hex[:8]}"
        with self._lock:
            self._status[run_id] = {
                "run_id": run_id,
                "target": target,
                "phase": "queued",
                "round_index": 0,
                "stop_reason": None,
            }
            self._progress[run_id] = []
        thread = threading.Thread(
            target=self._run_research,
            args=(run_id, target),
            daemon=True,
        )
        thread.start()
        return run_id

    def _run_research(self, run_id: str, target: str) -> None:
        settings = Settings()
        hydrate_runtime_secret(settings.api_key_env)

        def reporter(event: Any) -> None:
            payload = event.model_dump(mode="json")
            payload["phase_label"] = _label_phase(payload.get("phase"))
            payload["stage_label"] = _label_stage(payload.get("stage"))
            with self._lock:
                self._progress.setdefault(run_id, []).append(payload)
                self._status[run_id] = {
                    "run_id": run_id,
                    "target": target,
                    "phase": _label_phase(payload.get("phase")),
                    "round_index": payload.get("round_index", 0),
                    "stop_reason": payload.get("stop_reason"),
                }

        controller = build_controller(settings)
        controller.progress_reporter = reporter
        try:
            state = controller.run(target=target, budget=_default_budget())
            state.run_id = run_id
            if state.final_report is None:
                draft = Synthesizer().run(state)
                state.final_report = CitationAgent().run(state, draft)
            _persist_final_artifacts(controller, state)
            with self._lock:
                self._status[run_id] = summarize_state(state)
        except Exception as exc:
            with self._lock:
                self._status[run_id] = {
                    "run_id": run_id,
                    "target": target,
                    "phase": _label_phase("error"),
                    "round_index": 0,
                    "stop_reason": str(exc),
                }

    def _json_response(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> JsonResponse:
        return JsonResponse(
            status=f"{status.value} {status.phrase}",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )


def summarize_state(state: Any) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "target": state.target,
        "phase": _label_phase(getattr(state.current_phase, "value", state.current_phase)),
        "round_index": state.round_index,
        "stop_reason": state.stop_reason,
    }


def load_report_summary(runs_dir: Path, run_id: str) -> dict[str, Any]:
    report_path = Path(runs_dir) / run_id / "artifacts" / "final-report.json"
    if not report_path.exists():
        return {
            "run_id": run_id,
            "target_summary": "",
            "confirmed_competitors": [],
            "key_uncertainties": [],
            "citations": {},
        }
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "run_id": run_id,
        "target_summary": payload.get("target_summary", ""),
        "confirmed_competitors": payload.get("confirmed_competitors", []),
        "key_uncertainties": payload.get("key_uncertainties", []),
        "citations": payload.get("citations", {}),
    }


def load_raw_artifact(runs_dir: Path, run_id: str, kind: str) -> str:
    base = Path(runs_dir) / run_id
    mapping = {
        "report": base / "artifacts" / "final-report.json",
        "state": base / "state.json",
        "progress": base / "artifacts" / "progress-log.jsonl",
    }
    path = mapping.get(kind)
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8").rstrip()


def explain_status(status: dict[str, Any]) -> dict[str, Any]:
    if status.get("stop_reason"):
        return {
            "status": "已停止",
            "confirmed_count": 0,
            "latest_phase": status.get("phase"),
            "latest_plan": "",
            "stop_reason": status.get("stop_reason"),
            "recent_diagnostics": [],
        }
    return {
        "status": "运行中",
        "confirmed_count": 0,
        "latest_phase": status.get("phase"),
        "latest_plan": "",
        "stop_reason": None,
        "recent_diagnostics": [],
    }


def explain_run_outcome(state: Any) -> dict[str, Any]:
    confirmed = getattr(state, "final_report", None)
    confirmed_competitors = []
    if confirmed is not None:
        confirmed_competitors = list(getattr(confirmed, "confirmed_competitors", []) or [])
    latest_trace = state.traces[-1] if getattr(state, "traces", None) else None
    if state.stop_reason and not confirmed_competitors:
        status = "已停止，仍未确认出有效竞品"
    elif state.stop_reason:
        status = "已停止，已有可展示结果"
    else:
        status = "运行中"
    return {
        "status": status,
        "confirmed_count": len(confirmed_competitors),
        "latest_phase": _label_phase(getattr(getattr(latest_trace, "phase", None), "value", None)),
        "latest_plan": getattr(latest_trace, "planner_output", ""),
        "stop_reason": state.stop_reason,
        "recent_diagnostics": list(getattr(latest_trace, "diagnostics", [])[-4:]) if latest_trace else [],
    }


def _label_phase(phase: str | None) -> str:
    if phase is None:
        return "-"
    return PHASE_LABELS.get(str(phase), str(phase))


def _label_stage(stage: str | None) -> str:
    if stage is None:
        return "-"
    return STAGE_LABELS.get(str(stage), str(stage))


def make_app() -> WebApp:
    return WebApp()


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    app = make_app()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            response = app.handle_request("GET", self.path, b"")
            self._write_response(response)

        def do_HEAD(self) -> None:  # noqa: N802
            response = app.handle_request("HEAD", self.path, b"")
            self._write_response(response)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            response = app.handle_request("POST", self.path, body)
            self._write_response(response)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _write_response(self, response: JsonResponse) -> None:
            self.send_response(int(response.status.split(" ", 1)[0]))
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"jingyantai web ui: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def server_bind_address_from_env() -> tuple[str, int]:
    host = os.getenv("JINGYANTAI_WEB_HOST")
    port = os.getenv("JINGYANTAI_WEB_PORT")
    render_port = os.getenv("PORT")
    if render_port and not host:
        host = PUBLIC_HOST
    return host or DEFAULT_HOST, int(port or render_port or DEFAULT_PORT)


if __name__ == "__main__":
    host, port = server_bind_address_from_env()
    run_server(host=host, port=port)
