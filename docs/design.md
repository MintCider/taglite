# TagLite 设计文档

## 1. 项目背景

现有文件管理痛点：文件有时需要按时间归纳，有时按用途归纳，有时需要贴标签——物理目录结构只能选一种组织方式。需要一个在磁盘物理结构之外的虚拟标签层，对文件进行多维度管理。

市场调研结论：
- **Tabbles**：功能最匹配，但依赖 MSSQL，付费 €3-5/月
- **TagSpaces**：开源但改文件名或产生 sidecar 文件，OneDrive 不友好
- **Files App**：标签用 NTFS ADS 存储，OneDrive 同步会丢标签，组合筛选弱
- **TMSU**：开源 + SQLite，但 Windows 支持差且已停更
- **Spacedrive**：尚在 alpha，Windows 版未发布

结论：没有现成方案完美满足需求，自行开发。

## 2. 核心需求

### 2.1 Library 与 Backend 机制

#### Backend 概念
- **Backend** 是独立概念：一个数据库实例（SQLite 文件或 MySQL/PG 连接）
- 默认：一个本地 SQLite（存在系统应用数据目录），所有 Library 共用
- 用户可添加更多 Backend（额外 SQLite 或云 MySQL/PG）
- 新建 Library 时选择 Backend
- 跨 Backend 搜索暂不做

#### config.json 结构（只存 backends，不存 libraries）
```json
{
  "default_backend_id": 1,
  "backends": [
    {"id": 1, "name": "本地默认", "uri": "sqlite:///...TagLite/default.db"}
  ]
}
```
Library 信息（name, root_path）全部存在 DB 的 libraries 表里，不在 config 中冗余。

#### Library
- 用户指定一个目录作为 Library，仅索引该目录内部文件
- 支持多个 Library，同一 Backend 内 Library name 唯一
- Library 指向一个 Backend，同一 Backend 内多个 Library 用 `library_id` 区分
- UTF-8 名称，允许中文，允许重命名（name 只是显示标签，关联靠 id）
- 跨设备同步策略：文件同步依赖 OneDrive 等云服务，不同设备上将同一个 Library 指向实质相同的目录即可

### 2.2 标签系统
- 标签 CRUD（创建、读取、更新、删除）
- 支持 `key=value` 形式标签（如 `project=Alpha`、`status=done`）
- 支持普通标签（如 `重要`、`财务`）：key="" (空字符串), value="标签名"
- 用空字符串而非 NULL，确保 UNIQUE(library_id, key, value) 在所有 DB 后端正确工作
- 一个文件可以有多个标签
- 一个标签可以关联多个文件

### 2.3 搜索引擎

搜索栏支持完整的搜索语法，空格分隔默认 AND，支持 OR / NOT / 括号组合。

| 语法 | 含义 | 示例 |
|------|------|------|
| 纯文本 | 文件名模糊匹配 | `报告` |
| `tag:value` | 简单标签匹配 | `tag:重要` |
| `tag:key=value` | KV 标签精确匹配 | `tag:project=Alpha` |
| `tag:key` | 匹配该 key 的所有值 | `tag:status` |
| `ext:xxx` | 扩展名过滤 | `ext:pdf` |
| `ext:folder` / `-ext:folder` | 只显示/排除文件夹 | |
| `size>N` / `size<N` | 大小过滤（支持 KB/MB/GB） | `size>1MB` |
| `after:date` / `before:date` | 修改时间过滤 | `after:2024-01-01` |
| `AND` / `OR` / `NOT` / `-` / `()` | 逻辑运算 | `(tag:A OR tag:B) AND ext:pdf` |

搜索结果以平铺列表展示，每条文件下方显示完整相对路径（浅色小字，横贯所有列宽）。搜索结果缓存最近 3 次查询（LRU），数据变更时自动清空。

解析失败处理：纯文本回退为文件名搜索；含前缀时严格解析，语法错误在状态栏提示。

