# FishAutoPro Clone（闲鱼自动化交付工作台）

一个**自托管、无许可证校验**的闲鱼（goofish）自动化工作台，按 FishAutoPro 3.2 的功能形态重新实现：
Flask + SQLite + 原生 JS 单页后台，聚焦「账号 → 商品 → 订单 → 自动回复 → 自动发货 → 流程编排」这条主链路。

> 本仓库是独立实现（clean-room reimplementation），只参考了产品的公开功能描述与对客户端行为的分析，
> 不包含原产品的任何代码、资源或授权逻辑。真实闲鱼协议接入需要自行实现并遵守平台规则。

> 当前版本 **1.0.0**（首个自托管正式版），变更与已知限制见 [CHANGELOG.md](CHANGELOG.md)。
> 详细部署与操作手册见 **[使用攻略.md](使用攻略.md)**。

![dashboard](shots/dashboard.png)

## 已实现功能
| 模块 | 状态 | 说明 |
|---|---|---|
| 账号管理 | ✅ | 多账号 CRUD、详情、批量操作、JSON/加密导入导出、WS 诊断、扫码、资料刷新 |
| 用户与权限 | ✅ | 管理员/运营角色、用户 CRUD、启停、重置密码、`owner_id` 数据隔离 |
| 商品发布 | ✅ | 素材库、单个/批量发布、发布日志（Mock 本地成功；真实账号走 mtop 发布接口） |
| 商品下架 | ✅ | 单个/批量下架；真实账号走 mtop batch.offline，Mock/无 item_id 时本地下架 |
| 自动补货 | ✅ | 下架/售罄定时检查、按素材重新上架、补货日志 |
| 定时任务 | ✅ | 订单同步/监控/补货/备份周期任务、启停、手动运行、运行记录 |
| 消息接入桥 | ✅ | 令牌认证、入站消息、自动回复入队、出站轮询与 ACK、幂等 external_id |
| 商品管理 | ✅ | 商品 CRUD、标题搜索、在售/下架筛选、库存/价格、图片、下架 |
| 会话中心 | ✅ | 搜索/未读/全部已读/分页、买家标签筛选、人工回复、**定时暂停自动回复**、AI 开关、话术 |
| 快捷话术 | ✅ | 会话页下拉选择、管理弹窗增删、按用户隔离 |
| 操作日志 | ✅ | 动作/详情搜索、动作前缀、时间范围、XLSX 导出；运营只看自己 |
| 订单管理 | ✅ | 列表/状态计数/筛选/搜索、详情、备注、发货、重试、交付日志、同步、删除、平台发货 |
| 退款记录 | ✅ | 申请/退款中/成功/失败状态、金额与原因，退款成功自动标记订单已退款 |
| 自动回复 | ✅ | 精确 / 关键词 / 正则匹配，文本/图片/AI 兜底，模板变量，优先级 |
| 自动发货 | ✅ | 固定内容、库存卡密、API 取货、流程发货；按订单数量多份交付 |
| 流程编排 | ✅ | trigger / set / extract / api / condition / delay / deliver / notify 节点，分支与运行记录 |
| 商品监控 | ✅ | 关键词/价格区间任务、定时轮询；真实账号走 mtop 搜索，Mock 账号用本地数据 |
| AI 客服 | ✅ | OpenAI 兼容接口（base_url / key / model / 系统提示词），连通性测试，会话历史上下文 |
| 知识库 | ✅ | 多知识库/文档、自动分块、中文二元组 + TF-IDF 检索、AI 回复注入参考 |
| 数据导出 | ✅ | 订单 / 商品 / 会话消息 XLSX 导出（openpyxl，表头样式、冻结首行、筛选） |
| 买家标签 | ✅ | 买家/标签/备注 upsert、搜索、删除；黑名单跳过自动回复 |
| 电影票 | ✅ | 电影票订单 CRUD、出票状态、取票二维码，按用户隔离 |
| 经营报表 | ✅ | 定时统计订单/收入/退款/未读/在售，发送到当前用户的通知渠道 |
| 实时事件 | ✅ | 长轮询（最长 20s）新消息/订单/任务，未读角标与浏览器标题同步 |
| 运营总览 | ✅ | 7/30 天订单/收入/退款、待发货/失败、库存、未读、趋势图与最近订单 |
| 通知渠道 | ✅ | Bark / Telegram / Webhook / SMTP 邮件，账号绑定、测试发送、发送日志、事件触发 |
| 备份恢复 | ✅ | ZIP 全量备份（含 secret.key）、下载/删除、上传后重启恢复 |
| 图片上传 | ✅ | 商品主图、回复图片，PNG/JPEG/GIF/WEBP ≤5MB，本地 media 存储 |
| 系统状态 | ✅ | 版本、运行时长、数据库/WAL 大小、数据量、调度器状态 |
| 日志清理 | ✅ | 手动清理 + 定时任务（保留天数、可选 VACUUM） |
| 账号安全 | ✅ | 自助改密、旧会话失效、登录设备列表与单设备吊销 |
| 登录保护 | ✅ | 5 次/5 分钟限流、失败审计、`Retry-After` |
| PWA | ✅ | manifest、Service Worker、桌面/移动端安装、离线应用壳 |
| 联调模拟器 | ✅ | 模拟买家消息、模拟下单、模拟监控商品，一键载入演示数据 |
| 真实闲鱼协议 | 部分 | 扫码登录、mtop 签名、商品搜索/详情、单笔订单同步；消息/发布/WebSocket 待做 |
| 自动擦亮 / 自动好评 | ✅ | 擦亮按商品 ID（手动/定时）；好评支持手动与发货后自动评价（可配文案） |
| 多用户权限 | ✅ | 管理员/运营角色、用户管理、owner_id 数据隔离 |
| 订单/消息定时同步 | ⏳ | 单笔订单同步已做；订单列表轮询与 WebSocket 收消息未做 |
| 许可证 | — | 自托管版本不需要许可证 |

