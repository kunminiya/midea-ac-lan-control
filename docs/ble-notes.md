# 美的空调 BLE 直连探索记录（为什么部分机型走 LAN）

2026-08 实测：美的 KFR-35GW/N8HA1III-D，BLE 广播 SN `220F4051AC2236`，MAC `A4:2A:26:51:26:A1`。

## 如何确认 BLE 信号属于本机空调（防邻居设备误判）

用户可能质疑"蓝牙信号是邻居家的"（合理：BLE 广播可被任何附近设备收到）。确认归属用 **SN 交叉比对**：

- WiFi 模块上报 SN（`msmart discover` 返回的 `sn` 字段）：`000000512220F4051B3170212236613L`
- BLE 广播 SN：`220F4051AC2236`
- 两者共享 `220F4051` 前缀 —— SN 是美的出厂每台唯一标识，两个无线模块属于同一台设备才会一致
- 附加佐证：广播为厂商数据 0x06A8（`01 + SN14 + MAC逆序 + 00`，美的专用结构）；用广播 SN 重建 advertisData 后握手成功（HKDF+ECDH+AES-128-CCM），SN 若伪造/他人设备则密钥派生必然失败

**用户侧为何从未见蓝牙配对提示**：美的配网流程默认只走 WiFi（App 输 WiFi 密码），蓝牙模块后台静默广播，用途是 App 近距离配网引导/厂商调试/OTA，从不主动弹配对请求。回答"这空调有蓝牙吗"时：硬件有、能握手，但业务层对第三方不响应 → 对用户无实际用途，WiFi 才是可用遥控通道。

## 已确认可行

### GATT 服务（无配对直连）
```
Service 0xFFA0: Write FFA1 (0x08) / Indicate FFA2 (0x20)   ← 会话通道
Service 0xFF80: Write FF81 (0x08) / Indicate FF82 (0x20)
Service 0xFF90: Write FF91 (0x08) / Indicate FF92 (0x20)
```
- 蓝牙可无配对直接连接；广播为厂商数据 0x06A8（`01 + SN14 + ... + MAC逆序 + 00`）

### advertisData 手动重建（关键技巧）
工具（midea-ble-go）要求完整 25 字节广播 payload 才能重建密钥派生输入，但 BlueZ 只给 15 字节。可手动拼：
```
advertisData = 0xAC + SN前8位 + MAC逆序
例: ac3232304634303531a42a265126a1
```
（SN8 和 MAC 逆序都能从 bluetoothctl 的 ManufacturerData 抓包中直接读到。）

### 握手成功
```bash
midea-ble-go handshake A4:2A:26:51:26:A1 --adv ac3232304634303531a42a265126a1
# ✓ 握手成功 (HKDF + ECDH P-256 + AES-128-CCM 全链路验证通过)
```

## 卡点：业务层无响应
| 测试 | 结果 |
|------|------|
| 握手（会话层 t2） | ✅ |
| 状态查询 (0x41) / 控制 (0x40) | ❌ 业务无回包 |
| 三通道全订阅 FFA2/FF82/FF92 | ❌ |
| 写入换 FF81/FF91 | ❌ 连握手都失败（会话只在 FFA0） |

- 空调开/关机都测过，均无响应
- 与 midea-ble-go issue #1「空调没有响应」同症状（作者 2026-07 仍在排查）
- 结论：**该机型固件 BLE 业务层忽略第三方 t3 帧**，属固件兼容问题，非操作错误

## 附：Xiaomi 米家蓝牙温湿度计2 (LYWSD03MMC) 网关要点
- 广播 ServiceData 0xFE95 帧头 `0x58` = **加密**（`0x50` 才是明文）；固件 1.0.0_0110+ 起加密
- 破解两条路：
  1. 刷 ATC/pvvx 第三方固件 → 明文广播（含电量），浏览器 Web Bluetooth 刷机（**iOS 不支持 Web Bluetooth**，需电脑 Chrome/Edge）
  2. 云端提取 bind key（需小米账号），本地解密，保留米家 App 功能
- 监听工具：`bluetoothctl scan on` 抓 ServiceData/ManufacturerData（无需 root），`timeout N bluetoothctl --timeout M scan on` 自动停止
