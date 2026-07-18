"""
激活码 / 机器码 授权模块

设计要点：
- 机器码：由本机硬件指纹（CPU / 主板 / BIOS / 磁盘序列号 / 首张网卡 MAC）
  组合后 SHA-256 取前 16 位，格式 XXXX-XXXX-XXXX-XXXX。稳定且跨重启不变。
- 激活码：RSA 非对称签名（私钥只在 gen_license.py 生成器侧，公钥内置本模块）。
  激活码内嵌 machine（机器码）+ tier（档位）+ exp（过期时间戳，0=永久）。
  换机器 / 过期 / 篡改签名 → 校验失败，避免重复使用与伪造。

档位：
  day      试用 1 天
  month    月卡 30 天
  permanent 永久
"""

import os
import re
import json
import time
import base64
import socket
import hashlib
import subprocess
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ============== 内置公钥（仅用于验签，无法伪造激活码） ==============
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwf3nvH/SjskrFMKr+DNl
558SogjDMotnBxt56mPFXUQzbss8iCwbksj2Dl7JgrWu+GZW4huHRD2MKQPJk17I
FG2wKxDEBDT2rTlBjmF1061zkeLn3foR+YEQmxK2QL+YKMhR8vU0BhSV/rIjNZvw
6tgHJ08+iYJbrZxleZbe+GMFEjqWiEM+NIxX9AWOPZR/9tHozvLqhV47l2UFJE8H
Fpmh0qv97LikisQk0QS5AywutlF/L78sFh5pmTCWD0TD3WoS03UiYjSlf5iqWlIO
dtP7XOyW1TCduOq+3FKGnGFjOq6sMiZtrEXq/xK0SpZCE68nD6on+tkcITLbLHye
fwIDAQAB
-----END PUBLIC KEY-----
"""

# 激活码前缀（版本标识）
CODE_PREFIX = "XHS1"

# 档位定义
TIERS = {
    "day":       {"name": "试用",  "days": 1},
    "month":     {"name": "月卡",  "days": 30},
    "permanent": {"name": "永久",  "days": 0},
}


# ============== 机器码 ==============
def _wmic_value(cmd: str) -> str:
    """执行 wmic 命令，返回去掉表头后的首个非空值（稳定硬件序列）。"""
    try:
        out = subprocess.check_output(
            cmd, shell=True, stderr=subprocess.DEVNULL, timeout=5
        ).decode("gbk", errors="ignore")
    except Exception:
        return ""
    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low in ("processoid", "serialnumber", "uuid", "processid"):
            continue  # 表头行
        return s
    return ""


def get_machine_code() -> str:
    """生成本机机器码（硬件指纹哈希），跨重启稳定。"""
    seeds = []
    for cmd in (
        "wmic cpu get ProcessorId",
        "wmic baseboard get SerialNumber",
        "wmic bios get SerialNumber",
        "wmic diskdrive get SerialNumber",
    ):
        v = _wmic_value(cmd)
        if v:
            seeds.append(v)

    # 首张物理网卡 MAC
    try:
        out = subprocess.check_output(
            "getmac", shell=True, stderr=subprocess.DEVNULL, timeout=5
        ).decode("gbk", errors="ignore")
        for line in out.splitlines():
            line = line.strip()
            if re.match(r"^([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}", line):
                seeds.append(line.split()[0])
                break
    except Exception:
        pass

    raw = "|".join(seeds)
    if not raw:
        # 极端兜底：hostname（不稳定，仅当所有硬件不可读时）
        raw = "fallback:" + socket.gethostname()

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


# ============== 激活码编解码 ==============
def _canonical(payload: dict) -> bytes:
    """稳定的规范化序列化，用于签名与验签（生成器/校验必须一致）。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_code(payload: dict, signature: bytes) -> str:
    # 使用标准 base64（字母表不含 '-'，便于用 '-' 做分组展示分隔符且 normalize 安全）
    body = (
        base64.b64encode(_canonical(payload)).decode()
        + "."
        + base64.b64encode(signature).decode()
    )
    return CODE_PREFIX + body