## 快速开始

```bash
cd fishclone
python -m pip install -r requirements.txt
python run.py
```

Windows 也可以直接双击 `start.bat`（自动创建 `.venv` 并安装依赖）。

Docker：

```bash
docker compose up --build
```

打开 <http://127.0.0.1:8000>：

1. 首次启动进入初始化页，创建管理员账号（可勾选「载入演示数据」）；
2. 演示数据会创建一个模拟账号、3 个商品、2 条回复规则、2 条发货规则、1 个监控任务和 1 个流程；
3. 在「联调模拟器」里发一条买家消息、下一单，即可看到自动回复与自动发货。

演示账号（仅本地）：`admin / admin123`（管理员）、`demo_op / op123456`（运营，数据隔离演示）。请在生产环境立即修改。

环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `FAP_HOST` | `127.0.0.1` | 监听地址（对外请放在反向代理后） |
| `FAP_PORT` | `8000` | 端口 |
| `FAP_DATA_DIR` | `fishclone/data` | SQLite、secret.key 等运行数据目录 |
| `FAP_DB` | `data/app.db` | SQLite 路径 |
| `FAP_SECRET_FILE` | `data/secret.key` | 会话 HMAC 密钥文件 |
| `FAP_DISABLE_SCHEDULER` | `0` | 设为 `1` 关闭监控后台线程 |

## 目录结构

```
fishclone/
├─ run.py                     # 开发入口
├─ fap/
│  ├─ __init__.py             # create_app、静态资源、后台监控线程
│  ├─ api.py                  # 40+ REST 接口
│  ├─ auth.py                 # PBKDF2 密码、HMAC 会话 Cookie
│  ├─ db.py                   # SQLite schema（34 张表）、演示数据
│  ├─ notify.py               # Bark / Telegram / Webhook / SMTP
│  ├─ backup.py               # ZIP 备份、暂存恢复、启动替换
│  ├─ ratelimit.py            # 登录/初始化限流
│  ├─ knowledge.py            # 文档分块、中文检索、AI 上下文
│  ├─ exports.py              # 订单/商品/消息 XLSX 导出
│  ├─ publish.py              # 素材发布、自动补货
│  ├─ sync.py                 # 平台订单同步与字段映射
│  ├─ jobs.py                 # 持久化定时任务与调度执行
│  ├─ platform/               # Mock / Goofish / mtop 客户端
│  ├─ engines/
│  │  ├─ replies.py           # 自动回复匹配
│  │  ├─ delivery.py          # 固定/库存/API/流程发货
│  │  ├─ workflows.py         # 节点式流程引擎
│  │  ├─ monitor.py           # 商品监控轮询
│  │  └─ ai.py                # OpenAI 兼容客户端
│  └─ platform/
│     ├─ base.py              # 适配器接口
│     ├─ mock.py              # Mock 平台（本地演示/测试）
│     └─ goofish.py           # 真实闲鱼适配器 seam（未启用）
├─ web/                       # 原生 JS + CSS 单页后台
│  ├─ manifest.webmanifest    # PWA 清单
│  ├─ sw.js                   # Service Worker（应用壳缓存）
│  └─ icons/                  # PWA 图标
├─ CHANGELOG.md              # 版本与已知限制
├─ 使用攻略.md               # 部署、接入、运营与排障手册
├─ scripts/                  # lwp_probe.py / smoke.py / smoke_http.py / smoke_pwa.js
├─ tests/test_core.py         # 核心接口/引擎测试
├─ tests/test_p1.py           # 通知、备份恢复、媒体、限流测试
├─ tests/test_p2.py           # 知识库、XLSX 导出测试
├─ tests/test_p3.py           # 发布、补货、快捷话术、PWA 测试
├─ tests/test_p4.py           # 扫码登录（passport 调用 mock）测试
├─ tests/test_p5.py           # 多用户隔离、角色与管理员保护测试
├─ tests/test_p6.py           # mtop 签名、令牌重试、响应解析测试
├─ tests/test_p7.py           # 订单同步、审计隔离、话术归属测试
├─ tests/test_p8.py           # 定时任务、调度 tick、备份任务、权限测试
├─ tests/test_p9.py           # 自动擦亮、mtop 错误、擦亮任务测试
├─ tests/test_p10.py          # 订单好评、自动评价、失败记录测试
├─ tests/test_p11.py          # 消息接入桥、令牌、幂等与 outbox 测试
├─ tests/test_p12.py          # 真实发布 payload、归属与失败日志测试
├─ tests/test_p13.py          # 商品下架/批量下架、item_id 持久化测试
├─ tests/test_p14.py          # 订单列表解析、upsert、定时列表模式测试
├─ tests/test_p15.py          # 多页订单同步、limit 上限、任务页数测试
├─ tests/test_p16.py          # 账号代理透传与代理检测接口测试
├─ tests/test_p17.py          # 修改密码、session_version、管理员重置测试
├─ tests/test_p18.py          # 登录会话列表、单设备吊销、legacy token 测试
├─ tests/test_p19.py          # 订单删除、退款状态与归属测试
├─ tests/test_p20.py          # 系统状态、日志清理与权限测试
├─ tests/test_p21.py          # 定时日志清理任务、权限与注册测试
├─ tests/test_p22.py          # 会话搜索、未读过滤、消息分页测试
├─ tests/test_p23.py          # 历史消息搜索、全部已读、商品筛选测试
├─ tests/test_p24.py          # 单会话暂停/恢复自动回复、桥接尊重暂停测试
├─ tests/test_p25.py          # 定时暂停、到期自动恢复测试
├─ tests/test_p26.py          # 后台到期扫描、有效暂停保留测试
├─ tests/test_p27.py          # 总览 7/30 天范围、范围统计与钳制测试
├─ tests/test_p28.py          # 事件轮询游标、订单/任务事件、用户隔离测试
├─ tests/test_p29.py          # 长轮询立即返回、超时、用户隔离测试
├─ tests/test_p30.py          # 审计搜索/动作/时间过滤、运营隔离、XLSX 导出测试
├─ tests/test_p31.py          # 平台发货成功/失败/状态校验测试
├─ tests/test_p32.py          # 经营报表任务、渠道归属测试
├─ tests/test_p33.py          # 账号资料刷新、Mock 拒绝、错误映射、隔离测试
├─ tests/test_p34.py          # 账号详情汇总、Cookie 隐藏、隔离测试
├─ tests/test_p35.py          # 账号批量连接/断开/启停、权限测试
├─ tests/test_p36.py          # 账号 JSON 导出/导入、去重、权限测试
├─ tests/test_p37.py          # 加密账号导出/导入、密码校验测试
├─ tests/test_p38.py          # 电影票 CRUD、状态、二维码、隔离测试
├─ tests/test_p39.py          # 电影票核销、取票码、重复核销测试
├─ tests/test_p40.py          # LWP 令牌/握手诊断、失败阶段、隔离测试
├─ tests/test_p41.py          # 买家标签 upsert、搜索、隔离测试
├─ tests/test_p42.py          # 会话标签展示、标签筛选、隔离测试
├─ tests/test_p43.py          # 买家概览聚合、缺失参数、隔离测试
├─ tests/test_p44.py          # 买家最近消息时间线、隔离测试
├─ tests/test_p45.py          # 买家消息游标分页、导出、隔离测试
├─ tests/test_p46.py          # 安全响应头、Cookie 标志、Secure 开关测试
├─ tests/test_p47.py          # LWP 帧结构、本地回显传输测试
├─ tests/test_p48.py          # LWP 发送开关、参数校验、Mock 拦截测试
├─ tests/test_p49.py          # 电影票 XLSX 导出、运营隔离测试
├─ tests/test_p50.py          # 电影票导出状态/关键词筛选测试
├─ tests/test_p51.py          # 买家黑名单 CRUD、自动回复跳过/恢复测试
├─ tests/test_p52.py          # 审计日志游标分页、筛选、隔离测试
├─ tests/test_p53.py          # 订单备注设置/清空、字段限制、隔离测试
├─ tests/test_p54.py          # 订单备注搜索、导出备注列测试
├─ tests/test_p55.py          # 订单操作记录、实体关联、缺失/隔离测试
├─ tests/test_p56.py          # 旧审计实体回填、幂等测试
├─ tests/test_p57.py          # 订单状态统计、退款收入、隔离测试
├─ tests/test_p58.py          # 订单统计时间范围、非法参数、隔离测试
├─ shots/                     # 运行截图
└─ data/                      # 运行时生成（已 gitignore）
```

