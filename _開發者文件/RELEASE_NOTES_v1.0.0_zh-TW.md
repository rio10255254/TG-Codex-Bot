# Telegram Codex 橋接器 v1.0.0 發布說明

## 版本定位

這是第一版可正式交付的 Telegram Codex Bridge。

目標：

- 讓使用者能在 Windows 電腦上用 Telegram 控制本機 Codex
- 提供本機控制面板
- 提供可直接交付的安裝包
- 盡量避免使用者手動編輯檔案

## 本版重點

- 提供 Telegram bot 橋接器主程式
- 提供本機 Windows 控制面板
- 提供 GUI 安裝器
- 提供 GitHub 下載包可直接雙擊使用的根目錄 launcher entry
- 提供自動啟動與自動重啟
- 提供 Telegram 首次 claim 機制
- 提供 `/allow` 與 `/revoke`
- 提供整合 TG / 本機 Codex session 的 `Chats`
- 提供歡迎畫面與控制中心 UI

## 交付內容

- `GitHub_可發佈版.zip`
- `03_MANUAL_zh-TW.md`
- `01_INSTALL_ON_THIS_PC.cmd`
- `02_OPEN_CONTROL_PANEL.cmd`
- `04_UNINSTALL_ON_THIS_PC.cmd`
- `_程式核心/`
- `_開發者文件/`

## 使用方式

一般使用者：

1. 解壓安裝包
2. 執行 `01_INSTALL_ON_THIS_PC.cmd`
3. 安裝完成後執行 `02_OPEN_CONTROL_PANEL.cmd`
4. 到 Telegram 對 bot 發 `/start`

## 注意事項

- 正式使用建議一人一台機器、一人一個 bot token
- 預設為高權限模式
- 請勿把 `.env.local`、`data/` 內容提交到公開 repo
