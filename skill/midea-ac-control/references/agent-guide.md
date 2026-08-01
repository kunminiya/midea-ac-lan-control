# Agent 接管美的空调操作指南

> 面向 AI Agent（或想自动化的人）的完整操作手册。本文档回答两个问题：
> 1. 局域网直连能对空调**做哪些操作**？
> 2. 每个操作**怎么下发、输出长什么样、有什么坑**？
>
> 配套脚本 `scripts/midea_ac.py` 已实现本文档全部操作，直接调用即可。

---

## 1. 快速上手

```bash
# 一次性环境准备
python3 -m venv venv && venv/bin/pip install msmart-ng

# 查询状态（只读，自动带用电数据）
venv/bin/python midea_ac.py query

# 控制（k=v 通用格式，任意属性组合）
venv/bin/python midea_ac.py control power_state=true target_temperature=26
```

输出（JSON）：
```json
{
  "power": true,
  "mode": "COOL",
  "fan_speed": "AUTO",
  "target_temperature": 26.5,
  "indoor_temperature": 30.9,
  "outdoor_temperature": 36.6,
  "error_code": 0,
  "total_energy_usage_kwh": 242.88,
  "current_energy_usage_kwh": 0.0,
  "real_time_power_usage_w": 1408.0
}
```

---

## 2. 完整操作清单（已实测，KFR-35GW/N8HA1III-D）

### 2.1 电源与模式

| 操作 | 命令 | 取值 |
|------|------|------|
| 开机 | `power_state=true` | true/false |
| 关机 | `power_state=false` | true/false |
| 模式 | `operational_mode=AUTO` | AUTO/COOL/DRY/HEAT/FAN_ONLY/SMART_DRY |
| 目标温度 | `target_temperature=26` | 16.0 ~ 30.0（0.5 步进） |

> ⚠️ **防误关机**：`apply()` 会把设备缓存状态整体下发。只改温度不指定 `power_state` 时，脚本会自动保持开机（安全默认）。Agent 直接调用脚本无需操心，但**自己写代码调用 msm-ng 时必须显式 `dev.power_state = True`**。

### 2.2 风速

| 档位 | 值 |
|------|-----|
| 自动 | `AUTO` |
| 静音 | `SILENT` |
| 低 | `LOW` |
| 中 | `MEDIUM` |
| 高 | `HIGH` |
| 最大 | `MAX` |

```bash
python midea_ac.py control fan_speed=HIGH
```

### 2.3 扫风（摆风）

| 模式 | 值 |
|------|-----|
| 关闭 | `OFF` |
| 上下 | `VERTICAL` |
| 左右 | `HORIZONTAL` |
| 上下+左右 | `BOTH` |

```bash
python midea_ac.py control swing_mode=BOTH
```

### 2.4 特色功能

| 功能 | 命令 | 说明 |
|------|------|------|
| 极速制冷/制热 | `turbo=true` | 满负荷运行，实测功率可达 ~1400W |
| ECO 节能 | `eco=true` | 节能模式 |
| 睡眠模式 | `sleep=true` | 睡眠曲线 |
| 防冻结 | `freeze_protection=true` | 制热防冷风 |
| 面板灯 | `display_on=false` | 关闭室内机显示灯 |
| 蜂鸣提示 | `beep=true` | "滴"一声；脚本默认开启 |
| 空气净化 | `purifier=true` | 净化功能 |

```bash
# 组合示例：开机 + 26.5°C + 高风 + 上下扫风 + 极速制冷
python midea_ac.py control power_state=true target_temperature=26.5 fan_speed=HIGH swing_mode=VERTICAL turbo=true
```

### 2.5 用电数据（App 同款）

| 字段 | 含义 | 说明 |
|------|------|------|
| `total_energy_usage_kwh` | 累计总用电 | 装机以来总数，如 242.88 kWh |
| `current_energy_usage_kwh` | 当前周期用电 | 本机实测恒为 0，参考价值低 |
| `real_time_power_usage_w` | 实时功率 | 单位 W，直读即为真实值 |

