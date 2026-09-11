# 国际化待办

- 基准语种：简体中文（源码直接写中文，其它语言一律进 `i18n/<locale>/LC_MESSAGES/` 翻译）。
- 支持语言：`zh_CN` / `zh_TW` / `en_US` / `ja_JP`（与 `src/patches/language.py` 的 `supported_locales()` 一致）。
- 词条：`ok.po` 翻应用 UI，`ocr.po` 翻游戏画面文字；改完 `.po` 必须编译 `.mo`：
  `.\.venv\Scripts\python.exe .agents\skills\ok-script-i18n\scripts\task_i18n_helper.py compile`

## 已完成

- [x] 四语言词条目录；模板任务 `MyOneTimeTask` 源串中文化、测试同步
- [x] `ocr.po` 骨架 + 已实证条目（英文 16 条、日文 10 条、繁中 3 条）
- [x] OCR 匹配容错：`src/screens.py` 关键词与各任务 pattern 统一为忽略大小写的正则
- [x] 语言下拉与 debug 词条生成只保留支持语言（`src/patches/language.py`）
- [x] 词条编译统一由 `ok-script-i18n` 技能脚本负责（删除临时脚本）

## 待办

### 1. 正式任务元数据词条（未开始，量大，一个任务一次提交）

`DailyTask` / `HarvestTask` / `OutpostDefenseTask` / `CashShopTask` / `ShopTask` /
`RecruitTask` / `OutpostTask` / `ArkTask` / `RaidTask` / `ExtrasTask` / `DebugTask` 的
`name` / `description` / `default_config` / `config_description` / `config_type` 字符串。

### 2. `ocr.po` 缺口（要客户端文案，不接受自译）

- [ ] `赛季已结束`：英文待截图
- [ ] 提示语（`确认` / `全部领取` / `点击领取奖励` / `点击任意处` / `点击进行` / `资金不足`）：
      日文、繁中缺失（英文已补）
- [ ] 日文：`百货商店` / `付费商店` / `免费` / `每日` / `每周` / `每月` 及上述提示语
- [ ] 繁中：商店五类（百货/付费/普通/竞技场/废铁）、`招募队员` / `拦截战` / `方舟` /
      `派遣公告栏` / `免费` / `每日` / `每周` / `每月` 及上述提示语
      （繁中资料来源少，现有条目来自巴哈姆特、GameVika 繁中、萌娘百科）

### 3. 打包与发布

- [x] 便携包 / Release 含 `i18n/**`（尤其 `.mo`）：`build.yml` 用 `git archive` 打包，git 跟踪文件全量进包

### 4. 实机验证（非中文客户端）

- [ ] `screens.py` 关键词从「字符串全等」改为「正则部分匹配」后，确认无误命中（如 `咨询`）
- [ ] 各任务 OCR pattern 在目标语言画面下是否命中

### 5. 未纳入词条的 UI 文本（见 i18n 盘点，按需排期）

- [ ] `src/ui/UpdateCard.py`、`src/ui/DailyTab.py` 的硬编码控件文本（需 `og.app.tr` 包裹）
- [ ] `src/patches/`：`tasks_tab` 重置按钮与 InfoBar、`start_controller` 启动提示、
      `basic_options` 选项文案、`notification_tab` 卡片描述
- [ ] `src/update_config.py` 更新源文案、`src/config.py` 的 links
- [ ] 日志 / 异常文案（可选，量大）

### 6. 技术债

- [ ] 技能脚本的「去空格变体」按 msgid 生成，中文基准下产生无用条目（`ok.po` 11 条）；
      建议只对拉丁字母 msgid 生效
- [x] OCR 结果反向归一化：评估结论为不需要（与 pattern 翻译冲突，详见提交记录）

## 审核结论

- 词条覆盖：`scan --task src/tasks/MyOneTimeTask.py` 的源串已全部进入 `en_US/ok.po`
  （仅 `text` / `callback` 等 config_type 元数据键不翻）。
- 已跑测试（逐文件独立进程，全绿）：`TestMain`、`TestScreenRecovery`、`TestScreenRegistryIntegrity`、
  `TestShopTask`、`TestArkTask`、`TestOutpostTask`、`TestRecruitTask`、`TestCashShopTask`、
  `TestDailyTask`、`TestDailySubtasks`、`TestExtrasTask`、`TestRaidTask`、`TestDebugTask`、
  `TestBattleWait`、`TestFrameCache`、`TestRedDot`、`TestUpdateConfig`、`TestUpdateScript`、
  `TestDailyLoginReward`、`TestNoticePopup`、`TestPopupBlankClose`、`TestRupeePopup`。
