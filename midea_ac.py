#!/usr/bin/env python3
"""美的空调直连工具 — V3 云端取 token + LAN 控制

原理: msm.. 内置的演示云端账号(US区)可通过 getToken 接口获取任意设备的
      V3 认证 token/key，无需设备归属账号。之后走局域网 6444 端口直连。

用法:
  midea_ac.py query                # 查询状态 (只读)
  midea_ac.py control k=v k=v ...  # 控制 (如 power_state=true target_temperature=26)
"""
import asyncio
import json
import sys

from msmart.cloud import NetHomePlusCloud
from msmart.const import DeviceType
from msmart.discover import Discover
from msmart.lan import Security

RETRIES = 4


async def get_tokens(device_id: int) -> list[tuple[str, str]]:
    """国际版云端登录 + getToken 取 V3 认证用的 token/key 对。
    三个内置演示账号(US/DE/KR)轮换，避免共享账号限流。"""
    results: list[tuple[str, str]] = []
    for region in ("US", "DE", "KR"):
        cloud = NetHomePlusCloud(region=region)
        logged_in = False
        for attempt in range(3):
            try:
                await cloud.login()
                logged_in = True
                break
            except Exception as e:  # noqa: BLE001
                print(f"[{region}] 第{attempt + 1}次登录失败: {str(e)[:60]}", file=sys.stderr)
                await asyncio.sleep(3)
        if not logged_in:
            continue
        print(f"[{region}] 演示账号登录成功", file=sys.stderr)
        for endian in ("little", "big"):
            udpid = Security.udpid(device_id.to_bytes(6, endian)).hex()
            try:
                token, key = await cloud.get_token(udpid)
                results.append((token, key))
            except Exception as e:  # noqa: BLE001
                print(f"getToken({region},{endian}) 失败: {str(e)[:60]}", file=sys.stderr)
        if results:
            break
    return results


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


async def find_ac() -> object | None:
    for attempt in range(RETRIES):
        try:
            devices = await Discover.discover(timeout=5, auto_connect=False)
        except Exception as e:  # noqa: BLE001
            print(f"[{attempt}] discover异常: {e}", file=sys.stderr)
            continue
        for d in devices:
            if d.type == DeviceType.AIR_CONDITIONER:
                print(
                    f"[{attempt}] 发现空调 ip={d.ip} id={d.id} version={getattr(d, 'version', None)}",
                    file=sys.stderr,
                )
                return d
        print(f"[{attempt}] 未发现空调(共{len(devices)}台)，重试…", file=sys.stderr)
    return None


async def main() -> None:
    dev = await find_ac()
    if dev is None:
        print("ERROR: 重试%d次仍未发现空调" % RETRIES, file=sys.stderr)
        sys.exit(1)

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
    if not auth_ok:
        print("ERROR: 认证失败", file=sys.stderr)
        sys.exit(1)

    await dev.refresh()

    if len(sys.argv) > 1 and sys.argv[1] == "control":
        kwargs = sys.argv[2:]
        # 安全默认: 未显式指定 power_state 时保持开机，
        # 避免 apply() 用缓存默认值(False)把空调误关
        if not any(kv.startswith("power_state=") for kv in kwargs):
            dev.power_state = True
            print("默认 power_state = True (防止误关机)", file=sys.stderr)
        for kv in kwargs:
            name, _, value = kv.partition("=")
            setattr(dev, name, parse_value(name, value, dev))
            print(f"设置 {name} = {getattr(dev, name)!r}", file=sys.stderr)
        await dev.apply()

    state = {
        "power": dev.power_state,
        "mode": dev.operational_mode.name if dev.operational_mode is not None else None,
        "fan_speed": dev.fan_speed.name if dev.fan_speed is not None else None,
        "target_temperature": dev.target_temperature,
        "indoor_temperature": dev.indoor_temperature,
        "outdoor_temperature": dev.outdoor_temperature,
        "error_code": dev.error_code,
    }
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
