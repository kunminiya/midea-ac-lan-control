# midea-ac-control — 美的空调局域网直连控制 Skill

让 AI Agent(Hermes / Claude / 其他支持 skill 的 Agent)通过局域网直接查询和控制美的/华凌空调,无需美的账号密码。

## 安装

将 `midea-ac-control/` 整个目录放入 Agent 的 skills 目录:

```bash
# 示例: Hermes Agent
cp -r midea-ac-control ~/.hermes/skills/smart-home/

# 或手动放置后重启 Agent 会话
```

## 依赖

```bash
python3 -m venv venv && venv/bin/pip install msmart-ng
```

## 用法(AI Agent 视角)

```bash
# 查询状态(只读, 自动带用电数据)
venv/bin/python midea_ac.py query

# 控制: k=v 通用格式
venv/bin/python midea_ac.py control power_state=true
venv/bin/python midea_ac.py control target_temperature=26
venv/bin/python midea_ac.py control fan_speed=HIGH swing_mode=BOTH turbo=true
```

## 文档

| 文件 | 内容 |
|------|------|
| `SKILL.md` | Skill 元数据 + 核心原理 + 坑表 |
| `references/agent-guide.md` | **Agent 完整操作指南**(操作清单/时序/性能/架构) |
| `references/ble-notes.md` | BLE 直连探索记录(为什么走 LAN) |
| `scripts/midea_ac.py` | 可直接运行的查询/控制脚本 |

## 核心原理(30 秒版)

- msm-ng 内置 US/DE/KR 演示账号 → 国际版云端 `getToken(udpid)` 取任意设备 V3 token/key(接口不校验归属)
- 局域网 TCP 6444 直连认证 → 查询/控制,全程不需要美的账号
- token 长期有效(缓存 7 天),缓存命中时完全离线,~1.7s 完成一次操作

## 免责声明

- 演示账号机制来自 msm-ng 内置设计,仅用于技术学习与研究
- 请在自己的设备上使用,注意网络安全
- 通信协议基于社区逆向工程,非官方实现
