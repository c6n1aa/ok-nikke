import os

import numpy as np

from src.patches import apply_all  # 受控补丁唯一入口

apply_all()  # 启动器/运行时/任务列表等补丁，必须在 ok.OK(config) 构造前应用

version = "dev"
#不需要修改version, Github Action打包会自动修改


config = {
    'custom_tasks': False,  # 关闭后正式版不显示「脚本」「模板」tab, 也不加载 ok_tasks 自定义脚本
    'debug': False,  # Optional, default: False
    'config_folder': 'configs', #最好不要修改
    'global_configs': [],
    # 'screenshot_processor': make_bottom_right_black, # 在截图的时候对frame进行修改, 可选
    'gui_icon': 'icons/icon.png', #窗口图标, 最好不需要修改文件名
    'wait_until_before_delay': 0,
    'wait_until_check_delay': 0,
    'wait_until_settle_time': 1, #调用 wait_until时候, 在第一次满足条件的时候, 会等待再次检测, 以避免某些滑动动画没到预定位置就在动画路径中被检测到
    'ocr': { #可选, 使用的OCR库
        'lib': 'onnxocr',
        'auto_simplify': False, #自动繁体转简体, 需要ppocrv5等可以识别繁体的库
        'params': {
            'use_openvino': True,
        }
    },
    'windows': {  # Windows游戏请填写此设置
        'exe': ['nikke.exe'],
        # optional, if set, will search the exe only
        # 'hwnd_class': 'UnrealWindow', #增加重名检查准确度
        'interaction': ['Pynput', 'PyDirect'], # Genshin:某些操作可以后台, 部分游戏支持 PostMessage:可后台点击, 极少游戏支持 ForegroundPostMessage:前台使用PostMessage Pynput/PyDirect:仅支持前台使用
        'capture_method': ['WGC', 'BitBlt_RenderFull', 'BitBlt'],  # Windows版本支持的话, 优先使用WGC, 否则使用BitBlt_Full. 支持的capture有 BitBlt, WGC, BitBlt_RenderFull, DXGI
        'check_hdr': False, #当用户开启AutoHDR时候提示用户, 但不禁止使用
        'force_no_hdr': False, #True=当用户开启AutoHDR时候禁止使用
        'require_bg': True # 要求使用后台截图
    },
    # 'adb': {  # 模拟器或Android设备请填写此设置, mumu模拟器使用原生截图和input,速度极快. 其他模拟器和真机使用adb,截图速度较慢
    #     # optional, if set, will start the pacakge and ensure installed
    #     #'packages': ['com.abc.efg1', 'com.abc.efg1']
    # },
    # 'browser': {  # 浏览器游戏请填写此设置；windows、adb、browser 至少配置一个，也可以同时配置多个
    #     'url': 'https://example.com/game',
    #     'nick': 'Browser',
    #     'resolution': (1280, 720),
    # },
    'start_timeout': 120,  # default 60
    'gui': {
        'type': 'qt',
        'window_size': { #ok-script窗口大小
            'width': 1200,
            'height': 800,
            'min_width': 600,
            'min_height': 450,
        },
    },
    'supported_resolution': {
        'ratio': '16:9', #支持的游戏分辨率
        'min_size': (1600, 900), #支持的最低游戏分辨率
        'resize_to': [(2560, 1440), (1920, 1080), (1600, 900)], #可选, 如果非16:9自动缩放为 resize_to
    },
    'links': { # 关于里显示的链接, 可选
            'default': {
                'github': 'https://github.com/c6n1aa/ok-nikke',
                'share': 'Download from https://github.com/c6n1aa/ok-nikke',
                'faq': 'https://github.com/c6n1aa/ok-nikke'
            }
        },
    'screenshots_folder': "screenshots", #截图存放目录, 每次重新启动会清空目录
    'gui_title': 'ok-nikke',  #窗口名
    'template_matching': { # 可选, 如使用OpenCV的模板匹配
        'coco_feature_json': os.path.join('assets', 'coco_annotations.json'), #coco格式标记, 需要png图片, 在debug模式运行后, 会对进行切图仅保留被标记部分以减少图片大小
        'default_horizontal_variance': 0.002, #默认x偏移, 查找不传box的时候, 会根据coco坐标, match偏移box内的
        'default_vertical_variance': 0.002, #默认y偏移
        'default_threshold': 0.8, #默认threshold
    },
    'version': version, #版本
    'my_app': ['src.globals', 'Globals'], #可选. 全局单例对象, 可以存放加载的模型, 使用og.my_app调用
    'onetime_tasks': [  # 用户点击触发的任务
        ["src.tasks.DailyTask", "DailyTask"],
        ["src.tasks.HarvestTask", "HarvestTask"],
        ["src.tasks.OutpostDefenseTask", "OutpostDefenseTask"],
        ["src.tasks.CashShopTask", "CashShopTask"],
        ["src.tasks.ShopTask", "ShopTask"],
        ["src.tasks.RecruitTask", "RecruitTask"],
        ["src.tasks.OutpostTask", "OutpostTask"],
        ["src.tasks.ArkTask", "ArkTask"],
        ["src.tasks.RaidTask", "RaidTask"]
    ],
    'trigger_tasks': [  # 后台任务，可随时开启/关闭
    ],
    'custom_tabs': [  # 自定义Tab
        ["src.ui.DailyTab", "DailyTab"],
    ],
}
