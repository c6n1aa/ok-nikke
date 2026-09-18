<div align="center">
  <h1 align="center">
    <img src="icons/icon.png" width="120" alt="ok-nikke logo"/>
    <br/>
    ok-nikke
  </h1>

  <p>
    一个基于图像识别的《胜利女神：NIKKE》自动化程序，基于 <a href="https://ok-script.com">ok-script</a> 开发。
    <br />
    An image-recognition-based automation tool for Goddess of Victory: NIKKE, developed with <a href="https://ok-script.com">ok-script</a>.
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

### 关于游戏官方对自动化程序的态度

2026/09/16 官方公告原文如下：

> **3-2. 宏程序及输入自动化程序**
>
> 在《胜利女神：妮姬》中，对于本应由玩家手动完成的操作，严禁借助非游戏官方提供的外部程序或设备达成输入的自动化、重复或取代。
>
> 利用鼠标宏、连点程序、自动化脚本、自动挂机程序等外部手段取代玩家手动操作的行为均属此类。
>
> 此类行为通过外部手段取代手动操作过程，可能对战斗结果产生不当影响，并在竞技玩法中影响排名与奖励。
>
> 如果公开具体的程序种类及检测目标清单，可能会被用于规避检测或恶意利用，因此不便公开。但我们将持续检查并优化检测目标及相关程序清单，以便在自动核验阶段更准确地确认实际使用情况，并同步更加细致地核对输入与游玩纪录。
>
> **处罚期限变更：最长 10 年账号使用限制**
>
> 我们将综合考量违规次数、使用时长、重复性、是否规避检测或限制措施、对竞技玩法造成的影响以及不当得利情况等因素，实施分级处罚。
>
> 特别是反复规避相关限制或持续进行相同行为时，将视为较严重的违规情节。

**请务必知悉：使用本软件存在账号被限制或封禁的风险，且官方处罚可长达 10 年。请自行评估后再决定是否使用。**

**使用本软件即表示您已阅读、理解并同意以上声明，并自愿承担一切潜在风险。**

## 🚀 快速开始

1. 从 [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) 下载便携包 `ok-nikke-win32-portable.zip`，解压到任意英文目录。
2. 以管理员身份运行 `ok-nikke.exe`。
3. 启动游戏本体
4. 打开“日常设置”界面，对需要运行的任务进行开关、配置
![daily_config.png](docs/images/daily_config.png)
5. 回到“任务”界面，点击“日常”开始
![task.png](docs/images/task.png)

注意事项：

- **必须以管理员身份启动**：如果游戏以管理员权限运行，自动化程序也需要同等权限，否则截图或输入可能失效。
- 游戏分辨率需为 16:9 且不低于 1600×900。
- 输入方式：`SyntheticTouch` 走合成触控指针（WM_POINTER）绕开游戏输入过滤，需要游戏窗口位于前台。
- 更多运行与常见问题细节见文档[快速开始](docs/getting-started.md)。

## 🗑️ 卸载应用

删除整个应用目录即可。

## 📝 TODO

- [ ] i18n
- [ ] TBD

## ✨ 功能一览

| 任务 | 说明 |
| --- | --- |
| 日常 | 按日常任务设置执行的编排任务，串联以下子任务 |
| 收获 | 收取友情点、邮箱与 PASS（活动/任务通行证）奖励 |
| 歼灭 | 防御前哨基地收菜，可选使用珠宝追加次数 |
| 付费商店 | 领取付费商店 STEP UP / 每日 / 每周 / 每月免费礼包 |
| 商店 | 购买普通 / 竞技场 / 废铁商店商品 |
| 招募 | 活动免费招募 / 友情点招募 / 普通招募 |
| 前哨基地 | 派遣 / 咨询 / 突发剧情 |
| 方舟 | 企业塔 / 模拟室 / 拦截战 / 竞技场 |
| Raid | 限时挑战（协同作战 / 个人突袭） |
| 活动 | 限时活动通用处理（签到印章 / 剧情推图+扫荡 / 挑战） |


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
uv sync

# Debug 模式（含截图/标注等开发工具）
.\.venv\Scripts\python.exe main_debug.py

# 发布模式
.\.venv\Scripts\python.exe main.py
```

> 依赖由 `uv` 管理：`uv sync` 按 `uv.lock` 建 `.venv`；`uv export --no-dev` 生成交付锁 `requirements.txt`（`exclude-dependencies` 已剔除 `pyside6` 元包/addons，只装 `pyside6-essentials`；`update.py` 的应用内更新仍用 `pip install --no-deps`）。

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
- [MaaFramework](https://github.com/MaaXYZ/MaaFramework) — 合成触控指针（WM_POINTER）交互方式取自该框架
