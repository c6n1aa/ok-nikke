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
</div>

### [English](README_en.md) | 中文说明

---

## ⚠️ 免责声明

本软件为外部辅助工具，旨在自动化《胜利女神：NIKKE》Windows 客户端的部分游戏流程。它完全通过模拟常规用户界面与游戏交互，遵循相关法律法规，不会修改任何游戏文件或数据。

本软件开源、免费，仅供个人学习与交流使用，请勿用于任何商业或营利性目的。开发者团队拥有本项目的最终解释权。因使用本软件而产生的任何问题（包括但不限于账号被限制或封禁），均与本项目及开发者无关。

**使用本软件即表示您已阅读、理解并同意以上声明，并自愿承担一切潜在风险。**

## ✨ 主要功能

- **前台运行**：PC 客户端仅支持前台运行（Pynput / PyDirect 输入），需保持游戏窗口在前台可见。
- **图像识别**：OpenCV 模板匹配（COCO 标注管理素材）结合 onnxocr（PaddleOCR v5 + OpenVINO）识别文字与按钮。
- **分辨率自适应**：流畅支持 16:9 分辨率（最低 1600×900），素材按当前分辨率自动缩放匹配。
- **自动完成状态**：内置每日/每周完成状态管理，避免重复执行。
- **失败自动恢复**：识别失败或流程卡住时自动返回大厅重试，无需人工干预。

已实现的任务：

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

## 🚀 快速开始

从源码运行，需 Python 3.12（其他版本未测试）：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-deps -r requirements.txt --upgrade

# Debug 模式（含开发工具）
python main_debug.py

# 发布模式
python main.py
```

如果目标游戏以管理员权限运行，自动化程序也需要以管理员身份启动，否则截图或输入可能无法生效。详细的运行目标配置与打包流程见[快速开始](docs/getting-started.md)。

## 📥 下载渠道

- **[GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases)**：官方发布页，每个 tag 提供一个 `ok-nikke-win32-portable.zip` 便携包，解压到任意目录后运行其中的 `ok-nikke.exe`（需管理员权限）。

## 📖 文档

完整文档整理为 MkDocs 网站，可通过 `python -m mkdocs serve` 本地预览：

- [文档首页](docs/index.md)
- [快速开始](docs/getting-started.md)
- [应用与运行目标配置](docs/configuration.md)
- [任务开发](docs/tasks.md)
- [界面识别与失败恢复](docs/screen-and-recovery.md)
- [打包与发布](docs/release.md)
- [English documentation](docs/en/index.md)

## 💻 开发者专区

运行测试（需先完成环境安装）：

```powershell
python -m unittest tests.TestMain
# 全量：逐文件独立进程运行
.\run_tests.ps1
```

本项目基于 [ok-script](https://ok-script.com) 框架开发，简单易维护。欢迎使用 [ok-script](https://ok-script.com) 开发您自己的自动化项目。

## ❤️ 致谢

- [ok-script](https://github.com/ok-oldking/ok-script)