**关键发现：**
- 用电数据**不是默认返回的**——必须先设置 `dev.enable_energy_usage_requests = True` 再 `refresh()`，否则读到 `None`。脚本已内置。
- **功率单位就是 W，无需乘 10**（已与 HA 集成 midea_ac_lan 的解析公式交叉验证一致）。变频空调低频运行时几十瓦是正常的，满负荷 ~1400W。
- **看不到每日/每月历史**：设备本地不存历史，App 的用电曲线是美的云端按天归档的。局域网直连只能拿"当前累计值"和"实时功率"。要每日统计需自己定时记录累计值算差值。

---

## 3. Agent 集成要点

### 3.1 脚本调用方式

```bash
# 查询（只读，推荐 Agent 每次操作前先查）
python midea_ac.py query

# 控制（原子操作，一次一个意图）
python midea_ac.py control power_state=true
python midea_ac.py control target_temperature=27
```

### 3.2 执行时序建议

1. **先 query** 拿当前状态（功率、温度、模式）
2. **再 control** 下发变更
3. 脚本控制命令执行后会自动再次 refresh，返回**最新状态**（含用电），无需额外查询

### 3.3 性能表现（实测）

| 场景 | 耗时 |
|------|------|
| 缓存命中查询/控制 | **~1.7-2.3s** |
| 冷启动（无缓存/首次） | ~5.4s |
| 缓存失效自愈（自动回云端重取） | ~5s |

### 3.4 缓存机制

- token/key 与设备 IP 缓存在 `~/.midea-ac/cache.json`（**7 天 TTL**）
- 认证成功后自动写回；认证失败自动清缓存回云端重取
- token **长期有效**（不是网上流传的 1 小时——那是 msm-ng 的连接会话超时，不是 token 寿命；HA 生态配置一次用数月为证）

### 3.5 网络要求

- 与空调同一局域网（UDP 6445 发现 + TCP 6444 控制）
- 设备 IP 会变（DHCP）：单播失败自动转广播重新发现，无需固定 IP
- 云端仅在取 token 时访问（缓存命中时完全离线）

---

## 4. 设备能力参考（本机实测）

以下为 KFR-35GW/N8HA1III-D 实测能力，其他机型以 `query` 返回为准：

| 能力 | 支持 |
|------|------|
| 6 种运行模式 | ✅ AUTO/COOL/DRY/HEAT/FAN_ONLY/SMART_DRY |
| 6 档风速 + 自定义百分比 | ✅ |
| 4 种扫风模式 | ✅ |
| Turbo 极速 | ✅ |
| ECO 节能 | ✅ |
| 睡眠 | ✅ |
| 防冻结 | ✅ |
| 面板灯控制 | ✅ |
| 空气净化 | ✅ |
| 滤网提醒 | ✅（查询型） |
| 用电统计 | ✅（总累计 + 实时功率） |
| 每日用电历史 | ❌（在云端，设备不存） |
| 蓝牙业务控制 | ❌（固件忽略第三方帧，仅 WiFi 可用） |
| 新风机/湿度/除湿机扩展 | ❌ 本机无此硬件 |

---

## 5. 常见坑速查

| 现象 | 原因 | 处理 |
|------|------|------|
| 控制后空调关机 | `apply()` 下发缓存默认 power_state=False | 显式 `power_state=true`（脚本已内置） |
| 用电数据全是 None | 未启用能量请求 | 设 `enable_energy_usage_requests=True`（脚本已内置） |
| 功率看着"太小"（几十 W） | 变频低频运行，正常 | 对比 Turbo 满负荷 ~1400W |
| 登录报 `loginId is empty` | 演示账号被限流 | 脚本自动轮换 US/DE/KR 重试 |
| `Device is not capable of aux mode` | 良性警告 | 忽略 |
| 找不到设备 | 不在同一网段 / IP 变了 | 单播失败自动转广播 |

---

## 6. 架构总览

```
Agent / 用户
   │  python midea_ac.py query / control k=v
   ▼
midea_ac.py ──单播发现(0.3s)──→ 空调 UDP 6445
   │  └─ 失败 → 广播兜底
   ├─ 缓存 token/key (~/.midea-ac/cache.json, 7天) ──认证──→ TCP 6444
   │  └─ 失效 → 云端 getToken 重取 (US/DE/KR 演示账号轮换)
   │
   └─ 查询/控制 → JSON 输出（含用电统计）
```

*本文档配套仓库：https://github.com/kunminiya/midea-ac-lan-control*
