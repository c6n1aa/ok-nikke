# ok-nikke

[中文](../index.md)

ok-nikke is an automation app for the Windows client of Goddess of Victory: NIKKE, built on [ok-script](https://github.com/ok-oldking/ok-script). It plays in-game flows through Windows graphics capture and input simulation; it never reads memory or modifies game files.

## Features

- **Foreground running**: input is simulated via Pynput / PyDirect, so keep the game window in the foreground and visible; screenshots prefer WGC background capture.
- **Image recognition**: OpenCV template matching (COCO-managed assets) combined with onnxocr (PaddleOCR v5 + OpenVINO) to read text and locate buttons.
- **Resolution adaptive**: supports 16:9 (minimum 1600×900); assets are based on 2560×1440 and scaled to the current resolution automatically.
- **Completion state**: daily/weekly completion tracking to avoid repeating finished tasks.
- **Failure recovery**: automatically dismisses popups and returns to the lobby to retry when a flow stalls.

## Implemented tasks

| Task | Description |
| --- | --- |
| Daily | Orchestration task that runs the subtasks below according to its settings |
| Harvest | Collect friendship points and mailbox rewards |
| Outpost Defense | Farm the outpost defense, optionally spending gems for extra runs |
| Cash Shop | Claim free STEP UP / daily / weekly / monthly packages |
| Shop | Buy items from the ordinary / arena / scrapyard shops |
| Recruit | Event free recruit / friendship-point recruit / ordinary recruit |
| Outpost | Dispatch / advise / brief encounters |
| Ark | Manufacturer towers / simulation room / interception / arena |
| Raid | Limited-time challenges (co-op / solo raid) |

## Start Here

- Just want to use it: follow [Quick start](getting-started.md) to download and run the portable package; see its "Common issues" first when something goes wrong.
- Want to develop: start from [Development setup](development.md) (running from source and tests), then read [App configuration](configuration.md), [Task development](tasks.md), [Screen recognition & failure recovery](screen-and-recovery.md), [Task brief template](task_brief_template.md), [Packaging and release](release.md), and [Documentation site](documentation.md) as needed.

## Further Reading (ok-script upstream docs)

- [Intro to game automation](https://github.com/ok-oldking/ok-script/blob/master/docs/intro_to_automation/README.md)
- [ok-script quick start](https://github.com/ok-oldking/ok-script/blob/master/docs/quick_start/README.md)
- [After quick start](https://github.com/ok-oldking/ok-script/blob/master/docs/after_quick_start/README.md)
- [API documentation](https://github.com/ok-oldking/ok-script/blob/master/docs/api_doc/README.md)