### 2.4 文件浏览 GUI
- 三栏布局：
  - 左栏上：目录树（Library 内的文件夹结构）
  - 左栏下：标签浏览器（点击标签联动搜索）
  - 中栏：文件列表（名称/修改时间/大小/类型/标签芯片列，列头可拖拽调整）
  - 右栏：元数据面板（选中文件的详细信息 + 标签编辑）
- 工具栏搜索框 + 高级搜索展开面板（标签选择/扩展名/大小/日期筛选）
- 双击文件：调用系统默认程序打开
- 空格键：GUI 内快速预览
- 右键菜单：快速打标签

### 2.5 Windows 资源管理器集成
- 注册表方案：右键文件 → "用 TagLite 打标签" → 弹出标签选择对话框
- 位于二级菜单（"显示更多选项"下），Win11 一级菜单集成暂不做

### 2.6 数据存储
- 默认：SQLite 单文件，存放在系统应用数据目录（macOS: ~/Library/Application Support/TagLite/, Windows: %APPDATA%\TagLite/），不放在 Library 文件夹内
- 可选：通过连接字符串切换到 MySQL / PostgreSQL / MSSQL（用于 NAS 或云服务器场景）
- 使用 ORM 抽象层，切换后端只需改配置

## 3. 技术方案

### 3.1 技术栈
| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.10+ | 开发效率高，生态丰富 |
| GUI 框架 | PySide6 (Qt6) | 内置 QFileSystemModel/QTreeView，文件浏览器组件成熟；MIT 协议 |
| ORM | SQLAlchemy 2.0 | 支持 SQLite/MySQL/PostgreSQL/MSSQL，切换后端改连接字符串 |
| 主题 | qt-material 或 QSS 自定义 | 现代化外观 |
| 打包 | PyInstaller (`--onedir`) + Inno Setup | 标准 Windows 桌面应用分发方式 |

### 3.2 数据模型

所有表在同一个 Backend DB 内：

```
libraries
├── id (PK, autoincrement)
├── name (TEXT NOT NULL UNIQUE)     -- Library 名称，UTF-8
├── root_path (TEXT NOT NULL)       -- 本机上的实际路径
└── is_active (BOOLEAN default True) -- 是否在目录树中显示

tags
├── id (PK, autoincrement)
├── library_id (FK → libraries.id)
├── key (TEXT NOT NULL default="")  -- 普通标签为空字符串，KV标签为键名
├── value (TEXT NOT NULL)           -- 普通标签为标签名，KV标签为值
├── color (TEXT nullable)           -- 可选，显示颜色
└── UNIQUE(library_id, key, value)

files
├── id (PK, autoincrement)
├── library_id (FK → libraries.id)
├── relative_path (TEXT NOT NULL)   -- 相对 Library 根目录的路径
├── filename (TEXT NOT NULL)        -- 文件名/目录名
├── file_size (INTEGER nullable)    -- 字节数（目录为 NULL）
├── file_extension (TEXT nullable)  -- 小写扩展名含点（目录为 NULL）
├── file_mtime (DATETIME nullable)  -- 文件修改时间（UTC）
├── file_ctime (DATETIME nullable)  -- 文件创建时间（UTC）
├── content_hash (TEXT nullable)    -- 预留，Phase 1 不填
├── is_directory (BOOLEAN default False) -- 是否为目录
├── last_seen (DATETIME)            -- 最后扫描确认时间
├── is_missing (BOOLEAN default False) -- 文件/目录是否已消失
└── UNIQUE(library_id, relative_path)

file_tags
├── file_id (FK → files.id)        -- 复合主键
├── tag_id (FK → tags.id)          -- 复合主键
└── tagged_at (DATETIME)           -- 打标签时间
```

关键设计：
- `files` 表存储相对路径而非绝对路径，这样不同设备上 Library 根目录不同也不影响标签映射。显示时拼接 `library.root_path + file.relative_path` 得到绝对路径。
- 文件和目录统一存在 `files` 表中，通过 `is_directory` 区分。目录也可以打标签。
- 递归标签：给目录打标签后，搜索时通过 `relative_path LIKE 'dir/%'` 将子文件纳入结果（查询时展开，不写冗余数据）。

