#!/usr/bin/env python3
"""index.json.sig: the Ed25519 signature (RFC 8032) t-code checks before it trusts index.json.

    tools/sign_index.py --new-key KEY   make a signing key (keep it off GitHub), print its public key
    tools/sign_index.py KEY             sign index.json into index.json.sig (after tools/build_index.py)
    tools/sign_index.py --check         fail when index.json.sig is not PUBLIC_KEY's over index.json (CI)

KEY holds the key's 32-byte seed in base64; PUBLIC_KEY (in this repository) and t-code's
REGISTRY_PUBLIC_KEY hold the public key in base64. index.json.sig holds the 64-byte signature in base64.
Plain Python, no packages: slow (about a second), which does not matter for one file.
"""
import base64
import hashlib
import os
import pathlib
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _sha512_int(data):
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _add(a, b):
    """Points in extended coordinates (X, Y, Z, T)."""
    e1 = (a[1] - a[0]) * (b[1] - b[0]) % P
    e2 = (a[1] + a[0]) * (b[1] + b[0]) % P
    e3 = 2 * a[3] * b[3] * D % P
    e4 = 2 * a[2] * b[2] % P
    e, f, g, h = e2 - e1, e4 - e3, e4 + e3, e2 + e1
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _multiply(s, point):
    result = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            result = _add(result, point)
        point = _add(point, point)
        s >>= 1
    return result


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    return P - x if (x & 1) != sign else x


_GY = 4 * pow(5, P - 2, P) % P
_GX = _recover_x(_GY, 0)
BASE = (_GX, _GY, 1, _GX * _GY % P)


def _compress(point):
    zinv = pow(point[2], P - 2, P)
    x, y = point[0] * zinv % P, point[1] * zinv % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    a, _ = _expand(seed)
    return _compress(_multiply(a, BASE))


def sign(seed, message):
    a, prefix = _expand(seed)
    key = _compress(_multiply(a, BASE))
    r = _sha512_int(prefix + message) % L
    big_r = _compress(_multiply(r, BASE))
    h = _sha512_int(big_r + key + message) % L
    return big_r + ((r + h * a) % L).to_bytes(32, "little")


def verify(key, message, signature):
    if len(signature) != 64:
        return False
    a, r = _decompress(key), _decompress(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a is None or r is None or s >= L:
        return False
    h = _sha512_int(signature[:32] + key + message) % L
    return _equal(_multiply(s, BASE), _add(r, _multiply(h, a)))


def _read_b64(path, size):
    data = base64.b64decode(pathlib.Path(path).read_text().strip(), validate=True)
    if len(data) != size:
        raise ValueError(f"{path}: {size} bytes expected, {len(data)} found")
    return data


def main(argv):
    if argv[:1] == ["--new-key"] and len(argv) == 2:
        path = pathlib.Path(argv[1])
        if path.exists():
            sys.exit(f"{path} is there already: not overwriting a signing key")
        seed = secrets.token_bytes(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(base64.b64encode(seed).decode() + "\n")
        print(base64.b64encode(public_key(seed)).decode())
    elif argv == ["--check"]:
        key = _read_b64(ROOT / "PUBLIC_KEY", 32)
        signature_file = ROOT / "index.json.sig"
        if not signature_file.exists():
            sys.exit("index.json.sig is missing: a maintainer runs tools/sign_index.py KEY and commits it")
        if not verify(key, (ROOT / "index.json").read_bytes(), _read_b64(signature_file, 64)):
            sys.exit("index.json.sig does not match index.json: a maintainer signs it again (tools/sign_index.py KEY)")
        print("index.json.sig is good")
    elif len(argv) == 1 and not argv[0].startswith("-"):
        seed = _read_b64(argv[0], 32)
        key = _read_b64(ROOT / "PUBLIC_KEY", 32)
        if public_key(seed) != key:
            sys.exit(f"{argv[0]} is not the key of PUBLIC_KEY")
        signature = sign(seed, (ROOT / "index.json").read_bytes())
        (ROOT / "index.json.sig").write_text(base64.b64encode(signature).decode() + "\n")
        print("index.json.sig written")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
