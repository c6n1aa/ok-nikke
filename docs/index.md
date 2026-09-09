# ok-nikke

[English](en/index.md)

ok-nikke 是基于 [ok-script](https://github.com/ok-oldking/ok-script) 的《NIKKE：胜利女神》（Goddess of Victory: NIKKE）Windows 客户端自动化应用。它通过 Windows 图形捕获与输入模拟完成游戏内流程，不读取内存、不修改游戏文件。

## 功能

- **后台运行**：优先使用 WGC 捕获，游戏窗口最小化或被遮挡时仍可运行。
- **图像识别**：OpenCV 模板匹配（COCO 标注管理素材）结合 onnxocr（PaddleOCR v5 + OpenVINO）识别文字与按钮。
- **分辨率自适应**：支持 16:9（最低 1600×900），素材以 2560×1440 为基准，按当前分辨率自动缩放匹配。
- **完成状态**：按日/周记录任务完成情况，避免重复执行。
- **失败恢复**：流程卡住时自动清理弹窗、返回大厅重试，无需人工干预。

## 已实现任务

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

## 从这里开始

- 只想使用：按[快速开始](getting-started.md)下载便携包或直接运行源码，无需阅读开发文档。
- 参与开发：

1. [快速开始](getting-started.md)：准备 Python 3.12 环境、运行与测试命令。
2. [应用配置](configuration.md)：运行目标、任务清单、自定义 Tab 与补丁入口。
3. [任务开发](tasks.md)：新增任务、注册任务与编写测试。
4. [界面识别与失败恢复](screen-and-recovery.md)：任务开发的核心约定，写任务前必读。
5. [任务简报模板](task_brief_template.md)：用简报驱动 AI 生成任务代码。
6. [打包与发布](release.md)：tag 触发的便携包发布流程。
7. [文档网站](documentation.md)：本地预览与 GitHub Pages 部署。

## 功能演示

### API 列表与脚本录制

![API 列表与脚本录制](images/image_scripting.png)

### 多种截图与交互方式

![截图与交互方式](images/image_capture.png)

### 标注管理与模板匹配

![模板匹配](images/image_template.png)

![标注管理](images/image_markup.png)

## 继续阅读（ok-script 上游文档）

- [游戏自动化入门](https://github.com/ok-oldking/ok-script/blob/master/docs/intro_to_automation/README.md)
- [快速开始](https://github.com/ok-oldking/ok-script/blob/master/docs/quick_start/README.md)
- [进阶使用](https://github.com/ok-oldking/ok-script/blob/master/docs/after_quick_start/README.md)
- [API 文档](https://github.com/ok-oldking/ok-script/blob/master/docs/api_doc/README.md)
