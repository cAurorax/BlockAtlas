# 启动游戏（游戏本体安装 + 启动配置）

> 对应侧栏「启动游戏」页签。版本固定在 **Minecraft Java 1.20.1 + Fabric 0.19.4**，
> 与 `resources.py` 中资源库的版本钉死保持一致；本页只调整「怎么启动」，不修改游戏内容。

## 1. 它解决什么问题

社区里的整合包最终要落到本机能玩的游戏上。之前的流程停在「导出 .mrpack」——
文件生成了，但玩家还得自己找启动器、自己配 Java、自己决定给多少内存。本模块把这段补上：

- **装**：没有游戏本体的机器，点一次按钮就能装好 Minecraft + Fabric + Mojang Java 运行时。
- **配**：内存、窗口尺寸、用哪个 Java，按账号保存，下次进来直接启动。
- **跑**：直接拉起游戏进程，可查看日志、可停止。

PR 审阅者可以在任何一台干净机器上完整验证「安装 → 启动」全流程，不需要预置游戏文件。

## 2. 目录布局

全部文件放在一个启动器式的共享目录下，可用 `ATLAS_MVP_ROOT` 覆盖：

```text
<root>/                              # 默认 %LOCALAPPDATA%\BlockAtlas\mvp
└── .minecraft/
    ├── versions/
    │   ├── 1.20.1/                        # 原版
    │   └── fabric-loader-0.19.4-1.20.1/   # Fabric 档案（启动版本）
    ├── libraries/  assets/  runtime/       # 共享库、资源与 Mojang Java
    └── logs/blockatlas-launch-*.log        # 每次启动的命令与游戏输出
```

`root_dir()` 读 `ATLAS_MVP_ROOT`，缺省为 `%LOCALAPPDATA%\BlockAtlas\mvp`；
`minecraft_dir()` 即其下的 `.minecraft`。

## 3. 安装游戏本体

`install_runtime()` 走 `minecraft-launcher-lib`：

1. `install.install_minecraft_version("1.20.1", <minecraft_dir>)` —— 下载 client jar、
   assets、libraries，并安装 Mojang 自带的 Java 运行时（`runtime/java-runtime-gamma`）。
2. `mod_loader.get_mod_loader("fabric").install("1.20.1", ..., loader_version="0.19.4")`
   —— 安装 Fabric 档案，使用上一步下载的 Mojang Java，因此**没有系统 Java 的机器也能装**。

安装跑在后台线程里，进度通过 `GET /api/launch/install` 轮询：

| 字段 | 含义 |
| --- | --- |
| `status` | `idle` / `running` / `success` / `failed` |
| `stage` | 当前阶段（`Minecraft` / `Fabric` / `完成` / `失败`） |
| `detail` | 下载器当前的细粒度动作（如 `Download 1.20.1.jar`） |
| `current` / `total` | 阶段计数（2 个阶段） |
| `error` | 失败原因 |

> **进度条为什么不是百分比**：下载器对每个文件单独上报 `progress/max`，数字会反复归零，
> 直接当总进度会来回跳。界面因此采用**不确定态扫描条** + 阶段文字 + 当前文件名，
> 既能看出在动，又不谎报精度。条形动画是纯 CSS `transform`，不参与 JS 重绘。

## 4. 启动配置

| 项 | 说明 |
| --- | --- |
| **内存** | `auto` 按 `2048 + Mod 数 × 60 MB` 估算，上限为物理内存 60%；`manual` 由玩家指定，上下限 1024 MB ～ 物理内存 70%（`memory_ceiling()`），保证 JVM 真的能分配出来 |
| **窗口尺寸** | `--width` / `--height`，范围 640–7680，附 4 个常用预设 |
| **Java** | 扫描本机运行时（Mojang 运行时、`PATH`、`JAVA_HOME`、Oracle / Adoptium / Microsoft / Corretto / Zulu / BellSoft 等常见目录），逐个执行 `-XshowSettings:properties -version` 读取版本、发行方、架构后入库；列表可单选，也可手动填路径 |
| **离线用户名** | 1–16 位字母/数字/下划线，离线 UUID 用 `OfflinePlayer:<name>` 的 MD5 改位生成，与主流启动器一致 |

设置按账号存在 `launch_settings` 表；Java 目录是机器维度的，存在 `java_runtimes` 表。

**Java 版本不做拦截**：Minecraft 后续版本对 Java 的要求各不相同，硬编码「1.20.1 必须 17+」
会在多版本共存时变成负担。页面只展示版本号，由玩家自己选择；选错会在日志里直接看到
`UnsupportedClassVersionError`。

## 5. 启动与停止

`POST /api/launch/start` 用 `minecraft-launcher-lib` 的 `get_minecraft_command()` 组装命令，
`subprocess.Popen` 拉起，日志重定向到 `logs/blockatlas-launch-<时间戳>.log`。