## 核心设计

### 自动发货

规则绑定商品（`goods_id`，为空表示兜底），按以下顺序执行：

1. `fixed`：模板渲染（`{{order_no}}`、`{{buyer}}`、`{{quantity}}` 等变量）；
2. `stock`：从 `autosell_stock` 原子取 N 条（`multi_quantity` 控制按数量交付），库存不足则整单失败；
3. `api`：按模板渲染 URL/headers/body，调用外部接口，支持 `api_response_path` 点号取值；
4. `workflow`：运行流程，取上下文中的 `delivery` 作为发货内容。

每次执行写入 `delivery_logs`，订单状态更新为 `delivered` / `failed`，支持重试。

### 自动回复

按 `priority DESC, id ASC` 遍历启用规则：

- `exact` 精确匹配、`keyword` 逗号分隔关键词、`regex` 正则；
- 命中后渲染文本/图片回复；
- 未命中且账号与会话都开启 AI、且已配置 AI Key 时，调用 OpenAI 兼容接口兜底。

### 流程引擎

节点 + 连线的有向图，`condition` 节点按 `true/false` 选择分支，最多 50 步并检测循环；
每次运行写入 `workflow_runs` 与 `workflow_steps`，可在 API 中回放。

### 平台适配器

`MockAdapter` 使用 `mock_items` 表并可按关键词合成商品，完全离线；
`GoofishAdapter` 实现了真实的扫码登录与登录态检测，消息/订单/发布等 mtop 操作仍返回明确的未启用错误。

### 闲鱼扫码登录

- `POST /api/accounts/<id>/qr/start` 调用 `passport.goofish.com/newlogin/qrcode/generate.do`，
  服务端渲染二维码 PNG（data URL），会话保留在内存中 5 分钟；
- `GET /api/accounts/<id>/qr/status/<session_id>` 用 POST 调用 `qrcode/query.do`，
  解析 `NEW / SCANNED / CONFIRMED / EXPIRED / CANCELED`；
- 确认后抓取 passport Cookie，并调用 `hasLogin.do` 校验，**校验通过才写入账号并置为在线**；
- 二维码和 Cookie 只在服务端内存/数据库中短暂存在，状态接口不会回传 Cookie。

### 账号代理

