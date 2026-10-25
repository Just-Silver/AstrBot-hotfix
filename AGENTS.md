# AstrBot 热补丁仓库

<!-- 职责：仓库定位、上游源码指向、补丁约定与维护流程；不写：单个补丁的实现细节（见各补丁目录 README）。 -->

本仓库**只存放对 AstrBot 的热补丁**，不包含 AstrBot 源码、不包含业务插件。

补丁以「单文件挂载」方式覆盖官方镜像里的同名文件，用于在官方修复前临时解决缺陷。

## 上游源码

| | 位置 |
|---|---|
| 官方仓库（`upstream`） | https://github.com/AstrBotDevs/AstrBot |
| 本地源码 | `E:\Code\Projects\Applications\AstrBot\AstrBot`（git clone，分支 `master`） |
| 本地源码的 `origin` | https://github.com/Just-Silver/AstrBot（个人 fork，不含私改，仅做镜像） |
| 当前补丁基线 | **v4.29.3**（2026-10-24） |

## 开发前同步（强制）

任何改动开始前（新增/修改补丁、排查问题、生成对比文件），**必须先同步一次本地源码**，不允许在落后基线上动手。

```powershell
cd E:\Code\Projects\Applications\AstrBot\AstrBot
git fetch --all --tags --prune
git switch master
git merge --ff-only upstream/master   # 合入官方最新
git push origin master                # 同步回自己的 fork
git log --oneline -1
```

- `origin` 是个人 fork，`upstream` 是官方；同步方向只能是 `upstream` → 本地 → `origin`
- 合并只允许 `--ff-only`。失败说明 `master` 存在本地私改或已分叉：**停下向用户报告**，不 rebase、不 force push、不自行清理
- 同步后版本有变化时，同一次改动内更新：本文「当前补丁基线」、根 `README.md` 补丁清单的「基于版本」，并跑各补丁目录的检查脚本
- 任务开头要报告本次同步到的版本（`git log --oneline -1` 的结果）

拉取指定 tag 的原始文件用于对比（示例）：

```bash
gh api "repos/AstrBotDevs/AstrBot/contents/astrbot/core/utils/quoted_message/chain_parser.py?ref=v4.29.3" --jq '.content'
```

## 补丁与上游文件的对应关系

| 补丁文件 | 覆盖的上游路径（容器内） |
|---|---|
| `forward-content/chain_parser.py` | `/AstrBot/astrbot/core/utils/quoted_message/chain_parser.py` |

对应的上游源码路径（相对仓库根）：

```
astrbot/core/utils/quoted_message/chain_parser.py
```

## 补丁约定

- 每个补丁一个独立目录，目录内必须有自己的 `README.md`（根因、部署、验证、回滚）
- 补丁文件基于**官方 tag 的原始文件整份修改**，不是 diff；因此上游任何改动都会被覆盖
- 保持文件编码与原文件一致：UTF-8 无 BOM、LF 换行
- 改动范围尽量收敛：只动目标逻辑，不顺手改格式或无关代码
- 新增补丁后在根 `README.md` 的清单表登记一行
- 许可证必须与上游保持一致（AGPL-3.0-or-later）：补丁是 AstrBot 源码的衍生文件，不得改成 MIT、Apache 等宽松协议

## 维护流程

1. AstrBot 升级后，先跑该补丁目录下的检查脚本（如有）
2. 确认上游仍未修复 → 保留挂载
3. 上游已修复 → 删除对应挂载行，`docker compose up -d astrbot`
4. 上游改动较大导致补丁不再适用 → 基于新版本重新生成补丁文件

升级后必须确认容器内文件没被挂成目录：

```bash
docker exec astrbot ls -l /AstrBot/astrbot/core/utils/quoted_message/chain_parser.py | grep -q "^-" && echo file-ok
```

## 禁止事项

- 不在本仓库放 AstrBot 源码或插件的副本
- 不通过补丁改业务数据、配置或插件行为
- 不提交 `__pycache__`、`.last-check.json` 等运行产物（已在 `.gitignore` 忽略）
