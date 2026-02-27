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

### 2.3 标签组合搜索（核心功能）
- 支持 AND：同时拥有标签 A 和标签 B 的文件
- 支持 OR：拥有标签 A 或标签 B 的文件
- 支持 NOT：排除拥有某标签的文件
- 搜索结果显示文件列表 + 文件的绝对路径（非相对路径）

### 2.4 文件浏览 GUI
- 三栏布局：
  - 左栏：目录树（Library 内的文件夹结构）
  - 中栏：文件列表（当前目录下的文件，含标签列）
  - 右栏：元数据面板（选中文件的详细信息 + 标签编辑）
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
└── root_path (TEXT NOT NULL)       -- 本机上的实际路径

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
│   │   ├── library.py       -- Library 创建、目录扫描、文件索引
│   │   ├── tagger.py        -- 标签 CRUD 业务逻辑
│   │   └── search.py        -- 组合搜索引擎
│   ├── ui/
│   │   ├── main_window.py   -- 主窗口（三栏布局）
│   │   ├── dir_tree.py      -- 左栏：目录树
│   │   ├── file_list.py     -- 中栏：文件列表
│   │   ├── metadata_panel.py-- 右栏：元数据 + 标签编辑
│   │   ├── search_bar.py    -- 搜索栏（标签组合筛选 UI）
│   │   ├── tag_dialog.py    -- 快速打标签对话框
│   │   └── library_manager.py -- Library 管理界面
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
- [ ] PySide6 主窗口三栏布局
- [ ] 左栏目录树
- [ ] 中栏文件列表（含标签列显示）
- [ ] 右栏元数据面板 + 标签编辑
- [ ] 双击打开文件
- [ ] 右键菜单打标签

### Phase 3：搜索与筛选
- [ ] 标签组合查询引擎（AND/OR/NOT）
- [ ] 搜索 UI（搜索栏 + 标签选择器）
- [ ] 搜索结果展示（绝对路径）

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