- 账号的 `proxy` 字段会用于该账号的扫码登录、mtop 请求（搜索/详情/发布/下架/擦亮/好评/订单）；
- 支持 `http://` / `https://` 代理；未安装 socks 依赖时不支持 `socks5://`；
- 账号页「测代理」调用 `POST /api/accounts/<id>/proxy-test`，通过 `api.ipify.org` 返回出口 IP 与耗时，
  未配置代理时显示直连出口 IP，可用于排查代理是否生效。

### 账号资料刷新

- 真实账号「资料」按钮调用 `mtop.taobao.idlemessage.pc.loginuser.get`；
- 解析昵称、头像、平台用户 ID 并写入账号，列表展示昵称与 ID；
- Mock 账号直接拒绝；无登录态返回 mtop 错误码。

### 账号详情

- 点击账号名打开详情：头像/昵称/平台 ID、状态、Cookie 是否配置、代理、累计收入；
- 数据量统计：商品、订单、会话、回复规则、发货规则；
- 最近 5 条订单与最近 5 个商品；
- 详情接口不返回 Cookie，只返回 `has_cookie`；
- 详情内提供连接/断开、扫码、刷新资料、测代理、编辑快捷操作；
- 列表支持勾选后批量连接/断开/启用/停用，逐个返回成功或失败原因。

### 账号导入 / 导出

- `GET /api/accounts/export` 导出当前用户账号（含 Cookie、代理、备注、AI/好评配置），JSON `version=1`；
- `POST /api/accounts/import` 接收 `accounts` 数组，最多 100 条，按 `owner_id + name` 去重；
- 导入后账号默认离线、启用；操作写入审计日志；
- 导入/导出都受 `owner_id` 隔离，运营只能处理自己的账号；
- 加密导出：`POST /accounts/export/encrypted` 使用 PBKDF2-SHA256(200k) + AES-256-GCM，
  输出 `fap-accounts-encrypted` JSON；导入时自动识别并提示密码。

### LWP WebSocket 诊断

- 真实账号「WS」按钮先调用 `mtop.taobao.idlemessage.pc.login.token` 获取令牌；
- 再用 `websockets` 连接 `wss://wss-goofish.dingtalk.com/account?accessToken=...`；
- 连接后发送重建的 `/reg` 注册帧，并展示服务端响应或超时；
- 返回令牌获取、握手、`/reg` 响应与错误阶段（`stage=token`）；
- 目前只做连通性诊断，LWP 消息订阅/发送协议仍未实现，界面会明确提示。

### LWP 帧原型

- `fap/platform/lwp_frames.py` 按原程序符号重建 `/reg`、`/r/MessageSend/sendByReceiverScope`、
  `/r/SyncStatus/ackDiff` 帧结构；
- 从 `.so` 字符串/引用中确认注册头字段：`app-key`、`token`、`ua`、`dt`、`wv`、`sync`、`did`、`mid`、`cache-header`；
- 除 `app-key/ua` 外的头字段按账号运行态可选注入；
- `fap/platform/lwp.py::exchange` 使用 `websockets` 同步客户端发送帧并收集响应；
- `python scripts/lwp_probe.py --token ... [--conversation ... --receiver ... --text ...]`
  可在真实登录后手动探测；
- 帧字段尚未在真实账号上验证，属于实验性代码；
- 真实账号可设 `FAP_ENABLE_LWP_SEND=1` 后调用
  `POST /api/accounts/<id>/lwp/send {conversation_id,receiver_id,text}` 做单次校准，
  默认关闭，避免误发。

### mtop（H5 API）客户端

- 标准 H5 签名：`md5(token + "&" + t + "&" + appKey + "&" + data)`，appKey `34839810`；
- `_m_h5_tk` 缺失/过期时自动用服务端下发的新 token 重试一次；
- 支持 JSON / JSONP 响应，`FAIL_*`/`RGV587` 等错误映射为 `MtopError`（带 code/ret）；
- 已接入：
  - `mtop.taobao.idle.pc.detail`（商品详情）
  - `mtop.taobao.idlemtopsearch.pc.search`（商品搜索，真实账号监控使用）
- 账号页「mtop」按钮可手动调用详情接口做诊断；平台风控（如 RGV587）会原样显示错误码。
- 消息发送、发布仍依赖 WebSocket/其他 mtop 接口，暂未启用。

### 订单同步

- 订单页「同步订单」输入平台订单号，调用 `mtop.idle.web.trade.order.detail`（Mock 账号返回演示数据）；
- 字段递归提取：订单号、买家、商品标题、金额、数量、状态，写入或更新本地 `orders`；
- 可勾选「同步后自动发货」，同步为待发货时复用自动发货引擎；
- 单笔同步幂等，重复同步不会产生重复订单。
- 订单列表同步调用 `mtop.taobao.idle.trade.merchant.sold.get`，递归解析 `bizOrderId`/买家/金额/状态；
- 控制台「同步列表」可一次拉取并 upsert，支持最多 10 页（每页 20 条），返回 `fetched/created/updated/pages`；
- 定时任务的订单同步任务**订单号留空即走列表模式**，可配置页数，适合周期轮询。

### 退款与订单删除

- 订单详情可记录退款：申请/退款中/成功/失败、金额、原因；
- 退款成功会把订单状态置为 `refunded` 并记录 `refunded_at`；
- 订单可删除，同时删除交付日志；
- 目前是**本地业务记录**，不对接闲鱼退款接口，避免误操作真实资金。

### 订单备注

- `GET /api/orders/stats?days=7|30` 返回总数、各状态数量/金额与收入（排除已退款）；
- 订单页标签展示 全部/待发货/已发货/失败 数量，并支持全部/近 7 天/近 30 天切换；

