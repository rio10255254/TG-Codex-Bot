# Telegram Codex Bridge EXE 包裝規格

這份規格的目的不是立即產出 EXE，而是把之後要做成「單檔安裝器 / 單檔控制面板」時的做法固定下來。

---

## 1. 目標

希望最後能交付兩種 EXE：

1. `TelegramCodexBridgeInstaller.exe`
   給第一次安裝的人使用
2. `TelegramCodexBridgeControl.exe`
   給已安裝完成的人日常使用

---

## 2. 安裝器 EXE 要做什麼

`TelegramCodexBridgeInstaller.exe` 需要完成：

- 收集：
  - Telegram bot token
  - Default working directory
  - Allowed chat IDs
  - Pinned projects
- 自動檢查：
  - Python
  - Node.js
  - Codex CLI
- 盡量自動安裝缺少依賴
- 建立 `.env`
- 複製 bridge 主程式
- 建立桌面捷徑
- 註冊 Task Scheduler
- 可選擇安裝後立即啟動

建議來源：

- 以 `install_bridge_gui.ps1` 為安裝器核心
- 用 `ps2exe` 先打成 EXE
- 如果要更完整的 Windows 安裝流程，再外包一層 `Inno Setup`

---

## 3. 控制面板 EXE 要做什麼

`TelegramCodexBridgeControl.exe` 需要完成：

- 顯示目前 bridge 狀態
- `Start`
- `Stop`
- `Restart`
- `Open Logs`
- `Open Folder`
- `Package Zip`
- `Create Shortcut`

建議來源：

- 以 `bridge_control_gui.ps1` 為核心
- 用 `ps2exe` 打成 EXE

---

## 4. 建議包裝順序

### 第一階段

先做 PowerShell GUI 版：

- `install_bridge_gui.ps1`
- `bridge_control_gui.ps1`

這一階段的優點是：

- 開發快
- 邏輯和現在既有腳本共用
- 問題容易追

### 第二階段

再做 EXE 包裝：

- `install_bridge_gui.ps1 -> TelegramCodexBridgeInstaller.exe`
- `bridge_control_gui.ps1 -> TelegramCodexBridgeControl.exe`

### 第三階段

如果要正式對外發布，再加 `Inno Setup`：

- 安裝目錄選擇
- 開始選單捷徑
- 桌面捷徑
- 安裝後自動啟動控制面板

---

## 5. 推薦工具

### 最小可行方案

- `ps2exe`

用途：

- 把 PowerShell GUI 腳本轉成單一 EXE

### 正式安裝器方案

- `Inno Setup`

用途：

- 產出標準 Windows 安裝程式
- 提供安裝精靈
- 可加捷徑、卸載、版本資訊

---

## 6. 交付建議

如果現在要正式給別人用，但還沒做 EXE：

- 先交付 zip
- 內含：
  - `INSTALL_TELEGRAM_CODEX_BRIDGE.cmd`
  - `OPEN_TELEGRAM_CODEX_BRIDGE.cmd`
  - `MANUAL_zh-TW.md`

如果下一階段要升級：

- 再把這三個入口收斂成：
  - `TelegramCodexBridgeInstaller.exe`
  - `TelegramCodexBridgeControl.exe`

---

## 7. 目前實作對應

目前已經完成的基底：

- `install_bridge.ps1`
- `install_bridge_gui.ps1`
- `bridge_control.ps1`
- `bridge_control_gui.ps1`
- `build_portable_package.ps1`

所以要做 EXE 時，不是重寫，而是把既有 GUI 層拿去包裝即可。

