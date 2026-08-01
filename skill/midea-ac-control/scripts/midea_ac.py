#!/usr/bin/env python3
"""美的空调直连工具 — V3 云端取 token + LAN 控制（带本地缓存加速）

原理: msm.. 内置的演示云端账号(US/DE/KR区)可通过 getToken 接口获取任意设备的
      V3 认证 token/key，无需设备归属账号。之后走局域网 6444 端口直连。

加速: token/key 与设备 IP 缓存在 ~/.midea-ac/cache.json（约50分钟有效），
      命中时跳过云端调用，单播发现 + 直连认证，总耗时 ~2.5s。

用法:
  midea_ac.py query                # 查询状态 (只读)
  midea_ac.py control k=v k=v ...  # 控制 (如 power_state=true target_temperature=26)
"""
import asyncio
import json
import os
import sys
import time
from typing import Any

from msmart.cloud import NetHomePlusCloud
from msmart.const import DeviceType
from msmart.discover import Discover
from msmart.lan import Security

RETRIES = 4
DEVICE_ID = 210006740663182  # 已确认的空调 id（发现失败时兜底用）
CACHE_FILE = os.path.expanduser("~/.midea-ac/cache.json")
CACHE_TTL = 7 * 24 * 3600  # token 长期有效(HA生态实践:配置一次用数月)，7天保守缓存


def load_cache() -> dict | None:
    try:
        with open(CACHE_FILE) as f:
            c = json.load(f)
        if time.time() - c.get("ts", 0) < CACHE_TTL:
            return c
    except (OSError, json.JSONDecodeError):
        pass
    return None


def save_cache(ip: str, device_id: int, token: str, key: str) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump({"ip": ip, "device_id": device_id, "token": token,
                   "key": key, "ts": time.time()}, f)


async def get_tokens(device_id: int) -> list[tuple[str, str]]:
    """国际版云端登录 + getToken 取 V3 认证 token/key 对。
    优先用本地缓存（50分钟内）；否则轮换 US/DE/KR 演示账号。
    只取 big 端序 udpid（little 端序的 token 常被设备拒绝）。"""
    # 1) 缓存命中直接复用
    cache = load_cache()
    if cache and cache.get("device_id") == device_id:
        print(f"[缓存] 复用 token (剩余{int(CACHE_TTL - (time.time() - cache['ts'])) // 60}分钟)",
              file=sys.stderr)
        return [(cache["token"], cache["key"])]

    # 2) 云端获取
    for region in ("US", "DE", "KR"):
        cloud = NetHomePlusCloud(region=region)
        logged_in = False
        for attempt in range(2):
            try:
                await cloud.login()
                logged_in = True
                break
            except Exception as e:  # noqa: BLE001
                print(f"[{region}] 第{attempt + 1}次登录失败: {str(e)[:60]}", file=sys.stderr)
                await asyncio.sleep(1)
        if not logged_in:
            continue
        print(f"[{region}] 演示账号登录成功", file=sys.stderr)
        udpid = Security.udpid(device_id.to_bytes(6, "big")).hex()
        try:
            token, key = await cloud.get_token(udpid)
            return [(token, key)]
        except Exception as e:  # noqa: BLE001
            print(f"getToken({region}) 失败: {str(e)[:60]}", file=sys.stderr)
    return []


def parse_value(name: str, value: str, dev: object):
    attr_value = getattr(dev, name)
    attr_type = type(attr_value)
    if isinstance(attr_value, bool):
        return value.strip().lower() in ("true", "1", "on", "yes")
    if hasattr(attr_value, "name"):  # MideaIntEnum
        return attr_type[value.strip().upper()]
    if isinstance(attr_value, (int, float)):
        v = float(value) if "." in value else int(value)
        return attr_type(v)
    return attr_type(value)


async def find_ac(ip: str | None = None) -> Any | None:
    """发现空调。优先单播直查缓存 IP（1.5s），失败再广播（兜底）。"""
    if ip:
        try:
            devices = await Discover.discover(target=ip, timeout=0.3,
                                              discovery_packets=1, auto_connect=False)
            for d in devices:
                if d.type == DeviceType.AIR_CONDITIONER:
                    print(f"[单播] 发现空调 ip={d.ip} id={d.id}", file=sys.stderr)
                    return d
        except Exception as e:  # noqa: BLE001
            print(f"[单播] 发现异常: {e}", file=sys.stderr)
        print(f"[单播] IP {ip} 未响应，转广播…", file=sys.stderr)

    for attempt in range(RETRIES):
        try:
            devices = await Discover.discover(timeout=2, discovery_packets=2,
                                              auto_connect=False)
        except Exception as e:  # noqa: BLE001
            print(f"[{attempt}] discover异常: {e}", file=sys.stderr)
            continue
        for d in devices:
            if d.type == DeviceType.AIR_CONDITIONER:
                print(f"[广播] 发现空调 ip={d.ip} id={d.id} version={getattr(d, 'version', None)}",
                      file=sys.stderr)
                return d
        print(f"[{attempt}] 未发现空调(共{len(devices)}台)，重试…", file=sys.stderr)
    return None


