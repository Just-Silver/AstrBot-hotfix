# 引用合并转发内容展开

<!-- 职责：本热补丁的根因、部署与验证方式；不写：其他热补丁、AstrBot 其他模块。 -->

## 解决什么问题

群里有人「引用一条合并转发 + @机器人」时，机器人只能看到 `[转发消息]` 占位符，
回答"我看不了内容"。

根因在 `astrbot/core/utils/quoted_message/chain_parser.py`：
`get_msg` 返回的 forward 段其实**已经带着完整节点内容**，但代码只要看到 `id`
就只记 id、丢掉 `content`，随后拿 id 去调 `get_forward_msg`。
而 NapCat 的 `get_forward_msg` 只认 5000 条 LRU 缓存内的 msgId，
内层 id 一律报 `retcode=1200 消息已过期或者为内层消息`。

本补丁改成：**forward 段有 content 就直接用，没有才退回原来的 id 逻辑**。

## 文件

| 文件 | 说明 |
|---|---|
| `chain_parser.py` | 基于 AstrBot **v4.29.4** 官方源码改动，仅 forward 链路有差异 |
| `check-upstream.ps1` | 检查上游是否已修复该问题 |

## 解析输出格式

用 XML 风格的标签表达嵌套层级，边界不靠缩进猜测：

```
<合并转发 发起者="张三(10001)">
张三(10001): 你们看这个
张三(10001): <转发>
  李四(10002): 第一层
  李四(10002): [引用 李四(10002): 第一层] 对
  王五(10003): 再套一层 <转发>
    赵六(10004): 最里层
    </转发>
  </转发>
张三(10001): 转发之后的消息
</合并转发>
```

- 顶层整体用 `<合并转发 发起者="昵称(QQ号)">…</合并转发>` 包住
- 内层转发用 `<转发>…</转发>` 开闭标签 + 每层 `  ` 缩进，结束位置无歧义
- 层级超过 `max_forward_node_depth`（默认 6）时输出 `<转发 内容已省略="层级过深"/>`，不再静默丢内容
- 每条 `昵称(QQ号): 内容`；同层只有一个发送者时省略 QQ 号
- 转发节点若被 NapCat 写成统一占位 QQ 号（如 `1094950020`），自动退化为只显示昵称
- 引用回复还原成 `[引用 昵称(QQ号): 被引用内容]`
- 语音 `[语音]`、表情 `[表情]`、@ `@昵称(QQ号)`、空消息 `[非文本消息]`，不再整条消失
- 图片保留 `[Image]` 占位，同时作为图片送入模型（主模型需支持视觉）
- 走 `get_forward_msg` 兜底入口时拿不到发起者，因此没有外层 `<合并转发>` 包装，节点直接平铺

## 部署（可视化面板 / Compose）

### 1. 放到部署目录

整个 `AstrBot-hotfix` 文件夹放到 `docker-compose.yaml` 同级：

```
共享文件夹/Docker/AstrBot/
├── AstrBot/
├── NapCatQQ/
├── AstrBot-hotfix/
│   └── forward-content/
│       └── chain_parser.py
└── docker-compose.yaml
```

### 2. compose 加挂载

```yaml
    volumes:
      - ./AstrBot/data:/AstrBot/data          # 原有，保持不动
      - ./AstrBot-hotfix/forward-content/chain_parser.py:/AstrBot/astrbot/core/utils/quoted_message/chain_parser.py:ro
```

面板表单式挂载：

- 主机路径：`共享文件夹/Docker/AstrBot/AstrBot-hotfix/forward-content/chain_parser.py`
- 容器路径：`/AstrBot/astrbot/core/utils/quoted_message/chain_parser.py`
- 只读：开

### 3. 重建

```bash
docker compose up -d --force-recreate astrbot
```

## 验证

```bash
# 文件是否覆盖（应输出 patched）
docker exec astrbot sh -c "grep -q 'LRU 缓存' /AstrBot/astrbot/core/utils/quoted_message/chain_parser.py && echo patched || echo not-patched"

# 模块能否导入
docker exec astrbot python -c "import astrbot.core.utils.quoted_message.chain_parser as m; print('ok')"
```

## 查看解析结果

每次展开打一条 **DEBUG** 日志（不污染正常日志），输出完整展开内容：

```bash
# 先把 AstrBot 的 log_level 改成 DEBUG，重启后执行
docker logs astrbot 2>&1 | grep -A 200 转发展开
```

日志是多行格式，`grep -A` 可以一次看到整段。

## 回滚

删掉 compose 里那行挂载，再 `docker compose up -d astrbot`，立刻恢复镜像原文件。

## 升级注意

本补丁基于 **v4.29.4**。官方升级后如果改动了这个文件，你的旧文件会覆盖新逻辑。

升级后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\check-upstream.ps1
```

- 输出 `[未修复]` → 补丁继续有效
- 输出 `[已修复]` → 可以移除挂载

同时确认没挂成目录：

```bash
docker exec astrbot ls -l /AstrBot/astrbot/core/utils/quoted_message/chain_parser.py | grep -q "^-" && echo file-ok
```

## 已知局限

- 只修**引用**合并转发的场景；直接发一条合并转发仍然看不到内容
- 跨层级引用（引用了另一层转发里的消息）只能显示 `[引用消息]`，无法还原内容
- 图片能否被模型看到，取决于主模型是否支持视觉、图片 URL 是否可解析
- 文本没有字符上限，超长转发会占用较多上下文