### 3.2.1 文件变更策略
- Phase 1：启动时全量扫描，新文件插入，消失文件标记 is_missing
- content_hash 字段预留但不填充
- watchdog 实时监听和哈希匹配留到 Phase 5

### 3.3 项目结构

```
taglite/
├── main.py                  -- 入口
├── docs/
│   └── design.md            -- 本设计文档
├── taglite/
│   ├── __init__.py
│   ├── config.py            -- Backend 注册表、应用数据目录
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py        -- SQLAlchemy 2.0 ORM 数据模型
│   │   └── engine.py        -- 数据库引擎/会话管理（按 URI 缓存）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── library.py       -- Library 创建、目录扫描、文件索引、active 切换、路径变更
│   │   ├── tagger.py        -- 标签 CRUD 业务逻辑
│   │   └── search.py        -- 搜索引擎：AST 解析器 + 多条件执行
│   ├── ui/
│   │   ├── app.py           -- QApplication 初始化、QSS 加载
│   │   ├── main_window.py   -- 主窗口（三栏布局 + 搜索流程 + 高级面板）
│   │   ├── dir_tree.py      -- 左栏：目录树（自定义 drawBranches）
│   │   ├── file_list.py     -- 中栏：文件列表（FileTableView 搜索结果路径叠层）
│   │   ├── metadata_panel.py-- 右栏：元数据 + 标签编辑
│   │   ├── tag_chip.py      -- TagChipFrame（QPainter 绘制）+ AddTagButton
│   │   ├── tag_dialog.py    -- 快速打标签对话框（含自动配色）
│   │   ├── tag_browser.py   -- 标签浏览面板（点击联动搜索）
│   │   ├── search_panel.py  -- 高级搜索面板（标签/扩展名/大小/日期筛选）
│   │   ├── color_picker.py  -- 标签颜色选择器（彩虹渐变环）
│   │   ├── flow_layout.py   -- FlowLayout（标签芯片自动换行布局）
│   │   ├── scan_worker.py   -- 后台扫描线程
│   │   └── library_manager.py -- Library 管理界面（增量跟踪、active 切换、路径变更）
│   └── integration/
│       ├── shell_menu.py    -- Windows 右键菜单注册/注销
│       └── file_opener.py   -- 双击打开 / 空格预览
├── verify.py                -- 端到端验证脚本
└── resources/
    └── theme.qss            -- Qt 样式表
```

### 3.4 关键交互流程

**首次启动：**
1. 弹出 Library 管理器 → 选择目录创建 Library
2. 扫描目录建立文件和目录索引（仅记录路径，不读取文件内容，跳过隐藏文件/目录）
3. 进入主界面

**打标签（GUI 内）：**
1. 在文件列表中选中文件 → 右键 → "添加标签"
2. 弹出标签选择/创建对话框
3. 选择已有标签或新建标签（支持 key=value 输入）
4. 保存到数据库，文件列表标签列实时更新

**打标签（资源管理器）：**
1. 在资源管理器中右键文件 → "用 TagLite 打标签"
2. 执行 `taglite.exe --tag "C:\path\to\file.docx"`
3. 弹出轻量标签对话框（自动识别文件属于哪个 Library）
4. 选择标签，保存，窗口关闭

**组合搜索：**
1. 搜索栏输入/选择标签条件（如 `project=Alpha AND 重要 NOT archived`）
2. 执行 SQL 查询
3. 结果在文件列表中展示，显示绝对路径

## 4. 开发计划

### Phase 1：核心骨架
- [x] 项目初始化、依赖管理
- [x] SQLAlchemy 数据模型 + 数据库引擎
- [x] Library 创建 / 目录扫描 / 文件索引（含目录索引）
- [x] 标签 CRUD + key=value 支持
- [x] 文件和目录打标签

### Phase 2：GUI 主体
- [x] PySide6 主窗口三栏布局
- [x] 左栏目录树（自定义 branch 绘制，叶节点无箭头无交互）
- [x] 中栏文件列表（含标签芯片列显示、复合排序、可拖拽列宽）
- [x] 右栏元数据面板 + 标签编辑（芯片 hover 删除、右键重命名/换色）
- [x] 双击打开文件
- [x] 右键菜单打标签

