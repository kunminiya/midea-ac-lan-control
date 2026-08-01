---
name: midea-ac-control
description: 美的/华凌空调局域网直连控制（查询+控制，无需真实账号）。核心技巧：msmart-ng 内置演示账号(US/DE/KR)通过 getToken 接口取任意设备的 V3 认证密钥，LAN 6444 直连。BLE 直连在部分机型业务层无响应，LAN 是稳定路线。适用于美的/华凌空调、热水器等 M-Smart 设备。
---

# 美的空调局域网直连控制

## 触发场景
- 用户要远程查询/控制美的或华凌空调（开关、温度、模式、风速、室内外温度）
- BLE 直连握手成功但业务帧无响应（见 references/ble-notes.md）
- 用户不想提供美的账号密码（本方案完全不需要）

## 核心原理（关键发现）

**msmart-ng 内置演示账号可获取任意设备的 V3 认证密钥**：
- `NetHomePlusCloud(region="US"/"DE"/"KR")` 使用内置的 mailinator 演示账号（代码 `CLOUD_CREDENTIALS` 常量）。区域对应：**US=美国（默认）、DE=德国/欧洲、KR=韩国/东南亚**
- `getToken(udpid)` 接口**不校验设备归属**，返回任意设备的 token/key
- 必须用**国际版云端**（默认 mp-prod.appsmb.com）；中国区云端（smartmidea.net）的 getToken 返回 null，且无演示账号（想走中国区必须用真实美居账号，违背免账号初衷）

## 标准流程

1. 环境：`python3 -m venv venv && venv/bin/pip install msmart-ng`（只依赖 msmart-ng）
2. 用 `msmart-ng discover` 或脚本发现设备，拿到 `id`（如 210006740663182）
3. 取 token：`getToken(Security.udpid(id.to_bytes(6, "big")).hex())` — **big 端序**（little 端序的 token 常被设备拒绝，报 `Error packet received`）
4. `dev.authenticate(token, key)` → `dev.refresh()` → 读 `power_state/target_temperature/indoor_temperature/outdoor_temperature/error_code`
5. 控制：改属性后 `dev.apply()`

现成脚本：`scripts/midea_ac.py`（query/control 两个命令，已内置全部安全默认，可直接用）。

## 性能优化（实测，2026-08）

冷启动（无缓存）~5.4s，缓存命中查询 ~1.7s（控制 ~1.8s）。三处关键优化：

| 优化 | 效果 |
|------|------|
| **token/IP 本地缓存** `~/.midea-ac/cache.json`（**7天TTL**，认证成功后自动写回；认证失败自动清缓存回云端重取，自愈~5s） | 跳过云端 getToken 调用，省 2~10s（US 区常被限流重试） |
| **单播发现** `Discover.discover(target=ip, timeout=0.3, discovery_packets=1)` | 替代广播等待 5s，直接查缓存 IP；**发现超时可压到 0.3s 仍稳定**（设备秒回，但 msm-ng 的 discover 是固定 sleep(timeout)，超时值就是等待值） |
| **只取 big 端序 token**（去掉 little 端序循环） | 少一次 getToken + 少一次失败认证 |

**token 有效期修正（2026-08 实测）**：之前以为 token 约 1 小时过期是**错的**——那 1 小时是 msm-ng 库的 `AUTHENTICATION_EXPIRATION`（连接会话超时），不是 token 本身寿命。getToken 每次签发新 token/key，但旧 token 长期有效（HA 生态 midea_ac_lan 几万用户配置一次用数月，无 token 过期抱怨；实测模拟 3 天龄 token 认证仍成功）。缓存 TTL 因此可设 7 天甚至更长，取 token 波动彻底无感。

注意：`auto_connect=True` 反而更慢（3.7s，内部多走完整认证），不要用。广播兜底 `timeout=2, discovery_packets=2`（IP 变了或首次运行时用）。

## 用电统计（2026-08 实测）

N8HA1 III 系列**支持**用电统计（App 里能看到），LAN 协议也能读。关键坑：**能量字段默认读到 None，不代表硬件不支持**——必须显式打开能量请求开关再 refresh：

```python
dev.enable_energy_usage_requests = True   # 默认 False，不开则电量字段全 None
await dev.refresh()
total   = dev.get_total_energy_usage()        # 累计用电 kWh（本机 242.83）
current = dev.get_current_energy_usage()      # 当前周期用电 kWh
power   = dev.get_real_time_power_usage()     # 实时功率 W（16~90W 随压缩机启停波动）
```

