from ok.feature.Box import Box, find_boxes_by_name  # 检测框对象与按名过滤工具（find_boxes_by_name 用于复刻 ocr(match=...) 的过滤语义）。
from ok.task.exceptions import WaitFailedException  # 界面断言失败时抛出的等待失败异常（由 try_step 捕获恢复）。


_CACHE_MISS = object()  # 帧级判定缓存的「未命中」哨兵：与「命中但结果为 None」区分。


class ScreenMixin:
    """界面识别系统 + 帧级判定缓存。

    界面统一注册进 `self.screens`（判定描述含 features/keywords/ocr_box 等扩展字段），
    判定结果按帧缓存——同一帧内重复的模板匹配/区域 OCR 只真正执行一次；新帧覆盖旧帧
    （`next_frame` 清缓存），无陈旧风险。
    """

    def next_frame(self):
        """覆写框架取帧：拿到新帧后清空帧级判定缓存。

        框架抛出的 TaskDisabledException/WaitFailedException 等异常原样向上传播；
        取帧失败时不清缓存（旧帧未变，缓存仍然有效）。
        """
        frame = super().next_frame()  # 框架取新帧。
        self._screen_cache.clear()  # 新帧已就位，旧帧判定结果全部失效。
        return frame

    def _cache_get(self, key):
        entry = self._screen_cache.get(key)  # 条目结构 (帧对象, 结果)。
        if entry is not None and entry[0] is self.frame:  # 帧对象同一性成立才视为命中。
            return entry[1]
        return _CACHE_MISS

    def _cache_put(self, key, value):
        self._screen_cache[key] = (self.frame, value)  # 记录结果所属的帧。

    def _find_feature_cached(self, name):
        """带帧级缓存的 find_one：同一帧内同名特征只真正匹配一次。"""
        key = ("feat", name)
        cached = self._cache_get(key)
        if cached is not _CACHE_MISS:
            return cached
        found = self.find_one(name)  # ValueError（特征缺失）由调用方处理，不进缓存。
        self._cache_put(key, found)
        return found

    @staticmethod
    def _ocr_box_key(box):
        if isinstance(box, Box):  # coco 区域框：按坐标归一化，同框不同名也可共享。
            return ("box", round(box.x, 3), round(box.y, 3), round(box.width, 3), round(box.height, 3))
        return ("box", tuple(round(v, 3) for v in box))  # 相对坐标列表 [x, y, to_x, to_y]。

    def _region_ocr_cached(self, box_key, box):
        """带帧级缓存的区域 OCR（不做关键词过滤），同帧同区域只真正 OCR 一次。"""
        key = ("ocr", box_key)
        cached = self._cache_get(key)
        if cached is not _CACHE_MISS:
            return cached
        if box is None:  # 全屏 OCR。
            result = self.ocr()
        elif isinstance(box, (list, tuple)):  # 相对坐标列表形式。
            result = self.ocr(*box)
        else:  # 已解析的区域框。
            result = self.ocr(box=box)
        self._cache_put(key, result)
        return result

    def register_screen(self, name: str, features=(), keywords=(), ocr_box=None, **extra):
        """注册一个界面及判定条件。

        全局界面已由基类从 src/screens.py 的 SCREENS 加载；本方法是任务的
        扩展口：可追加任务私有界面，同名调用覆盖全局（或先前）条目。
        扩展字段（absent/priority/min_frames 等）经 **extra 原样并入判定描述。

        Args:
            name: 界面名（子任务用 is_screen/wait_screen/assert_screen 时传入的名称）。
            features: coco 标注的模板特征名列表，全部命中才判定为该界面。
            keywords: OCR 关键词列表，任一命中即判定为该界面（多用于无稳定模板的页面）。
            ocr_box: 可选 OCR 区域，避免全屏 OCR 的开销。可为相对坐标列表
                [x, y, to_x, to_y]，也可为 coco 标注的区域特征名（字符串），
                匹配时按当前分辨率解析。
        """
        self.screens[name] = {  # 保存界面判定描述到注册表；扩展字段（absent/priority/min_frames）原样并入。
            "features": list(features),  # 模板特征名列表。
            "keywords": list(keywords),  # OCR 关键词列表。
            "ocr_box": ocr_box,  # OCR 区域相对坐标。
            **extra,  # 扩展字段：缺省时为空，不改变既有条目结构。
        }

    def _screen_match(self, spec: dict) -> bool:
        """按判定描述在当前帧检测是否处于该界面。

        features 与 keywords 同时配置时取「与」：所有特征命中 且 命中任一关键词。
        any_features（任一命中特征，与 features 的「全部命中」相对）与 keywords
        同时配置时同样取「与」：任一特征命中 且 命中任一关键词。
        absent 中的特征（消歧字段，默认空）任一命中则直接判负，作用于各条命中路径。
        """
        features = spec.get("features")  # 模板特征名列表。
        keywords = spec.get("keywords")  # OCR 关键词列表。
        absent = spec.get("absent") or []  # 消歧特征：任一命中即否定该界面。
        if features:  # 有模板特征则先逐个检测特征。
            for name in features:  # 逐个检测特征。
                try:  # 特征可能已不存在（如 coco 重建后旧特征被移除）。
                    found = self._find_feature_cached(name)  # 查找模板特征（同帧只匹配一次）。
                except ValueError:  # 特征缺失时视为未命中，避免因 coco 变更导致异常冒泡。
                    self.log_warning(f"界面特征缺失: {name}")  # 记录缺失。
                    return False  # 返回未命中。
                if found is None:  # 任一特征缺失则不在该界面。
                    return False  # 返回未命中。
            if not keywords:  # 未配置关键词时特征全部命中即判定为该界面。
                return self._check_absent(absent)  # absent 检查后返回。
            if not self._match_ocr_keywords(spec):  # 同时配置了关键词则还需命中任一关键词。
                return False  # 关键词未命中。
            return self._check_absent(absent)  # 关键词命中后再做 absent 检查。
        if spec.get("any_features"):  # 任一命中特征：任一特征在当前帧命中即视为特征命中。
            if not self._match_any_features(spec):  # 逐个检测，任一命中即通过。
                return False  # 全部未命中。
            if not keywords:  # 未配置关键词时任一特征命中即判定为该界面。
                return self._check_absent(absent)  # absent 检查后返回。
            if not self._match_ocr_keywords(spec):  # 同时配置了关键词则还需命中任一关键词。
                return False  # 关键词未命中。
            return self._check_absent(absent)  # 关键词命中后再做 absent 检查。
        if keywords:  # 无模板特征时退化为 OCR 关键词判定。
            if not self._match_ocr_keywords(spec):  # 按关键词判定。
                return False  # 关键词未命中。
            return self._check_absent(absent)  # 关键词命中后再做 absent 检查。
        self.log_warning(f"界面 {spec} 未配置判定条件")  # 记录空配置。
        return False  # 空配置判定为不在该界面。

    def _match_any_features(self, spec: dict) -> bool:
        """any_features 判定：列表中任一特征在当前帧命中即返回 True（「或」语义）。

        feature_box（可选，coco 区域特征名）限定匹配区域，缺失时退化为全屏匹配；
        区域匹配不做帧级缓存（小区域模板匹配开销低，且轮询判定每轮都是新帧）。
        """
        raw_box = spec.get("feature_box")  # 可选匹配区域。
        box = None  # None 表示全屏匹配。
        if isinstance(raw_box, str):  # 区域限定为 coco 区域特征名。
            try:  # 区域特征可能缺失。
                box = self.get_box_by_name(raw_box)  # 按当前分辨率解析区域框。
            except ValueError:  # 区域缺失时退化为全屏匹配。
                box = None  # 置空走全屏逻辑。
        for name in spec.get("any_features") or ():  # 逐个检测任一命中特征。
            try:  # 特征可能已不存在（如 coco 重建后旧特征被移除）。
                found = self.find_one(name, box=box) if box is not None \
                    else self._find_feature_cached(name)  # 区域匹配或全屏缓存匹配。
            except ValueError:  # 特征缺失时视为未命中，避免因 coco 变更导致异常冒泡。
                self.log_warning(f"界面特征缺失: {name}")  # 记录缺失。
                continue  # 检查下一个特征。
            if found is not None:  # 任一特征命中。
                return True  # 判定通过。
        return False  # 全部未命中。

    def _check_absent(self, absent) -> bool:
        """absent 消歧检查：列表中任一特征在当前帧命中则返回 False。走与 features 相同的缓存查找路径。"""
        for name in absent:  # 逐个检测消歧特征。
            try:  # 与 features 相同的容错：特征缺失视为未命中。
                if self._find_feature_cached(name) is not None:  # 消歧特征命中。
                    return False  # 该界面判定失败。
            except ValueError:  # coco 变更导致特征缺失时按未命中处理。
                self.log_warning(f"界面 absent 特征缺失: {name}")  # 记录缺失。
        return True  # 无消歧特征命中。

    def _match_ocr_keywords(self, spec: dict) -> bool:
        """按界面判定描述在当前帧 OCR 匹配关键词，命中任一关键词返回 True。

        同帧内共享同一区域的 OCR 结果（未过滤的全量文本框），各条目的关键词集
        各自比对——与框架 ocr(match=...) 的过滤语义逐位一致；全屏退化路径按
        条目隔离，不跨界面合并。
        """
        raw_box = spec.get("ocr_box")  # 读取可选 OCR 区域。
        box = None  # None 表示全屏 OCR。
        box_key = ("full", id(spec))  # 全屏退化不合并：键带上条目身份互相隔离。
        if isinstance(raw_box, str):  # ocr_box 为 coco 区域特征名时解析为当前分辨率的框。
            try:  # 特征可能缺失。
                box = self.get_box_by_name(raw_box)  # 解析区域框。
                box_key = self._ocr_box_key(box)
            except ValueError:  # 特征缺失时退化为全屏 OCR（与现状一致）。
                box = None  # 置空走全屏逻辑。
        elif isinstance(raw_box, (list, tuple)):  # 相对坐标列表形式。
            box = raw_box
            box_key = self._ocr_box_key(raw_box)
        elif raw_box is not None:  # 直接给了 Box 对象。
            box = raw_box
            box_key = self._ocr_box_key(raw_box)
        boxes = self._region_ocr_cached(box_key, box)  # 同帧同区域只跑一次 OCR。
        matched = find_boxes_by_name(boxes, self.fix_match_regex(spec["keywords"]))  # 与 ocr(match=...) 相同的过滤。
        return bool(matched)  # 命中任一关键词即判定为该界面。

    def current_screen(self) -> str | None:
        """在当前帧识别所处界面，返回界面名；未命中返回 None（常用于失败日志）。

        按 spec 的 priority 降序遍历（默认 0）；同优先级保持注册顺序
        （sorted 稳定排序），消除对注册先后顺序的隐性依赖。
        """
        ordered = sorted(self.screens.items(), key=lambda item: -item[1].get("priority", 0))  # 降序且稳定。
        for name, spec in ordered:  # 遍历所有已注册界面。
            if self._screen_match(spec):  # 命中则返回该界面名。
                return name  # 返回界面名。
        return None  # 全部未命中返回 None。

    def is_screen(self, name: str) -> bool:
        """单帧检测当前是否处于指定界面。

        恒为单帧语义：即使 spec 配置了 min_frames，本方法也不做多帧确认；
        连续帧确认仅作用于 wait_screen/assert_screen 的轮询判定。
        """
        spec = self.screens.get(name)  # 读取界面判定描述。
        if spec is None:  # 界面未注册。
            self.log_warning(f"未注册界面: {name}")  # 记录未注册。
            return False  # 未注册判定为不在该界面。
        return self._screen_match(spec)  # 按判定描述检测。

    def wait_screen(self, name: str, time_out=10, raise_if_not_found=False):
        """等待进入指定界面，复用 wait_until 的轮询与超时机制。

        spec 的 min_frames（默认 1）表示需连续多少次轮询命中才算进入：
        轮询条件每轮在不同帧上求值，连续命中计数天然逐帧；未命中即清零。
        默认值下与原单帧判定行为一致。
        """
        spec = self.screens.get(name)  # 读取界面判定描述。
        if spec is None:  # 界面未注册。
            raise ValueError(f"未注册界面: {name}")  # 未注册直接报错。
        min_frames = max(1, int(spec.get("min_frames", 1)))  # 缺省退化为单帧语义。
        consecutive = {"hits": 0}  # 实例级计数状态：跨轮次递增，未命中清零。

        def condition():  # 轮询条件：wait_until 每轮取新帧后调用一次。
            if self._screen_match(spec):  # 本轮命中。
                consecutive["hits"] += 1  # 连续命中数递增。
            else:  # 本轮未命中。
                consecutive["hits"] = 0  # 清零重来。
            return consecutive["hits"] >= min_frames  # 达到连续帧要求才算进入。

        return self.wait_until(condition,  # 轮询界面判定条件。
                               time_out=time_out,  # 超时时间。
                               raise_if_not_found=raise_if_not_found)  # 超时是否抛异常。

    def assert_screen(self, name: str, time_out=10):
        """断言处于指定界面，超时抛 WaitFailedException（由 try_step 捕获并恢复）。"""
        if not self.wait_screen(name, time_out=time_out):  # 等待界面超时。
            cur = self.current_screen()  # 识别当前实际界面用于日志。
            self.log_warning(f"界面断言失败: 期望 {name}，当前 {cur}")  # 记录断言失败。
            raise WaitFailedException(f"not on screen: {name} (current: {cur})")  # 抛等待失败异常。