### Phase 2.5：GUI 修复与增强
- [x] Library.is_active 字段 — 目录树中隐藏/显示 Library
- [x] Library 管理器增量跟踪（添加/移除/active 切换/路径变更）
- [x] TagChipFrame 全 QPainter 绘制（避免 QSS border-radius 锯齿）
- [x] 标签 hover overlay + 红色叉号删除（QPainter drawLine）
- [x] 标签自动配色 + 颜色选择器彩虹渐变环
- [x] FlowLayout 标签自动换行
- [x] FileSortProxy 修复 PySide6 QVariant 元组比较问题
- [x] 首次启动延迟弹出 Library 管理器（QTimer.singleShot）
- [x] 目录树 drawBranches 自定义绘制，叶节点 branch 区域完全透明无交互

### Phase 3：搜索、筛选与时间字段
- [x] File 表增加 file_mtime / file_ctime，扫描时采集时间戳
- [x] 文件列表增加"修改时间"列（5 列：名称/修改时间/大小/类型/标签）
- [x] 搜索引擎（search.py）：递归下降 AST 解析器，支持 AND/OR/NOT/括号
- [x] 搜索语法：tag: / ext: / size> / size< / after: / before: / 纯文件名
- [x] 搜索结果模式：FileTableView 视口叠层绘制全宽路径、LRU 缓存 3 条
- [x] 标签浏览器点击联动搜索栏（tag_selected / tag_deselected）
- [x] 高级搜索面板（标签芯片选择、扩展名、大小范围、日期范围）
- [x] 列头竖线分隔 + splitter handle 可见

### Phase 4：集成与打包
- [ ] Windows 资源管理器右键菜单注册
- [ ] 空格键预览
- [ ] qt-material 主题美化
- [ ] PyInstaller 打包 + Inno Setup 安装包

### Phase 5：增强（可选）
- [ ] 文件变更监控（watchdog）自动更新索引
- [ ] 标签导入/导出
- [ ] 多数据库后端配置 UI
- [ ] Library 间标签同步

## 5. Multi-Computer 设计方案（未来 Phase）

### 5.1 背景

当用户在多台电脑上使用 TagLite（通过 OneDrive 同步数据库），同一个 Library 在不同设备上的根目录路径可能不同（如 `D:\Projects` vs `C:\Users\bob\Projects`）。需要一种机制让每台设备自动解析到正确的本地路径。

### 5.2 machine_id

`config.json` 增加 `machine_id` 字段，首次运行时自动生成 UUID：

```json
{
  "machine_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "default_backend_id": 1,
  "backends": [...]
}
```

### 5.3 library_mounts 表

新增数据库表，存储每台设备对每个 Library 的挂载路径：

```
library_mounts
├── library_id (FK → libraries.id)   -- 复合主键
├── machine_id (TEXT NOT NULL)        -- 复合主键
├── root_path (TEXT NOT NULL)         -- 该设备上的实际路径
└── PK(library_id, machine_id)
```

### 5.4 路径解析逻辑

```python
def resolve_library_path(db_uri: str, library_id: int, machine_id: str) -> str:
    """解析当前设备上 Library 的实际路径。

    优先级：
    1. library_mounts 中匹配 (library_id, machine_id) 的记录
    2. 回退到 Library.root_path（创建时的默认值）
    """
```

### 5.5 工作流程

1. 用户在设备 A 创建 Library，root_path 记录为设备 A 的路径
2. 自动在 library_mounts 中插入 `(library_id, machine_id_A, root_path_A)`
3. 设备 B 首次打开同一数据库，发现 Library 在 library_mounts 中无当前 machine_id 记录
4. 弹窗提示用户选择本地路径，写入 `(library_id, machine_id_B, root_path_B)`
5. 后续启动自动通过 machine_id 解析到正确路径

### 5.6 多数据库快速浏览 UI（Phase 3.3）

工具栏添加 Backend 切换下拉框，可快速在不同数据库之间切换查看。目前跨 Backend 搜索不做。