- `PATCH /api/orders/<id> {note}` 只允许修改备注，避免误改状态/金额；
- 订单详情展示备注并提供「编辑备注」；
- 订单搜索同时匹配订单号/买家/商品/备注；订单 XLSX 导出新增「备注」列；
- `GET /api/orders/<id>/history` 返回该订单的审计操作记录，详情页展示「操作记录」；
- 订单审计写入 `entity_type='order' / entity_id`，历史查询优先按实体关联，旧日志回退订单号匹配；
- 启动时自动回填旧审计：从 `order=<订单号>` 或 `order=<订单ID>` 解析并写入实体字段。
- 备注写入审计日志，按 `owner_id` 隔离。

### 平台发货同步

- 订单详情对已发货订单提供「同步平台发货」，调用 `mtop.taobao.idle.logistic.consign.dummy`；
- 成功后记录 `ship_status=success` 与 `platform_shipped_at`，重复同步会被拒绝；
- 失败记录 `ship_status=failed`，可再次重试；
- Mock 账号直接成功，真实账号需要有效登录 Cookie。

### 定时任务

- `job_tasks` 存任务配置（类型、间隔、config、下次运行时间），`job_runs` 存每次执行结果；
- 调度线程每 5 秒调用一次 `jobs.tick()`，执行到期任务并写回状态/下次运行时间；
- 类型：`order_sync`（固定订单号/列表周期同步）、`monitor`（运行监控规则）、`relist`（运行补货规则）、
  `polish`（周期擦亮）、`backup`（自动备份，仅管理员）、`prune`（日志清理，仅管理员，可配天数/VACUUM）、
  `report`（经营报表，发送到当前用户的通知渠道）；
- 任务按 `owner_id` 隔离，监控/补货/订单任务只能引用自己的资源；
- 单次失败只记失败状态，不会中断调度器；控制台支持启停、手动运行与运行记录。

### 经营报表

- 定时任务 `report` 按 1/7/30 天统计订单数、收入、退款、未读会话与在售商品；
- 通过 `notify.dispatch(owner_id=...)` 只发送到该用户自己的通知渠道；
- 结果写入任务运行记录与通知日志，没有渠道时返回 `0/0` 但不报错。

### 自动擦亮

- 调用 `mtop.taobao.idle.item.polish`，按商品 ID 逐个擦亮，最多 50 个；
- 账号页「擦亮」可手动输入商品 ID，或尝试从 `mtop.idle.web.xyh.item.list` 拉取在售商品；
- 每个商品独立返回成功/失败原因（如 `POLISH_DUPLICATE`、`FAIL_SYS_SESSION_EXPIRED`），不会因单个失败中断；
- 定时任务新增 `polish` 类型，可周期擦亮固定商品列表；
- 真实调用需要有效登录 Cookie，Mock 账号会直接拒绝。

### 订单评价

- 订单详情对已发货订单提供「好评」，可自定义内容，调用 `mtop.taobao.idle.merchant.rate.create`；
- 账号可开启「自动好评」并配置文案，发货成功后自动评价，失败只记录 `rate_status=failed`，不影响发货；
- 订单记录 `rated_at` / `rate_status` / `rate_content`，重复评价会被拒绝；
- 所有评价操作写入审计日志。

### 会话标签联动

- 会话列表通过子查询返回 `tags`（同一买家的全部标签），列表与聊天头部展示标签徽章；
- `GET /api/conversations?tag=VIP` 按买家标签过滤，标签与 `owner_id` 联动；
- 会话页提供标签下拉筛选，与搜索/未读可组合；
- 聊天头部「标签」按钮可直接为当前买家新增标签，保存后自动刷新。

### 会话检索与分页

- `GET /conversations?q=&unread=1` 支持按买家、最后消息或**历史消息内容**搜索，可只看未读；
- `POST /conversations/read-all` 只清除当前用户自己的未读；
- `GET /conversations/<id>/messages?limit=&before_id=` 返回最新一页与 `has_more`，可向前翻页；
- 会话页提供搜索框与「只看未读」，聊天区可「加载更早」，避免大会话一次渲染全部消息；
- 每个会话可单独「暂停自动回复」，支持 30 分钟 / 2 小时 / 24 小时 / 直到手动恢复；
- 暂停期间规则、AI 与外部桥都不回复；定时暂停到期后由后台调度器每 5 秒扫描自动恢复，
  下一条入站消息也会做一次到期兜底。

### 消息接入桥（外部桥）

- 管理后台「消息接入」可生成/轮换接入令牌，令牌只对管理员展示，普通设置接口不会返回；
- 外部桥（浏览器插件、Android 通知监听等）用 `X-FAP-Token` 或 Bearer 调用：
  - `POST /api/integrations/messages`：入站消息（`account_id/buyer/text/external_id`），自动跑回复规则并写入待发回复；
  - `GET /api/integrations/outbox`：轮询 `delivery_status=pending` 的出站消息；
  - `POST /api/integrations/outbox/<id>/ack`：桥发送成功后回写 `sent/failed`；
  - `POST /api/integrations/send`：外部系统主动排队一条人工消息；
- `external_id` 在会话内唯一，重复上报不会重复入库；
- 这条链路不依赖闲鱼 LWP WebSocket，真实发送由桥完成，适合先接通浏览器插件/通知监听。

### 通知

`notify.dispatch()` 在订单发货成功/失败、监控命中、流程 notify 节点、登录限流时触发：

- 无账号绑定的渠道是全局渠道；有绑定的渠道只对绑定账号触发；
- 支持 Bark、Telegram Bot、任意 JSON Webhook、SMTP（starttls/ssl）；
- 每次发送写入 `notification_logs`，失败不会影响发货/回复主流程。

### 备份与恢复

