# Telegram Codex Bridge 操作手冊

這份手冊是給正式使用者看的。

目標很簡單：

- 讓你用 Telegram 控制自己電腦上的 Codex
- 不需要自己打開腳本修改設定
- 不需要自己手動找啟動指令

---

## 1. 你會拿到什麼

正式交付包內會有這些重要檔案：

- `INSTALL_TELEGRAM_CODEX_BRIDGE.cmd`
  用來安裝這套橋接器
- `OPEN_TELEGRAM_CODEX_BRIDGE.cmd`
  用來打開本機控制面板
- `Telegram Codex Bridge` 桌面捷徑
  安裝完成後會自動建立
- `.env`
  安裝器會自動建立，不需要手動打開修改

---

## 2. 安裝前你需要準備什麼

你只需要先準備：

1. 一台自己的 Windows 電腦
2. 一個自己的 Telegram 帳號
3. 一個自己的 Telegram bot token

Telegram bot token 的取得方式：

1. 在 Telegram 搜尋 `@BotFather`
2. 傳送 `/newbot`
3. 按指示建立 bot
4. 記下它給你的 token

---

## 3. 第一次安裝

### 方法

1. 解壓縮交付給你的 zip 包
2. 雙擊 `INSTALL_TELEGRAM_CODEX_BRIDGE.cmd`
3. 依畫面輸入：
   - Telegram bot token
   - 允許的 chat id
   - 預設工作資料夾
   - 常用專案路徑

### 你不用自己做的事

安裝器會自動處理：

- 檢查 Python
- 檢查 Node.js
- 檢查 Codex CLI
- 盡量自動安裝缺少的依賴
- 建立 `.env`
- 建立桌面捷徑
- 設定開機登入後自動啟動
- 設定 bot 掛掉後自動重啟

---

## 4. 安裝完成後怎麼開

### 最簡單方式

直接雙擊桌面上的：

- `Telegram Codex Bridge`

這會打開本機控制面板。

### 控制面板可以做什麼

- `Start`
  啟動 bridge
- `Stop`
  停止 bridge
- `Restart`
  重啟 bridge
- `Open Logs`
  打開日誌
- `Open Folder`
  打開 bridge 資料夾
- `Package Zip`
  重新產生可分發 zip
- `Shortcut`
  重建桌面捷徑

---

## 5. Telegram 第一次使用

### 情況 A：你安裝時 allowlist 留空

這是最推薦的方式。

步驟：

1. 打開你的 Telegram bot
2. 傳送 `/start`
3. 如果目前還沒有授權任何人，畫面會出現授權按鈕
4. 點 `Authorize This Chat`
5. 這個聊天就會成為第一個管理者

這樣你不需要回電腦改 `.env`。

### 情況 B：你安裝時已經填了 chat id

那你直接在 Telegram 對 bot 傳 `/start` 即可開始使用。

---

## 6. 要怎麼加別的使用者

如果是正式環境，最推薦：

- 一人一台機器
- 一人一個 bot token

如果真的要同一台機器給多個人用：

1. 先讓一個管理者 chat 已經授權成功
2. 讓新使用者先對 bot 發任何訊息
3. bot 會告訴他自己的 chat id，或你也可以請他用 `/id`
4. 管理者在 Telegram 裡輸入：

```text
/allow <chat_id>
```

例如：

```text
/allow 123456789
```

要移除某人：

```text
/revoke 123456789
```

---

## 7. 平常怎麼用

### 最常用操作

- `Menu`
  打開控制中心
- `Projects`
  切換專案
- `Chats`
  切換對話
- `New Chat`
  開新對話
- `Status`
  看目前任務狀態

### 正常提問

直接送普通文字即可，例如：

```text
先讀一下這個 repo，告訴我目前有哪些主要模組。
```

如果要明確執行命令型操作，也可以用：

```text
/run 幫我修掉登入流程的 bug，改完後跑測試
```

---

## 8. 如果我看不到按鈕或 bot 沒回

先做這幾步：

1. 打開桌面 `Telegram Codex Bridge`
2. 看控制面板右上方狀態是不是 `Running`
3. 如果不是，按 `Start`
4. 如果怪怪的，按 `Restart`
5. 再回 Telegram 傳 `/start` 或 `Menu`

如果還是不行：

1. 在控制面板按 `Open Logs`
2. 看 `bot.err.log`
3. 把錯誤內容提供給維護者

---

## 9. 如果我換了電腦

你不需要把整套重新手工搭一次。

做法：

1. 拿最新交付 zip
2. 解壓縮
3. 執行 `INSTALL_TELEGRAM_CODEX_BRIDGE.cmd`
4. 填入你自己的：
   - bot token
   - 預設工作資料夾
   - 專案路徑

然後再到 Telegram 對 bot 發 `/start` 就可以。

---

## 10. 安全提醒

這套 bridge 目前設計是高權限模式：

- `CODEX_SANDBOX=danger-full-access`
- `CODEX_APPROVAL_POLICY=never`

意思是：

- 只要你的 Telegram chat 被授權
- 就能直接用 bot 操作這台電腦上的 Codex

所以正式使用時請務必記住：

1. 最好一人一台機器、一人一個 bot
2. 不要把不信任的 chat id 加進 allowlist
3. 如果懷疑有人不該再用，立刻 `/revoke <chat_id>`

---

## 11. 給交付對象的一句話版本

如果你只是想知道最短操作：

1. 雙擊 `INSTALL_TELEGRAM_CODEX_BRIDGE.cmd`
2. 填入你的 bot token
3. 雙擊桌面 `Telegram Codex Bridge`
4. 到 Telegram 對 bot 發 `/start`
5. 點授權按鈕或直接開始用

