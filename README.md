# Telegram Codex 橋接器

這個資料夾已經整理成：

- **第一層主要放一般使用者會直接用到的入口**
- 另外保留少量給入口批次檔使用的 launcher helper（`_launch_*.ps1`）
- 程式核心集中在 [`_程式核心`](./_程式核心)
- 開發者文件集中在 [`_開發者文件`](./_開發者文件)

## 一般使用者怎麼用

1. 安裝到這台電腦：
   [02_INSTALL_ON_THIS_PC.cmd](./02_INSTALL_ON_THIS_PC.cmd)
2. 打開控制面板：
   [01_OPEN_CONTROL_PANEL.cmd](./01_OPEN_CONTROL_PANEL.cmd)
3. 看繁中操作手冊：
   [03_MANUAL_zh-TW.md](./03_MANUAL_zh-TW.md)

## GitHub 上傳建議

如果你要把這份資料夾直接當成 GitHub repo：

- 可以直接以上傳這整個資料夾為基礎
- 請保留根目錄的 `_launch_open_control_panel.ps1` 與 `_launch_install_on_this_pc.ps1`
- 不要提交 `_程式核心/.env.local`
- 不要提交 `_程式核心/data`
- 不要提交 `_程式核心/dist`
- 不要提交 `_發布封包/GitHub_可發佈版.zip`

`.gitignore` 已經幫你把這些執行期資料排除。

真正給一般使用者下載安裝的**唯一正式安裝包**，應該是：

- `_發布封包/GitHub_可發佈版.zip`

也就是說：

- GitHub repo：放原始碼與安裝入口
- GitHub Release：放 `GitHub_可發佈版.zip`

## 開發者文件

較技術性的說明放在：

- [README.md](./_開發者文件/README.md)
- [EXE_PACKAGING_SPEC_zh-TW.md](./_開發者文件/EXE_PACKAGING_SPEC_zh-TW.md)
