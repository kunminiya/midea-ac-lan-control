# 美的空调局域网直连控制（无需真实账号）

通过局域网 6444 端口直接查询和控制美的/华凌空调（V3 协议），**不需要你的美的账号密码**。

> 本项目源于一次真实排障：BLE 直连方案（[midea-ble-go](https://github.com/sorinyang/midea-ble-go)）在部分机型上握手成功但业务层无响应（见 [issue #1](https://github.com/sorinyang/midea-ble-go/issues/1)，作者仍在排查），于是转向局域网方案并成功打通。本仓库记录完整经验，供同款设备用户参考。

## 已验证设备

| 设备 | 型号 | 状态 |
|------|------|------|
| 美的空调 1.5匹 | KFR-35GW/N8HA1III-D | ✅ 查询 + 控制全部正常 |

## 工作原理

```
华硕/电脑 ──UDP发现──→ 空调 (广播 6445/20086 端口)
    │
    ├─ 发现包可能是 V2(5a5a) 或 V3(8370) 格式，随设备状态波动
    │
    ├─ 认证: 国际版云端 getToken 接口取 V3 token/key
    │   (msmart-ng 内置演示账号即可，接口不校验设备归属)
    │
    └─ LAN TCP 6444 端口 → V3 认证 → 查询/控制
```

## 关键发现（重点）

### 1. getToken 接口不校验设备归属 🎯

[msmart-ng](https://pypi.org/project/msmart-ng/)（`mill1000/midea-msmart` 的活跃维护分支）内置了三个**演示账号**（US/DE/KR 区的 mailinator 账号，代码里 `CLOUD_CREDENTIALS` 常量）。用它们登录**国际版云端**后，调用 `getToken(udpid)` 接口可以取到**任意设备**的 V3 认证 token/key——接口并不校验设备是否属于该账号。

也就是说：**不需要自己的美的账号**，直接借用演示账号即可完成 V3 认证。

```python
from msmart.cloud import NetHomePlusCloud
from msmart.lan import Security

cloud = NetHomePlusCloud(region="DE")          # 内置演示账号
await cloud.login()
udpid = Security.udpid(device_id.to_bytes(6, "big")).hex()   # 用 big 端序！
token, key = await cloud.get_token(udpid)       # 任意设备都能取
```

### 2. 演示账号限流与选择

- US 演示账号经常被限流（登录报 `loginId is empty` 或 `invalidSession`）
- **DE / KR 账号相对稳定**，脚本会自动轮换重试
- ⚠️ **token 有效期更正（2026-08 实测）**：网上流传的"token 有效期约 1 小时"是**误解**——那是 msm-ng 库的 `AUTHENTICATION_EXPIRATION`（连接会话超时），不是 token 本身寿命。getToken 每次会签发新 token/key，但**旧的依然长期有效**（HA 生态 midea_ac_lan 几万用户配置一次用数月，无过期抱怨；实测模拟 3 天龄 token 认证仍成功）。脚本因此缓存 token 7 天，日常控制完全不需要碰云端。

### 3. udpid 端序注意

- **big 端序**生成的 udpid 取到的 token 认证成功 ✅
- little 端序生成的 udpid 取到的 token 可能被设备拒绝（`Error packet received`）
- 脚本只取 big 端序（省一次云端调用和一次失败认证）

### 4. V2/V3 发现包波动（排障参考）

实测空调的发现响应格式随状态波动：关机时回 V2 格式（`5a5a`），开机时回 V3 格式（`8370`）。msmart-ng 按 IP 去重、**先到先得**，因此分类结果不稳定：

- 分类成 V2 → 走内置默认密钥认证，无需云端
- 分类成 V3 → 走云端 getToken（演示账号即可）

最终方案直接绕过发现分类：任何版本发现后都强制走 V3 云端认证，稳定可靠。

### 5. 控制命令防误关机 ⚠️

`apply()` 会把设备**缓存状态**整体下发。如果只改了 `target_temperature` 而缓存里的 `power_state` 是默认 `False`，空调会被**误关机**。必须显式带上 `power_state=true`（脚本已内置此安全默认）。

### 6. 蜂鸣反馈（2026-08 新增）

控制指令默认带 `beep=true`（和遥控器一样"滴"一声），要静音显式 `beep=false`。

### 7. 性能优化（2026-08 实测）

冷启动 ~5.4s，缓存命中 **~1.7s**（控制 ~1.9s）。三处优化：

| 优化 | 效果 |
|------|------|
| **token/IP 本地缓存** `~/.midea-ac/cache.json`（7天TTL，认证成功后自动写回；认证失败自动清缓存回云端重取，自愈~5s） | 跳过云端 getToken 调用，省 2~10s（US 区常被限流重试） |
| **单播发现** `Discover.discover(target=ip, timeout=0.3, discovery_packets=1)` | 替代广播等待 5s，直接查缓存 IP |
| **只取 big 端序 token** | 少一次 getToken + 少一次失败认证 |

注意：`auto_connect=True` 反而更慢（3.7s，内部多走完整认证），不要用。广播兜底 `timeout=2, discovery_packets=2`（IP 变了或首次运行时用）。

## 安装

```bash
python3 -m venv venv
venv/bin/pip install msmart-ng
```

## 使用

```bash
# 查询状态（只读）
python midea_ac.py query

# 控制：开机 + 制冷 26℃（默认带蜂鸣"滴"一声）
python midea_ac.py control power_state=true target_temperature=26

# 静音控制：加 beep=false
python midea_ac.py control power_state=true target_temperature=26 beep=false

# 只调温度（脚本自动保持开机）
python midea_ac.py control target_temperature=28
```

输出示例：

```json
{"power": true, "mode": "COOL", "fan_speed": "AUTO", "target_temperature": 26.0, "indoor_temperature": 29.3, "outdoor_temperature": 34.5, "error_code": 0}
```

## 常见问题

| 问题 | 解决 |
|------|------|
| `loginId is empty` / `invalidSession` | 演示账号被限流，脚本自动换区重试；多跑几次即可 |
| 找不到设备 | 确认电脑与空调在同一网段；`msmart-ng discover` 手动验证 |
| 设备 IP 变化 | 单播失败自动转广播重新发现，无需配置固定 IP |
| 控制后空调关机 | 必须带 `power_state=true`（脚本已内置） |
| 控制后空调不响 | 脚本默认 `beep=true`；被显式 `beep=false` 覆盖过则恢复默认 |
| 报错 `Device is not capable of aux mode` | 良性警告，不影响控制 |

## 目录说明

- `midea_ac.py` — 直连控制脚本（查询/控制）
- `docs/ble-notes.md` — BLE 直连方案的完整探索记录（为什么走 LAN）

## 免责声明

- 演示账号机制来自 msmart-ng 内置设计，仅用于技术学习与研究
- 局域网直连请在自己的设备上使用，注意网络安全
- 通信协议基于社区逆向工程，非官方实现

## 致谢

- [mill1000/midea-msmart](https://github.com/mill1000/midea-msmart) — msmart-ng 上游
- [sorinyang/midea-ble-go](https://github.com/sorinyang/midea-ble-go) — BLE 方案参考，其未解决的机型问题启发了本仓库的 LAN 路线
- [georgezhao2010/midea_ac_lan](https://github.com/georgezhao2010/midea_ac_lan) — Home Assistant 集成，云端接口细节参考