async def main() -> None:
    cache = load_cache()
    dev = await find_ac(cache.get("ip") if cache else None)
    if dev is None:
        print("ERROR: 重试%d次仍未发现空调" % RETRIES, file=sys.stderr)
        sys.exit(1)

    # 优先用缓存 token 认证；失败则清缓存回云端重新获取，再认证一次
    tokens = []
    if cache:
        tokens = [(cache["token"], cache["key"])]

    if not tokens:
        tokens = await get_tokens(dev.id)
        if not tokens:
            print("ERROR: 云端取token失败", file=sys.stderr)
            sys.exit(1)

    auth_ok = False
    for token, key in tokens:
        try:
            await dev.authenticate(token, key)
            auth_ok = True
            print(f"认证成功 (token={token[:8]}…)", file=sys.stderr)
            break
        except Exception as e:  # noqa: BLE001
            print(f"认证失败: {str(e)[:80]}", file=sys.stderr)

    # 缓存 token 失效 → 清缓存、云端重取、重新认证
    if not auth_ok and cache:
        print("缓存 token 失效，回云端重新获取…", file=sys.stderr)
        os.remove(CACHE_FILE)
        fresh = await get_tokens(dev.id)
        for token, key in fresh:
            try:
                await dev.authenticate(token, key)
                auth_ok = True
                tokens = [(token, key)]
                print(f"云端新 token 认证成功 (token={token[:8]}…)", file=sys.stderr)
                break
            except Exception as e:  # noqa: BLE001
                print(f"重新认证失败: {str(e)[:80]}", file=sys.stderr)

    if not auth_ok:
        print("ERROR: 认证失败", file=sys.stderr)
        sys.exit(1)

    # 认证成功后更新缓存（含 IP，下次直接单播）
    save_cache(dev.ip, dev.id, tokens[0][0], tokens[0][1])

    await dev.refresh()

    if len(sys.argv) > 1 and sys.argv[1] == "control":
        kwargs = sys.argv[2:]
        # 安全默认: 未显式指定 power_state 时保持开机，
        # 避免 apply() 用缓存默认值(False)把空调误关
        if not any(kv.startswith("power_state=") for kv in kwargs):
            dev.power_state = True
            print("默认 power_state = True (防止误关机)", file=sys.stderr)
        # 默认响蜂鸣器(像遥控器一样"滴"一声)；显式 beep=false 可静音
        if not any(kv.startswith("beep=") for kv in kwargs):
            dev.beep = True
            print("默认 beep = True (蜂鸣提示)", file=sys.stderr)
        for kv in kwargs:
            name, _, value = kv.partition("=")
            setattr(dev, name, parse_value(name, value, dev))
            print(f"设置 {name} = {getattr(dev, name)!r}", file=sys.stderr)
        await dev.apply()
        # 控制后再刷新一次，返回最新状态
        await dev.refresh()

    # 用电数据: 需显式启用能量请求(默认关闭，否则读到 None)
    # 实测 N8HA1 III 系列支持；不支持的机型 get_* 返回 None 不影响
    # 单位验证: BCD 解析即真实瓦数(与 HA 集成交叉验证一致; Turbo满负荷1456W合理, 低频89W正常)
    energy = {}
    try:
        dev.enable_energy_usage_requests = True
        await dev.refresh()
        energy = {
            "total_energy_usage_kwh": dev.get_total_energy_usage(),
            "current_energy_usage_kwh": dev.get_current_energy_usage(),
            "real_time_power_usage_w": dev.get_real_time_power_usage(),
        }
    except Exception as e:  # noqa: BLE001
        print(f"用电数据读取失败(忽略): {str(e)[:60]}", file=sys.stderr)

    state = {
        "power": dev.power_state,
        "mode": dev.operational_mode.name if dev.operational_mode is not None else None,
        "fan_speed": dev.fan_speed.name if dev.fan_speed is not None else None,
        "target_temperature": dev.target_temperature,
        "indoor_temperature": dev.indoor_temperature,
        "outdoor_temperature": dev.outdoor_temperature,
        "error_code": dev.error_code,
        **energy,
    }
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