- 备份使用 SQLite 在线备份 API 生成一致性快照，打包 `app.db`、`secret.key`、`meta.json`；
- 恢复采用「暂存 + 重启生效」：上传后写入 `restore-pending.db`，下次启动时自动替换，
  并把原库另存为 `app.db.bak-*`，避免 Windows 下替换正在使用的 SQLite 文件。

### 媒体

上传的图片保存在 `data/media/`，数据库只记录元数据；`/media/<uuid>.<ext>` 直接提供访问，
商品主图与图片回复共用同一套上传接口。

### 知识库与 AI

- 文档按 400 字（60 字重叠）自动分块；
- 中文按字符二元组、英文按小写词建立索引，检索使用 TF-IDF 风格打分；
- 在设置中选择「知识库增强」后，AI 回复前会检索 Top 3 分块并作为系统提示注入，
  同时要求模型只使用与问题相关的资料。

### 导出

`/api/exports/orders.xlsx`、`/goods.xlsx`、`/messages.xlsx` 使用 openpyxl 生成，
带表头样式、冻结首行和自动筛选；页面上的「导出 XLSX」按钮直接下载。

### 商品发布与补货

- 素材库保存标题、描述、价格、库存、主图、发布账号；
- 发布时调用平台适配器 `publish_item`，Mock 适配器返回 `mock-*` item id，
  引擎落地一条商品记录和发布日志；
- 补货规则按间隔检查商品，发现下架/售罄就用素材重新上架（库存/价格恢复），
  并记录「已补货 / 跳过 / 失败」日志；
- 真实账号调用 `mtop.idle.pc.idleitem.publish`，提交标题/描述/价格/数量/图片（仅绝对 URL）/
  categoryId；成功时从响应提取 `itemId` 并落地商品，失败写入发布日志；
- 真实发布参数仍需有效登录态与真实分类/图片 CDN 地址校准，未登录会返回 `FAIL_SYS_SESSION_EXPIRED`；
- 发布生成的 `goods.owner_id` 取所属账号 owner，避免运营发布的商品归到管理员；
- 商品下架：有平台 `item_id` 的真实商品调用 `mtop.alibaba.idle.seller.pc.item.batch.offline`，
  成功后标记本地 `off_shelf`；Mock 或无 item_id 时只做本地下架；失败保留原状态并返回 mtop 错误。

### 快捷话术与 PWA

- 会话页下拉选择话术，管理弹窗可增删，保存在 `quick_phrases` 表；
- `manifest.webmanifest` + `sw.js` 提供安装到桌面/主屏与离线应用壳，
  API 请求仍走网络（离线时显示错误提示）。

### 多用户与数据隔离

- 角色：`admin`（全部数据 + 用户/设置/备份/审计）与 `operator`（仅自己的数据）；
- 12 张业务表带 `owner_id`（账号、商品、订单、会话、规则、流程、素材、补货、知识库、通知、媒体）；
- 所有列表/详情/修改/删除按 `owner_id` 过滤，越权按 404 处理；
- 管理员页面：用户 CRUD、启停、重置密码、最后管理员保护、带数据用户禁止删除；
- 会话统计、导出、仪表盘、通知投递同样按归属过滤。

### 密码与会话

- 每个用户有 `session_version`，签名 Cookie 携带该版本；
- 自助修改密码或管理员重置密码都会 `session_version+1`，**所有旧 Cookie 立即失效**；
- 当前设备在修改密码后会收到新 Cookie，不需要重新登录；
- 每次登录写入 `user_sessions`（jti、UA、IP、登录/活跃时间），可吊销单个设备；
- 入口：侧边栏用户区的钥匙按钮，任何角色都可用；「登录设备」页可查看并吊销会话。

### 系统状态与日志清理

- `GET /api/system/status`（管理员）返回版本、运行时长、数据库/WAL 大小、各表数量、备份数、调度器状态；
- `POST /api/system/prune`（管理员）按天数清理审计、通知、任务运行、交付、发布、补货日志；
- 设置页「系统状态」卡片展示关键指标，并提供「清理 30 天前日志」按钮。

### 运营总览

- `GET /api/dashboard?days=7|30` 返回区间订单数、收入、退款金额、待发货/失败、库存、未读与逐日趋势；
- 区间上限 90 天，所有统计按 `owner_id` 隔离；
- 总览页可切换「近 7 天 / 近 30 天」，展示区间卡片、趋势图、最近消息与最近订单。

### 事件长轮询与未读角标

- `GET /api/events/wait?after_message=&after_order=&after_job=&timeout=20` 长轮询等待新事件；
- 有新消息/订单/任务时立即返回，否则最多等待 20 秒后返回空结果，前端随即发起下一次请求；
- 前端首次请求只建立游标，之后新入站消息会更新会话未读角标与浏览器标题并弹出提示；
- 新订单、失败任务同样提示；所有事件按 `owner_id` 隔离。

### 审计检索

- `GET /api/audit-logs?q=&action=&days=&limit=&before_id=` 支持动作/详情搜索、动作前缀、时间范围与游标分页；
- 运营固定追加 `user_id=自己`，管理员可看全部；
- `GET /api/audit-logs.xlsx` 按同样条件导出 XLSX；
- 审计页提供搜索框、动作前缀、时间筛选与「加载更早」游标分页（100 条/页）。

### 买家标签

