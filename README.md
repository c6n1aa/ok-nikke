<div align="center">
  <h1 align="center">
    <img src="icons/icon.png" width="120" alt="ok-nikke logo"/>
    <br/>
    ok-nikke
  </h1>

  <p>
    一个基于图像识别的《胜利女神：NIKKE》自动化程序，PC 客户端仅支持前台运行，基于 <a href="https://ok-script.com">ok-script</a> 开发。
    <br />
    An image-recognition-based automation tool for Goddess of Victory: NIKKE; the PC client only supports foreground running, developed with <a href="https://ok-script.com">ok-script</a>.
  </p>

  <p><i>通过 Windows 接口模拟用户进行操作，无内存读取、无文件修改</i></p>

  <p>专注日常自动化，解放老登双手</p>
</div>

### [English](README_en.md) | 中文说明

---

**应用开发基于最新游戏进度的早期游戏账号，部分功能可能适配不完整**

## ⚠️ 免责声明

本软件为外部辅助工具，旨在自动化《胜利女神：NIKKE》Windows 客户端的部分游戏流程。它完全通过模拟常规用户界面与游戏交互，遵循相关法律法规，不会修改任何游戏文件或数据。

本软件开源、免费，仅供个人学习与交流使用，请勿用于任何商业或营利性目的。开发者团队拥有本项目的最终解释权。因使用本软件而产生的任何问题（包括但不限于账号被限制或封禁），均与本项目及开发者无关。

**使用本软件即表示您已阅读、理解并同意以上声明，并自愿承担一切潜在风险。**

## 🚀 快速开始

1. 从 [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) 下载最新 `ok-nikke-win32-portable.zip`，解压到任意目录。
2. 按网络环境将便携包根目录的 `pyappify-cn.yml` 或 `pyappify-global.yml` 重命名为 `pyappify.yml`（与 `ok-nikke.exe` 同目录），作为更新源配置。
3. 以管理员身份运行 `ok-nikke.exe`。

注意事项：

- **必须以管理员身份启动**：如果游戏以管理员权限运行，自动化程序也需要同等权限，否则截图或输入可能失效。
- 游戏分辨率需为 16:9 且不低于 1600×900。
- 更多运行与常见问题细节见文档[快速开始](docs/getting-started.md)。

## 📝 TODO

- [ ] 活动剧情/活动区域
- [ ] 超频模拟室
- [ ] i18n

## ✨ 功能一览

| 任务 | 说明 |
| --- | --- |
| 日常 | 按日常任务设置执行的编排任务，串联以下子任务 |
| 收获 | 收取友情点与邮箱奖励 |
| 歼灭 | 防御前哨基地收菜，可选使用珠宝追加次数 |
| 付费商店 | 领取付费商店 STEP UP / 每日 / 每周 / 每月免费礼包 |
| 商店 | 购买普通 / 竞技场 / 废铁商店商品 |
| 招募 | 活动免费招募 / 友情点招募 / 普通招募 |
| 前哨基地 | 派遣 / 咨询 / 突发剧情 |
| 方舟 | 企业塔 / 模拟室 / 拦截战 / 竞技场 |
| Raid | 限时挑战（协同作战 / 个人突袭） |


## 🔧 疑难解答

如果遇到问题，请在提问前按以下步骤逐一排查：

1. **安装路径**：请确保软件安装在纯英文路径下，避免包含中文字符的文件夹。
2. **杀毒软件**：将软件的安装目录添加到您的杀毒软件（包括 Windows Defender）的信任区或白名单中，以防文件被误删或拦截。
3. **显示设置**：
   - 关闭 Windows 自动 HDR。
   - 画质设置：推荐越高越好。
4. **游戏语言**：优先使用简体中文。
5. **软件版本**：检查并确保您使用的是最新版本。
6. **寻求帮助**：如果以上步骤都无法解决您的问题，请通过ISSUE或社区渠道提交详细的错误报告。

## 💻 开发者专区

从源码运行，仅支持 Python 3.12（其他版本未测试）：

```powershell
git clone https://github.com/c6n1aa/ok-nikke.git
cd ok-nikke
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade

# Debug 模式（含截图/标注等开发工具）
.\.venv\Scripts\python.exe main_debug.py

# 发布模式
.\.venv\Scripts\python.exe main.py
```

> 必须用 `--no-deps`：依赖已在 `requirements.txt` 中锁定（含全部传递依赖），让 pip 解析依赖会装到 `pyside6` 元包与 addons 模块。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMain
# 全量：逐文件独立进程运行
.\run_tests.ps1
```

更多开发文档：[开发环境](docs/development.md) · [应用配置](docs/configuration.md) · [任务开发](docs/tasks.md) · [界面识别与失败恢复](docs/screen-and-recovery.md) · [打包与发布](docs/release.md)

本项目基于 [ok-script](https://ok-script.com) 框架开发，简单易维护。欢迎使用 [ok-script](https://ok-script.com) 开发您自己的自动化项目。

## ❤️ 致谢

- [ok-script](https://github.com/ok-oldking/ok-script)
