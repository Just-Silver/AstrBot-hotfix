# AstrBot 热补丁仓库

<!-- 职责：仓库定位、上游源码指向、补丁约定，以及新增/修改/维护补丁的流程；不写：单个补丁的实现细节（见各补丁目录 README）。 -->

本仓库**只存放对 AstrBot 的热补丁**，不包含 AstrBot 源码、不包含业务插件。

补丁以「单文件挂载」方式覆盖官方镜像里的同名文件，用于在官方修复前临时解决缺陷。

## 上游源码

| | 位置 |
|---|---|
| 官方仓库（`upstream`） | https://github.com/AstrBotDevs/AstrBot |
| 本地源码 | `E:\Code\Projects\Applications\AstrBot\upstream\AstrBot`（git clone，分支 `master`） |
| 本地源码的 `origin` | https://github.com/Just-Silver/AstrBot（个人 fork，不含私改，仅做镜像） |
| 当前补丁基线 | **v4.29.4**（2026-10-31） |

## 开发前同步（强制）

任何改动开始前（新增/修改补丁、排查问题、生成对比文件），**必须先同步一次本地源码**，不允许在落后基线上动手。

```powershell
cd E:\Code\Projects\Applications\AstrBot\upstream\AstrBot
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
gh api "repos/AstrBotDevs/AstrBot/contents/astrbot/core/utils/quoted_message/chain_parser.py?ref=v4.29.4" --jq '.content'
```

## 补丁与上游文件的对应关系

| 补丁文件 | 覆盖的上游路径（容器内） |
|---|---|
| `patches/forward-content/chain_parser.py` | `/AstrBot/astrbot/core/utils/quoted_message/chain_parser.py` |

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

## 新增补丁流程

按顺序执行，缺一项就算没做完。每一步的产物都必须在同一次提交里。

### 0. 同步上游

先按本文「开发前同步（强制）」跑完，并报告同步到的版本。补丁必须基于最新基线生成。

### 1. 定位真正生效的替换点

这一步决定补丁有没有用，不能跳过：

- 找到缺陷所在的函数/类，以及**所有调用方**
- 调用方用 `import mod` + `mod.X(...)` → 替换 `mod.X` 有效
- 调用方用 `from mod import X` → 替换 `mod.X` **无效**，必须替换**调用方模块**里的 `X`
- `targets[].module` 填「已绑定该对象的那一层」，不是对象定义的位置

`forward-content` 就是第二种：定义在 `quoted_message.chain_parser`，但 `extractor.py` 用 `from .chain_parser import OneBotPayloadParser` 绑定了引用，所以 `targets` 指向 `quoted_message.extractor`。同一个类在 `content_safety_check/stage.py` 里也被绑定，因此那里不受本补丁影响——这是有意的收敛，不是遗漏。

定位命令：

```bash
rg -n "from .* import .*<对象名>|<对象名>\(" <本地源码>/astrbot
```

### 2. 建目录

```
patches/<patch-name>/
├── patch.json        # 必填，没有它这个目录会被忽略
├── <file>.py         # 补丁文件
├── check-upstream.ps1  # 可选，用于判断上游是否已修复
└── README.md         # 必填
```

- 目录名与 `patch.json` 的 `name` 保持一致，用小写英文与短横线
- 只在 `patches/` 下放**一层**目录；插件不递归扫描
- 不要在 `patches/` 下放模板、草稿、临时验证目录

### 3. 生成补丁文件

- 从官方 tag 取原始文件**整份复制**再改，不是写 diff：单文件挂载需要完整可导入的模块
- 相对导入基于 `targets[0].module` 的父包（插件用它决定补丁模块的导入名）；跨包引用一律用绝对导入
- 模块顶层不能有副作用：不发网络请求、不写文件、不改全局状态
- 只改目标逻辑，不顺手格式化、不改无关代码
- UTF-8 无 BOM、LF 换行

### 4. 写 `patch.json`

```json
{
  "name": "<patch-name>",
  "version": "1.0.0",
  "changelog": [
    "用户能感知到的变化一",
    "用户能感知到的变化二"
  ],
  "description": "一句话说明修的是什么缺陷",
  "file": "<file>.py",
  "astrbot": ">=4.29,<5",
  "targets": [
    {
      "module": "<已绑定该对象的模块>",
      "attribute": "<该模块里的名字>",
      "source": "<补丁模块里的替代对象名>"
    }
  ]
}
```

字段语义与校验规则见插件仓库的 [`astrbot-hotfix-repository.md`](https://github.com/Just-Silver/astrbot_plugin_agent_toolkit/blob/main/docs/research/astrbot-hotfix-repository.md)。

- `version`：补丁自己的版本，**从 `1.0.0` 起**，与仓库 commit 无关
- `changelog`：写用户能看懂的结果，一条一句；不写「验证流程」「调整代码结构」这类过程描述
- `astrbot`：兼容范围，不是补丁的「基于版本」；基于版本写在补丁目录的 README 里
- `targets` 尽量少；多个 target 的父包不同时，相对导入只对第一个成立，其余必须绝对导入

### 5. 写补丁目录的 `README.md`

必须包含：解决什么问题（根因）、文件清单、部署方式（挂载与插件远程加载）、验证方式、回滚方式、已知局限。参照 `patches/forward-content/README.md`。

### 6. 登记索引

同一次改动里更新根 `README.md` 的补丁清单表，以及本文「补丁与上游文件的对应关系」表。

### 7. 自检

- [ ] `patch.json` 能被解析：`python -c "import json,pathlib; json.loads(pathlib.Path('patches/<name>/patch.json').read_text(encoding='utf-8'))"`
- [ ] `file` 指向的文件存在，且在补丁目录内
- [ ] 目标存在：`docker exec astrbot python -c "import <module> as m; print(m.<attribute>)"`
- [ ] 插件界面「刷新」后能看到该补丁，勾选并「应用更改」显示「已应用」（同时验证了补丁模块能导入）
- [ ] 实际触发一遍缺陷场景，确认行为已修复
- [ ] 根 `README.md` 与「补丁与上游文件的对应关系」表已登记
- [ ] 没有提交 `__pycache__`、`.last-check.json`

### 8. 提交

```bash
git add patches/<patch-name> README.md AGENTS.md
git commit -m "feat(<patch-name>): 简述修复内容"
git push origin main
```

## 修改已有补丁

改的是**已发布给用户**的补丁，规则比新增更严：

- 只要补丁文件或 `patch.json` 的行为有一处变化，**必须递增 `version`** 并追加 `changelog`
- 不递增的后果：用户侧继续运行旧快照，永远收不到这次修改；即使手动更新，同名版本的快照已存在也不会被覆盖
- 只改补丁目录的 `README.md`、`check-upstream.ps1` 不影响运行，不需要递增
- 一个版本只放一组相关修复；不相关的问题另起版本，方便用户判断更新

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
- 不在 `patches/` 下放模板、草稿或没有 `patch.json` 的目录
- 不修改补丁行为却不递增 `version`（用户侧会一直运行旧快照）