def _normalize_input(text: str) -> str:
    """用户输入清洗：去空白、去连字符、转大写前缀。"""
    s = text.strip().replace(" ", "").replace("\r", "").replace("\n", "").replace("\t", "")
    s = s.replace("-", "")
    return s


def _b64d(s: str) -> bytes:
    """base64 解码（按长度补正确数量的 '='，避免过度填充截断）。"""
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def _group(code: str, size: int = 4) -> str:
    """把连续激活码按 size 分组，便于展示/复制。"""
    return "-".join(code[i:i + size] for i in range(0, len(code), size))


# ============== 校验结果 ==============
@dataclass
class LicenseInfo:
    valid: bool
    tier: Optional[str] = None
    machine: Optional[str] = None
    expires_at: int = 0          # 0 = 永久
    issued_at: int = 0
    message: str = ""

    @property
    def tier_name(self) -> str:
        if self.tier and self.tier in TIERS:
            return TIERS[self.tier]["name"]
        return "-"

    @property
    def is_permanent(self) -> bool:
        return self.expires_at == 0

    def status_text(self) -> str:
        """用于 GUI 展示的授权状态文案。"""
        if not self.valid:
            return "未激活"
        if self.is_permanent:
            return f"{self.tier_name}"
        exp_str = time.strftime("%Y-%m-%d", time.localtime(self.expires_at))
        return f"{self.tier_name} 至 {exp_str}"


# ============== 校验 ==============
def verify_license(code: str) -> LicenseInfo:
    """校验激活码：签名 → 机器绑定 → 过期。返回 LicenseInfo。"""
    norm = _normalize_input(code)
    if not norm.startswith(CODE_PREFIX):
        return LicenseInfo(valid=False, message="激活码格式不正确")
    body = norm[len(CODE_PREFIX):]
    if "." not in body:
        return LicenseInfo(valid=False, message="激活码格式不正确")
    b64p, b64s = body.split(".", 1)
    try:
        payload = json.loads(_b64d(b64p).decode("utf-8"))
        signature = _b64d(b64s)
    except Exception:
        return LicenseInfo(valid=False, message="激活码解析失败")

    # 1) 验签
    try:
        pub = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
        pub.verify(signature, _canonical(payload), padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        return LicenseInfo(valid=False, message="激活码签名无效（可能被篡改）")

    tier = payload.get("tier")
    machine = payload.get("machine", "")
    expires_at = int(payload.get("exp", 0) or 0)
    issued_at = int(payload.get("issued", 0) or 0)

    # 2) 机器绑定
    current = get_machine_code()
    if machine != current:
        return LicenseInfo(
            valid=False, tier=tier, machine=machine,
            expires_at=expires_at, issued_at=issued_at,
            message="激活码与本机不匹配（已绑定其他机器）",
        )

    # 3) 过期
    if expires_at and expires_at < int(time.time()):
        return LicenseInfo(
            valid=False, tier=tier, machine=machine,
            expires_at=expires_at, issued_at=issued_at,
            message="激活码已过期",
        )

    return LicenseInfo(
        valid=True, tier=tier, machine=current,
        expires_at=expires_at, issued_at=issued_at, message="OK",
    )


# ============== 本地持久化（记住已激活的码） ==============
def _license_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "config", "license.json")


def load_saved_code() -> Optional[str]:
    p = _license_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("code")
    except Exception:
        return None


def save_code(code: str) -> bool:
    p = _license_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"code": code, "activated_at": int(time.time())}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def clear_saved_code() -> None:
    p = _license_path()
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def grouped_display(code: str) -> str:
    """把保存的原始码转成分组展示串（用于对话框回显）。"""
    return _group(_normalize_input(code))