- 注意 msm-ng 里**没有** `supports_energy_usage` 属性可探测，别用 `getattr` 判断——直接无条件尝试，不支持的机型 get_* 返回 None，不影响其他字段（脚本已内置 try/except）
- 控制（apply）后建议再 refresh 一次，返回最新状态（脚本已内置）
- 旧版属性名 `total_energy_usage` 等已废弃，用 `get_*_energy_usage()` 方法
- **功率单位验证（重要教训，2026-08 实测）**：`get_real_time_power_usage()` 返回的就是**真实瓦数（W）**，BCD 解析正确，**不要看数值小就自作聪明乘 10**！验证方法：① 与 HA 集成（georgezhao2010/midea_ac_lan 的 `XC1MessageBody.parse_power`）交叉计算同组字节，结果一致；② 开 Turbo 满负荷实测 ~1400W（1.5 匹标称输入功率），完全吻合。16W/89W 是变频空调低频/待机的**真实低功耗**，不是少零。BINARY 格式（`EnergyDataFormat.BINARY`）解析出 8000+W 是垃圾值，**只信 BCD 格式**

## 坑与规避（全部实测）

| 坑 | 规避 |
|----|------|
| **`apply()` 会下发缓存状态，power_state 缓存默认 False → 误关机！** | 控制命令必须显式 `power_state=true`，或脚本默认置 True（脚本已内置） |
| **控制指令空调不响蜂鸣**（`beep` 属性默认 False） | 控制时默认 `beep=true`（脚本已内置，像遥控器一样"滴"一声）；要静音显式 `beep=false` |
| 演示账号限流（`loginId is empty` / `invalidSession`） | US 常被限流；**DE/KR 相对稳定**；三个区轮换 + 重试（脚本已内置） |
| V2/V3 发现包波动：关机回 `5a5a`(V2)、开机回 `8370`(V3)，msmart 按 IP 去重先到先得 | 分类结果不稳定，但**强制走 V3 云端认证即可**，与发现分类无关 |
| 中国区云 getToken 返回 null | 用国际版云端（默认即可），不用 smartmidea.net |
| 设备 IP 会变（DHCP） | 每次运行重新发现，不写死 IP |
| `Device is not capable of aux mode` 警告 | 良性，不影响控制 |
| token 有效期曾被误记为"约1小时" | 实测**长期有效**（HA 生态数月不刷新）；缓存 `~/.midea-ac/cache.json` 7天TTL，认证失败自动清缓存回云端重取（见性能优化） |
| 用户质疑"蓝牙是邻居家的"（BLE 广播谁都能收到） | SN 交叉比对确认归属：WiFi 模块 `sn` 字段与 BLE 广播 SN 共享前缀即同一台（见 references/ble-notes.md） |
| **能量字段读到 None 就下结论"硬件不支持用电统计"** | ❌ 错误推理！None 只是因为 `enable_energy_usage_requests` 默认关闭；先 `dev.enable_energy_usage_requests=True` 再 refresh 就能读到（见上方"用电统计"节）。App 里有此功能 = LAN 大概率也能读 |
| **实时功率数值"太小"就猜单位 bug、乘 10 修正** | ❌ 变频空调低频/待机 16~90W 是真实值；乘 10 会得出 Turbo 满负荷 14 万 W 的荒谬值。改单位前先交叉验证（HA 解析公式 + Turbo 满负荷实测 ~1400W），见用电统计节 |

## 已验证设备
- 美的 KFR-35GW/N8HA1III-D（1.5匹 N8HA1 III 系列）：查询+控制全通，**用电统计可用**（累计242.83 kWh、实时功率16~90W）
- 同账号云设备列表里还有电热水器（type 0xE2），同方案应可扩展

## 验证方法
```bash
python midea_ac.py query
# {"power": true, "mode": "COOL", "target_temperature": 26.0, "indoor_temperature": 29.3,
#  "total_energy_usage_kwh": 242.83, "current_energy_usage_kwh": 0.0, "real_time_power_usage_w": 16.0, ...}
python midea_ac.py control target_temperature=28   # 改温，自动保持开机，返回含用电
```

## 相关参考
- `references/ble-notes.md` — BLE 直连完整探索（为什么部分机型走 LAN）+ SN 交叉比对确认设备归属（邻居误判排查）
- `scripts/midea_ac.py` — 可直接运行的控制脚本（含 token/IP 缓存加速）
- 上游：mill1000/midea-msmart（msmart-ng）、georgezhao2010/midea_ac_lan（HA 集成，云端细节参考）
- 已发布经验仓库：kunminiya 的 midea-ac-lan-control（含 README/docs/ble-notes.md）
