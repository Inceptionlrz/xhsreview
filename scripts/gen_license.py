"""
激活码生成器（仅开发者侧使用，需妥善保管 license_private_key.pem）

用法：
  python scripts/gen_license.py --machine XXXX-XXXX-XXXX-XXXX --tier day
  python scripts/gen_license.py --machine XXXX-XXXX-XXXX-XXXX --tier month
  python scripts/gen_license.py --machine XXXX-XXXX-XXXX-XXXX --tier permanent
  python scripts/gen_license.py --machine XXXX-XXXX-XXXX-XXXX --tier day --days 3

说明：
  --tier day        试用，默认 1 天（可用 --days 改天数）
  --tier month      月卡，默认 30 天
  --tier permanent  永久（过期字段为 0）
生成的激活码已与本机机器码绑定，换机器无法使用。
"""

import os
import sys
import time
import json
import argparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# 让脚本能 import src.license（复用 TIERS / 编码逻辑）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.license import TIERS, CODE_PREFIX, _canonical, _encode_code, _group  # noqa: E402


KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "license_private_key.pem")


def main():
    ap = argparse.ArgumentParser(description="小红书助手激活码生成器")
    ap.add_argument("--machine", required=True, help="目标机器码（用户在软件内复制）")
    ap.add_argument("--tier", required=True, choices=list(TIERS.keys()), help="档位")
    ap.add_argument("--days", type=int, default=None, help="day/month 自定义天数（覆盖默认）")
    args = ap.parse_args()

    if not os.path.exists(KEY_PATH):
        print(f"[错误] 找不到私钥文件：{KEY_PATH}", file=sys.stderr)
        sys.exit(1)

    tier = args.tier
    if tier == "permanent":
        exp = 0
    else:
        days = args.days if args.days else TIERS[tier]["days"]
        if days <= 0:
            print("[错误] 天数必须为正整数", file=sys.stderr)
            sys.exit(1)
        exp = int(time.time()) + days * 86400

    payload = {
        "v": 1,
        "tier": tier,
        "machine": args.machine.strip().upper(),
        "exp": exp,
        "issued": int(time.time()),
    }

    with open(KEY_PATH, "rb") as f:
        priv = serialization.load_pem_private_key(f.read(), password=None)

    signature = priv.sign(_canonical(payload), padding.PKCS1v15(), hashes.SHA256())
    code = _encode_code(payload, signature)

    print()
    print(f"档位   : {TIERS[tier]['name']}")
    print(f"机器码 : {args.machine.strip().upper()}")
    if exp:
        print(f"过期   : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exp))}")
    else:
        print("过期   : 永久")
    print()
    print("激活码（复制整行给用户）：")
    print(_group(code))
    print()


if __name__ == "__main__":
    main()