- `GET/POST /api/buyer-tags`、`DELETE /api/buyer-tags/<id>`；
- `GET /api/buyers/summary?buyer=` 聚合订单数、消费、会话、标签与最近订单；
- 同一买家同一标签执行 upsert，更新备注而不是重复插入；
- 支持按买家/标签/备注搜索；
- 按 `owner_id` 隔离，运营只能管理自己的买家标签；
- 聊天头部点击买家名查看「买家概览」：订单数、累计消费（不含已退款）、会话/未读、标签、最近订单与最近 10 条消息；
- 黑名单 `GET/POST /api/buyer-blacklist`：命中后自动回复直接跳过（规则/AI 均不触发），移出后恢复。
- `GET /api/buyers/messages?buyer=&before_id=&limit=20` 游标分页查看买家全部消息；
- `GET /api/buyers/messages.xlsx?buyer=` 导出该买家消息；
- 概览内可打开「全部消息」弹窗并加载更早，或直接导出 XLSX。

### 电影票

- `GET/POST /api/movie-tickets`、`PATCH/DELETE /api/movie-tickets/<id>` 管理电影票订单；
- 状态：待支付、已支付、已核销、已退款、已取消；
- 创建时生成 `MT` 开头订单号与随机取票码；
- `GET /api/movie-tickets/<id>/qr` 返回取票二维码 PNG Data URL；
- `GET /api/movie-tickets.xlsx?status=&q=` 导出电影票订单，支持状态/关键词筛选；
- `POST /api/movie-tickets/<id>/verify` 或 `/api/movie-tickets/verify {code}` 核销已支付票，
  记录 `used_at/verified_by`，重复核销返回已核销；
- 页面顶部展示总数、已支付、已核销与票款汇总；
- 按 `owner_id` 隔离，运营看不到管理员票务数据。

## 测试

### 干净实例冒烟

```bash
cd fishclone
python scripts/smoke.py
```

在临时数据目录完成 setup → 登录 → 建账号/商品/发货规则 → 模拟下单/平台发货 → 会话消息 →
电影票核销/导出 → 备份 → 审计检查，共 14 项，不污染现有数据。

### HTTP 冒烟

```bash
python scripts/smoke_http.py
```

在随机端口启动 waitress，使用 httpx 走真实 HTTP/Cookie/安全头，完成 12 项核心检查。

### PWA 浏览器冒烟

```bash
node scripts/smoke_pwa.js
```

用 Edge/CDP 验证登录、应用外壳、manifest、Service Worker 注册/接管与离线外壳/数据，共 6 项；
Service Worker 使用 `fap-shell-v3` 缓存外壳、`fap-data-v1` 缓存最近一次 GET API 数据，
导航离线回退 `/`，离线时仍可看到上次的总览/列表数据；退出登录会通知 SW 清除数据缓存。

### 自动化测试

```bash
cd fishclone
python -m unittest discover -s tests -v
```

覆盖：初始化/登录/401、自动回复匹配、固定发货、库存多数量、库存不足、流程条件分支、监控任务、
跨站请求拒绝、密码哈希、通知渠道与订单事件、备份创建/下载/暂存恢复、图片上传/删除、登录限流、
知识库检索/分块/AI 注入、三类 XLSX 导出、素材发布/批量发布、自动补货、快捷话术、PWA 资源、
扫码登录状态流转与 Cookie 落库、多用户隔离与管理员保护、mtop 签名/令牌重试/JSONP/错误映射、
订单同步幂等与字段映射、审计按用户过滤、话术归属、定时任务调度与权限、自动擦亮与部分失败、
手动/自动好评与失败记录、消息接入桥令牌与 outbox、真实发布参数与归属、商品下架、
订单列表解析、幂等与多页同步、账号代理透传与检测、改密后旧会话失效、登录设备吊销、
订单删除与退款状态、系统状态与日志清理、定时清理任务、会话搜索与消息分页、
历史消息搜索/全部已读/商品筛选、单会话自动回复暂停/定时恢复、后台到期扫描、总览 7/30 天统计、
事件轮询与未读角标、长轮询事件等待、审计检索与导出、平台发货同步、定时经营报表、账号资料刷新/详情、
账号批量操作、账号 JSON 导入/导出、加密账号导入/导出、电影票模块与核销、LWP 诊断、买家标签、
会话标签筛选、买家概览、最近消息、买家消息分页/导出、安全响应头与 Cookie 加固、LWP 帧原型与受控发送、
电影票导出与筛选、干净实例冒烟（14 项）、HTTP 冒烟（12 项）、PWA 冒烟（6 项，含离线数据）、
买家黑名单、审计日志分页、订单备注/搜索/操作记录、审计实体关联/回填、订单状态计数/时间范围。
当前共 **240** 个测试。

## 安全说明

- 密码：PBKDF2-HMAC-SHA256（210,000 轮，随机盐）；
- 会话：HMAC-SHA256 签名的 HttpOnly Cookie，`SameSite=Lax`，密钥首次启动随机生成（不提供默认密钥）；
- HTTPS 部署可设 `FAP_SECURE_COOKIES=1` 为会话 Cookie 增加 `Secure`；
- 响应统一添加 `X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`、COOP 与 CSP；
- CSP 仅允许同源脚本/连接、`data:`/HTTPS 图片，禁止被第三方 iframe 嵌入；
- 写请求校验 `Origin`，拒绝跨站；
- 登录 5 次失败/5 分钟限流，返回 `Retry-After` 并写审计；
- SQL 全部参数化，前端输出统一 HTML 转义；
- 上传图片校验真实格式与 5MB 上限，文件名使用随机 UUID；
- AI Key、通知密钥以明文存储在本地 SQLite（与多数自托管工具一致），请限制数据目录权限；
- 生产部署请使用 `waitress`/`gunicorn` + HTTPS 反向代理，并修改默认管理员密码；
- PWA 会在本机缓存最近一次 GET API 数据（`fap-data-v1`），退出登录时清除；共用设备请手动退出。

## 路线图

