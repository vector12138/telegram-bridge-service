# Telegram Bridge Service

**融合版 Telegram 桥接服务**，整合了消息监听存储 + 中转发送 + API服务 + Webhook推送的全功能服务，一套代码解决所有Telegram自动化需求。

## ✨ 功能特性

### 🎯 核心能力
- ✅ **双模式支持**：
  - 🤖 **Bot模式**：使用官方Bot API，稳定可靠，适合自动发通知、机器人交互
  - 🧑 **User模式**：使用个人账号登录，可接收所有私聊/群聊/频道消息，模拟人工发送
- ✅ **消息实时监听**：自动接收所有消息，完整保存发送者、聊天、内容、时间等全字段
- ✅ **消息持久化存储**：自动保存到Redis，默认保留7天，支持自动清理旧消息
- ✅ **中转发送服务**：提供HTTP API发送消息，异步队列处理，自动重试失败任务
- ✅ **完整API接口**：发送消息、查询消息、搜索消息、任务管理、统计查询全支持
- ✅ **Webhook推送**：收到消息时自动推送到指定URL，支持签名校验，防止伪造
- ✅ **安全防护**：API密钥鉴权、聊天ID白名单、发送频率控制，防止滥用
- ✅ **自动重试**：发送失败自动重试，可配置重试次数和间隔
- ✅ **Markdown/HTML支持**：发送消息支持富文本格式，静默发送等高级选项
- ✅ **全类型媒体发送支持**：图片、文件、视频、音频、语音全部支持，兼容官方API所有send*方法

### 🔥 融合优势
> 相比之前拆分的两个项目，融合版：
> - ✅ 一套代码，统一配置，不用维护两套服务
> - ✅ 所有功能无缝整合，数据互通
> - ✅ 架构更精简，冗余代码全部删除
> - ✅ 资源占用更低，性能更好
> - ✅ 功能更完整，覆盖所有使用场景

## 📦 环境要求

- Python 3.8+
- Redis 5.0+
- 对应模式的Telegram账号（Bot Token 或个人账号）

## 🚀 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置文件
复制配置模板：
```bash
cp config.example.yaml config.yaml
```

根据需求选择运行模式：

#### 模式一：Bot 模式（推荐，适合自动发送）
```yaml
mode: "bot"
bot:
  token: "你的Bot Token，从@BotFather获取"
```

#### 模式二：User 模式（个人账号，适合接收全量消息）
```yaml
mode: "user"
user:
  api_id: 123456  # 从 https://my.telegram.org/ 获取
  api_hash: "你的API Hash"
  phone_number: "+8613800138000"  # 你的手机号
```

**必填配置**：别忘了修改 `api.api_key` 为你自己的密钥，用于接口鉴权。

### 3. 启动服务
```bash
python main.py
```

> 首次启动 User 模式时，需要输入手机号收到的验证码，登录成功后会生成 `telegram_user.session` 文件，下次启动无需验证。

### 4. 测试接口
访问 Swagger 在线文档：`http://localhost:8080/docs`，支持在线调试所有接口。

## 📚 API 接口速查

### 通用请求头
所有接口需要在请求头携带 API 密钥：
```
X-API-Key: 你在config.yaml中配置的api_key
```

### 常用接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/stats` | 获取服务运行统计 |
| POST | `/api/v1/message/send` | 发送消息，返回任务ID |
| GET | `/api/v1/task/{task_id}` | 查询发送任务状态 |
| POST | `/api/v1/task/{task_id}/retry` | 重试失败的任务 |
| GET | `/api/v1/message/received` | 获取接收的消息列表 |
| GET | `/api/v1/message/{chat_id}/{message_id}` | 根据ID查询消息详情 |
| POST | `/api/v1/message/search` | 搜索包含关键词的消息 |

### 发送消息示例
```bash
curl -X POST http://localhost:8080/api/v1/message/send \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{
    "chat_id": 123456789,
    "text": "*Hello from Telegram Bridge* \n\n这是一条融合版桥接服务的测试消息",
    "parse_mode": "Markdown"
  }'
```

返回：
```json
{"task_id": "1710923456789_abc123", "status": "pending"}
```

### 查询任务状态
```bash
curl http://localhost:8080/api/v1/task/1710923456789_abc123 \
  -H "X-API-Key: your_api_key"
```

## 🔧 高级配置

### Webhook 推送
配置后收到的消息会自动推送到你指定的URL：
```yaml
webhook:
  enabled: true
  url: "https://your-server.com/webhook/telegram"
  secret: "your_sign_secret"  # 签名密钥
```

**签名校验**：请求头会携带 `X-Telegram-Bridge-Signature`，值为 `HMAC-SHA256(secret, 请求体JSON)`，你可以在接收端校验签名防止伪造请求。

### 聊天白名单
只允许和指定的聊天ID通信，防止误发消息：
```yaml
telegram:
  allowed_chat_ids:
    - 123456789  # 你的私聊ID
    - -1001234567890  # 群聊/频道ID
```

### 存储配置
```yaml
redis:
  host: "127.0.0.1"
  port: 6379
  db: 2
  password: "your_redis_password"
  message_expire: 604800  # 消息保存7天
  max_recent_messages: 2000  # 最多保存2000条消息，超出自动清理
```

## 📊 数据存储结构

所有数据存在 Redis 中，可直接查询：

| Key 格式 | 类型 | 说明 |
|----------|------|------|
| `telegram:bridge:msg:{chat_id}:{msg_id}` | Hash | 消息详情 |
| `telegram:bridge:msg:all` | ZSet | 所有消息按时间排序 |
| `telegram:bridge:msg:chat:{chat_id}` | ZSet | 单聊天的消息列表 |
| `telegram:bridge:task:{task_id}` | Hash | 发送任务详情 |
| `telegram:bridge:queue:pending` | List | 待发送任务队列 |

## 🛠 部署建议

### 生产环境使用 PM2 后台运行
```bash
npm install -g pm2
pm2 start main.py --name telegram-bridge --interpreter python3
```

### 开机自启
```bash
pm2 save
pm2 startup
```

### 查看日志
```bash
pm2 logs telegram-bridge
```

## ⚠️ 注意事项

1. **安全第一**：生产环境务必配置 `api_key`，不要暴露未授权的接口到公网
2. **账号安全**：`*.session` 文件包含登录凭证，请勿泄露，不要提交到代码仓库
3. **频率限制**：遵守 Telegram API 频率限制，短时间大量发送可能导致账号被封禁
4. **Bot 限制**：Bot 模式下无法主动给未发过消息的用户发送消息，需要用户先给 Bot 发消息
5. **User 模式风险**：使用个人账号登录有被官方检测到封号的风险，谨慎用于生产环境

## ❓ 常见问题

### Q: 如何获取聊天 ID？
A: 给你的 Bot/个人账号发送任意消息，然后调用 `/api/v1/message/received` 接口查看返回的 `chat_id` 字段。

### Q: 支持发送图片/文件/视频吗？
A: 完全支持！所有媒体类型（图片、文件、视频、音频、语音）都支持，100%兼容官方API的sendPhoto、sendDocument、sendVideo、sendAudio、sendVoice方法，使用方式和官方API完全一致。

### Q: 可以同时运行多个实例吗？
A: 可以，多个实例会自动消费同一个 Redis 队列，实现负载均衡。

## 📄 License
MIT