安全与并发约束：

- **仅本机**：`launch_allowed` 只对 `127.0.0.1` / `::1` 放行，`ATLAS_ALLOW_REMOTE_LAUNCH=1` 仅供开发。
- **单实例**：同一时间只允许一个游戏进程；安装期间不允许启动，启动期间不允许安装。
- **停止**：`terminate()` 后等待 10 秒，超时改 `kill()`。

## 6. 日志

`GET /api/launch/logs?offset=<byte>` 返回该字节位置之后的新增内容：

- 首次请求（`offset` 省略）返回末尾 `lines` 行，并给出文件当前大小作为游标。
- 之后按游标增量读取，只发送**完整行**，避免多字节字符或半行被截断。
- 前端用 `appendChild(TextNode)` 追加，不重建节点；只有在滚动条本来就在底部时才自动跟随。
- 超过 2000 行时丢弃最旧的一半。

### 为什么状态面板不整块重绘

早期实现每次轮询都 `innerHTML = ...` 整个状态卡，`<pre>` 被整体替换、文字重排，
日志区肉眼可见地一闪一闪。现在：

1. 状态卡**只渲染一次骨架**，之后用「值变了才写」的方式更新 `textContent`。
2. 安装面板按 `dataset.shape`（`ready|missing` + `run|idle`）判断是否需要换结构，进度变化不重建。
3. 日志走上面的字节游标增量追加。

## 7. HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/launch/settings` | 启动配置 + 推荐内存 + Java 列表 + 安装状态 + 上限值 |
| PUT | `/api/launch/settings` | 保存配置；校验内存上限、窗口范围、用户名、Java 路径存在 |
| GET | `/api/launch/java` | 已入库的 Java 列表 |
| POST | `/api/launch/java/scan` | 扫描本机 Java 并写库 |
| GET | `/api/launch/memory` | 机器信息与内存推荐（含计算依据） |
| GET | `/api/launch/install` | 安装任务快照 + 安装状态 |
| POST | `/api/launch/install` | 202 启动后台安装（仅本机、单任务） |
| GET | `/api/launch/status` | 进程状态 + 安装状态快照 |
| POST | `/api/launch/start` | 202 启动游戏（仅本机、单实例） |
| POST | `/api/launch/stop` | 停止当前游戏 |
| GET | `/api/launch/logs?offset=` | 启动器日志（字节游标增量） |

## 8. 数据表

```sql
CREATE TABLE IF NOT EXISTS java_runtimes (
  path TEXT PRIMARY KEY, version TEXT, vendor TEXT, arch TEXT,
  major INTEGER, source TEXT, seen_at TEXT
);
CREATE TABLE IF NOT EXISTS launch_settings (
  uid INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  memory_mode TEXT, memory_mb INTEGER, width INTEGER, height INTEGER,
  java_path TEXT, username TEXT, updated_at TEXT
);
```

## 9. 验证

```bash
python -m atlas.tools.verify_launch
```

覆盖：Java 扫描与入库、Java 版本号归一化（`1.8.0_401 → 8`）、内存推荐与上限、
按账号隔离的配置读写、输入校验、固定版本命令组装、安装任务成功/失败路径、
单实例锁、停止、日志字节游标（增量 / 半行 / 空增量）、仅回环地址可启动。

`verify_launch` 全程使用 mock，不联网、不下载、不启动真实游戏。
真实「安装 → 启动」的人工验证步骤见第 10 节。

## 10. 人工验证（干净机器）

```bash
# 1. 用一个空目录，避免使用已有游戏
set ATLAS_MVP_ROOT=%TEMP%\atlas-launch-check

# 2. 启动服务
python -m uvicorn atlas.server:app --host 127.0.0.1 --port 18183

# 3. 浏览器打开 http://127.0.0.1:18183/ ，登录后进入「启动游戏」
#    4. 点「安装游戏本体」，等待阶段走到「完成」（约 500 MB）
#    5. 选 Java、设内存与窗口，点底部的「启动游戏」
```

预期：安装完成后徽标变为「可启动」；启动后状态卡显示 PID，日志逐行追加且不闪烁；
关闭游戏或点「停止游戏」后按钮回到「启动游戏」。

## 11. 已知边界

- 版本写死为 1.20.1 + Fabric 0.19.4；多版本管理未实现（本 PR 刻意不引入版本选择，避免与资源库的版本钉死冲突）。
- 启动器只负责启动；`.minecraft/mods` 里的 Mod 由玩家或后续模块放置，本模块不下载 Mod。
- `terminate()` 不杀进程树，用第三方启动脚本包一层时可能残留子进程。
- 窗口标题不可配置：Minecraft 1.20.1 的客户端参数里没有 `--title`，标题由游戏内部 GLFW 设置，
  改写需要注入系统 API 或 mod，收益不抵复杂度，故不实现。