见 [PLAN.md](PLAN.md)。P0–P5、mtop 签名/搜索/详情、单笔订单同步、定时任务、自动擦亮/好评、
消息接入桥、真实发布/下架、订单列表/多页同步已完成；下一阶段：LWP WebSocket、mtop 消息发送、订单删除。

## 运行截图

| 闲鱼扫码登录 | 商品发布 |
|---|---|
| ![qr](shots/qr-login.png) | ![publish](shots/publish.png) |

| 自动补货 | 自动发货 |
|---|---|
| ![relist](shots/relist.png) | ![autosell](shots/autosell.png) |

| 用户管理 | 设置与备份 |
|---|---|
| ![users](shots/users.png) | ![settings](shots/settings.png) |

| 定时任务 |
|---|
| ![jobs](shots/jobs.png) |

| 自动擦亮 |
|---|
| ![polish](shots/polish.png) |

| 订单好评 |
|---|
| ![rating](shots/rating.png) |

| 消息接入桥 |
|---|
| ![bridge](shots/bridge.png) |

| 真实发布诊断 |
|---|
| ![publish-real](shots/publish-real.png) |

| 商品下架 |
|---|
| ![offline](shots/offline.png) |

| 订单列表同步 |
|---|
| ![order-list](shots/order-list.png) |

| 代理检测 |
|---|
| ![proxy](shots/proxy.png) |

| 修改密码 |
|---|
| ![password](shots/password.png) |

| 登录设备 |
|---|
| ![sessions](shots/sessions.png) |

| 退款记录 |
|---|
| ![refund](shots/refund.png) |

| 系统状态 |
|---|
| ![system](shots/system.png) |

| 自动日志清理 |
|---|
| ![prune-job](shots/prune-job.png) |

| 会话搜索 |
|---|
| ![chat-search](shots/chat-search.png) |

| 商品筛选 |
|---|
| ![goods-filter](shots/goods-filter.png) |

| 自动回复暂停 |
|---|
| ![autoreply-pause](shots/autoreply-pause.png) |

| 定时暂停 |
|---|
| ![pause-modal](shots/pause-modal.png) |

| 近 30 天总览 |
|---|
| ![dashboard-30](shots/dashboard-30.png) |

| 未读角标 |
|---|
| ![unread-badge](shots/unread-badge.png) |

| 审计检索 |
|---|
| ![audit-filter](shots/audit-filter.png) |

| 审计分页 |
|---|
| ![audit-paging](shots/audit-paging.png) |

| 平台发货 |
|---|
| ![ship](shots/ship.png) |

| 订单备注 |
|---|
| ![order-note](shots/order-note.png) |

| 备注搜索 |
|---|
| ![order-note-search](shots/order-note-search.png) |

| 订单状态计数 |
|---|
| ![order-tabs](shots/order-tabs.png) |

| 订单统计时间范围 |
|---|
| ![order-stats-range](shots/order-stats-range.png) |

| 订单操作记录 |
|---|
| ![order-history](shots/order-history.png) |

| 经营报表 |
|---|
| ![report-job](shots/report-job.png) |

| 账号资料刷新 |
|---|
| ![profile](shots/profile.png) |

| 账号详情 |
|---|
| ![account-detail](shots/account-detail.png) |

| 账号快捷操作 |
|---|
| ![account-actions](shots/account-actions.png) |

| 账号批量操作 |
|---|
| ![account-batch](shots/account-batch.png) |

| 账号导入导出 |
|---|
| ![account-import](shots/account-import.png) |

| 加密账号导出 |
|---|
| ![account-encrypted](shots/account-encrypted.png) |

| 电影票 |
|---|
| ![movie](shots/movie.png) |

| 取票二维码 |
|---|
| ![movie-qr](shots/movie-qr.png) |

| 电影票核销 |
|---|
| ![movie-verify](shots/movie-verify.png) |

| 电影票导出 |
|---|
| ![movie-export](shots/movie-export.png) |

| 电影票筛选导出 |
|---|
| ![movie-export-filter](shots/movie-export-filter.png) |

| PWA 冒烟 |
|---|
| ![pwa-smoke](shots/pwa-smoke.png) |

| PWA 离线数据 |
|---|
| ![pwa-offline](shots/pwa-offline.png) |

| LWP WebSocket 诊断 |
|---|
| ![ws-test](shots/ws-test.png) |

| 买家标签 |
|---|
| ![buyer-tags](shots/buyer-tags.png) |

| 自动回复黑名单 |
|---|
| ![buyer-blacklist](shots/buyer-blacklist.png) |

| 会话标签筛选 |
|---|
| ![conv-tags](shots/conv-tags.png) |

| 聊天内新增标签 |
|---|
| ![chat-tag](shots/chat-tag.png) |

| 买家概览 |
|---|
| ![buyer-summary](shots/buyer-summary.png) |

| 买家最近消息 |
|---|
| ![buyer-timeline](shots/buyer-timeline.png) |

| 买家消息分页 |
|---|
| ![buyer-messages](shots/buyer-messages.png) |

| 安全头验证（页面正常） |
|---|
| ![security](shots/security.png) |

| 通知渠道 | 商品管理 |
|---|---|
| ![notifications](shots/notifications.png) | ![goods](shots/goods.png) |

| 订单 | 会话中心 |
|---|---|
| ![orders](shots/orders.png) | ![conversations](shots/conversations.png) |

| mtop 诊断 | 知识库 |
|---|---|
| ![mtop](shots/mtop.png) | ![knowledge](shots/knowledge.png) |

| 操作日志 | 登录 |
|---|---|
| ![audit](shots/audit.png) | ![login](shots/login.png) |
