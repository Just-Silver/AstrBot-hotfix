# AstrBot 热补丁

<!-- 职责：热补丁索引与通用约束；不写：单个补丁的实现细节（见各自目录）。 -->

以**单文件挂载**或**插件远程加载**两种方式修复官方 AstrBot 镜像里的缺陷，不改镜像、不动业务数据。

## 补丁清单

| 目录 | 修复内容 | 基于版本 |
|---|---|---|
| [`patches/forward-content`](patches/forward-content/README.md) | 引用合并转发时读不到转发正文 | v4.29.4 |

## 通用约束

- 每个补丁一个目录，目录内自带 `README.md` 说明部署与回滚
- 挂载只覆盖单个文件，其余代码仍走官方镜像
- 升级 AstrBot 后必须核对补丁是否仍适用（各补丁目录内附检查脚本）
- 官方修复后应及时移除对应挂载，避免旧文件覆盖新逻辑

## 通过插件远程加载

本仓库同时是 `astrbot_plugin_agent_toolkit` 的远程热补丁来源，可以不挂载文件、重启容器，直接在插件的「工具台 → 模块 → 热补丁」里开启。

- 根 `hotfix.json` 声明清单格式
- 每个补丁目录内的 `patch.json` 声明文件、适用 AstrBot 版本、版本号与注入点
- 插件只扫描 `patches/` 下一层目录，补丁默认关闭，需要用户手动开启
- 补丁有新版本时不会自动替换，由用户在界面里逐个确认更新

清单字段的完整定义见插件仓库的 [`astrbot-hotfix-repository.md`](https://github.com/Just-Silver/astrbot_plugin_agent_toolkit/blob/main/docs/research/astrbot-hotfix-repository.md)。

## 目录约定

```
AstrBot-hotfix/
├── README.md
├── hotfix.json               ← 插件远程加载的根清单
└── patches/
    └── forward-content/      ← 补丁一
        ├── patch.json        ← 补丁清单
        ├── chain_parser.py
        ├── check-upstream.ps1
        └── README.md
```

新增补丁的完整流程（目录、`patch.json` 模板、版本规则、自检清单）见 [`AGENTS.md`](AGENTS.md#新增补丁流程)，不要凭印象直接建目录。

## 许可证

本仓库是 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的衍生作品，补丁文件基于其源码修改，
因此与上游一致，采用 **GNU Affero General Public License v3.0 or later**（AGPL-3.0-or-later），
全文见 [`LICENSE`](LICENSE)。
