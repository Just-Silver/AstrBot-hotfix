# AstrBot 热补丁

<!-- 职责：热补丁索引与通用约束；不写：单个补丁的实现细节（见各自目录）。 -->

对官方 AstrBot 镜像做**单文件挂载式**修复，不改镜像、不动业务数据。

## 补丁清单

| 目录 | 修复内容 | 基于版本 |
|---|---|---|
| [`forward-content`](forward-content/README.md) | 引用合并转发时读不到转发正文 | v4.29.3 |

## 通用约束

- 每个补丁一个目录，目录内自带 `README.md` 说明部署与回滚
- 挂载只覆盖单个文件，其余代码仍走官方镜像
- 升级 AstrBot 后必须核对补丁是否仍适用（各补丁目录内附检查脚本）
- 官方修复后应及时移除对应挂载，避免旧文件覆盖新逻辑

## 目录约定

```
AstrBot-hotfix/
├── README.md                 ← 本索引
├── forward-content/          ← 补丁一
│   ├── chain_parser.py
│   ├── check-upstream.ps1
│   └── README.md
└── <下一个补丁>/
```

新增补丁时：建目录 → 放补丁文件与 README → 在本表登记一行。

## 许可证

本仓库是 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的衍生作品，补丁文件基于其源码修改，
因此与上游一致，采用 **GNU Affero General Public License v3.0 or later**（AGPL-3.0-or-later），
全文见 [`LICENSE`](LICENSE)。
