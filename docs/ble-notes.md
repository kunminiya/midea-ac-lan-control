# BLE 直连方案探索记录（为什么最终走 LAN）

本文记录对美的空调 BLE 直连的完整排障过程，供遇到同类问题的朋友参考。

## 设备

- 空调：美的 KFR-35GW/N8HA1III-D（1.5匹 N8HA1 III 系列）
- 蓝牙模块广播 SN：`220F4051AC2236`，MAC `A4:2A:26:51:26:A1`

## 已确认可行的事

### GATT 服务结构（无需配对即可连接）

```
Service 0xFFA0:  Write FFA1 (0x08) / Indicate FFA2 (0x20)
Service 0xFF80:  Write FF81 (0x08) / Indicate FF82 (0x20)
Service 0xFF90:  Write FF91 (0x08) / Indicate FF92 (0x20)
```

- 蓝牙可**无配对直接连接**
- 广播内容为厂商数据 `0x06A8`：`0x01 + SN14 + ... + MAC(逆序) + 0x00`
- **advertisData（密钥派生输入）可手动重建**（无需完整 25 字节广播包）：
  ```
  advertisData = 0xAC + SN前8位 + MAC逆序
  例: ac3232304634303531a42a265126a1
  ```

### 握手成功

使用 [midea-ble-go](https://github.com/sorinyang/midea-ble-go) 手动指定 `--adv` 后握手成功：

```bash
midea-ble-go handshake A4:2A:26:51:26:A1 --adv ac3232304634303531a42a265126a1
# ✓ 握手成功 (C1→C2→C3, HKDF + ECDH P-256 + AES-128-CCM 全部验证通过)
```

## 卡住的地方：业务层无响应

| 测试 | 结果 |
|------|------|
| 握手（会话层） | ✅ 成功 |
| 状态查询 (opcode 0x41) | ❌ 业务无回包 |
| 控制命令 (opcode 0x40) | ❌ 业务无回包 |
| 三通道全订阅 (FFA2/FF82/FF92) | ❌ 仍无回包 |
| 写入通道换 FF81/FF91 | ❌ 连握手都失败（确认会话通道只有 FFA0） |

- 空调开机/关机状态都测试过，均无响应
- 与 [midea-ble-go issue #1](https://github.com/sorinyang/midea-ble-go/issues/1)（"空调没有响应"）完全同症状，作者仍在排查
- 结论：**该机型固件的 BLE 业务层（t3/sessionKey 加密帧）不响应第三方实现**，可能是固件兼容问题

## 结论

- BLE 直连在**会话层完全可行**（握手/加密链路都对），但**业务帧被设备忽略**
- 同款机型的用户建议直接走 **LAN 方案**（见仓库 README）：稳定、功能全（查询+控制）、无需账号

## 附：midea-ble-go 的补丁尝试

为排查"业务回复走其他通道"的假设，对 midea-ble-go 做了三通道全订阅补丁（`internal/ble/ble.go` 支持 `MIDEA_WRITE_PREFIX` / `MIDEA_NOTIFY_PREFIXES` 环境变量），实测三通道均无业务回复，证明问题不在订阅遗漏，而是设备固件本身不响应。补丁可作通用调试工具保留。
