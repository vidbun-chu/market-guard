#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
publish_via_api.py — 绕过 git 协议，用 GitHub REST API 直接发布
================================================================================
为什么需要这个脚本：
    git push 走 github.com 主站，本机主站不通（代理失效/未放行），
    但 api.github.com 直连可用（HTTP 200）。因此全程改走 REST API。

关键坑（已踩）:
    Contents API（PUT /contents/{path}）在**空仓库**上无法创建首个 commit ——
    会返回 404 "This repository is empty."，因为它要求目标分支已存在。
    正确做法：先用 Git Data API 建 blob → tree → commit → ref 打通分支，
    之后才能用 Contents API 逐文件更新。

本脚本采用两步法：
    第 1 步（仅空仓库时）：Git Data API 建分支 + 一次性提交全部文件
    第 2 步（增量更新）  ：Contents API 逐文件 PUT（带 sha 覆盖）

用法：
    GH_TOKEN=xxx python publish_via_api.py
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("GH_TOKEN")
if not TOKEN:
    sys.exit("✗ 请先设置 GH_TOKEN 环境变量")

REPO = os.environ.get("GH_REPO", "vidbun-chu/market-guard")
API = f"https://api.github.com/repos/{REPO}"
BRANCH = "main"
SKIP_DIRS = {".git", "__pycache__", "dist", "build", ".eggs", "market_guard.egg-info"}
DELAY = 0.07

# 强制不走代理（本机代理已失效且未放行 githubusercontent）
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def req(method, url, data=None, retries=3, allow_empty=False):
    """allow_empty: 把"仓库为空/对象不存在"类响应视为 None。
    注意 GitHub 对空仓库返回 409 Conflict（而非 404）：
      GET /git/ref/heads/main → 409 "Git Repository is empty."
      GET /contents/{path}    → 404 "This repository is empty."
    两种都表示"需要走 bootstrap 路径"。
    """
    hdr = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "market-guard-publisher",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdr["Content-Type"] = "application/json"

    for attempt in range(1, retries + 1):
        try:
            r = urllib.request.Request(url, data=body, headers=hdr, method=method)
            with _opener.open(r, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            code = e.code
            detail = ""
            try:
                detail = json.loads(e.read().decode()).get("message", "")
            except Exception:
                pass
            if allow_empty and (code == 404 or
                               (code == 409 and "empty" in detail.lower())):
                return None
            if code in (502, 503, 504) and attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            raise RuntimeError(f"HTTP {code} {method} {urllib.parse.urlparse(url).path[:70]} {detail}")
        except Exception:
            if attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            raise


def collect_files():
    out = []
    base = os.path.dirname(os.path.abspath(__file__))
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if n.endswith((".pyc", ".pyo")) or n == ".DS_Store":
                continue
            p = os.path.join(root, n)
            rel = os.path.relpath(p, base).replace("\\", "/")
            out.append((rel, p))
    return sorted(out)


def bootstrap_via_git_data(files):
    """建初始 commit 并一次性提交全部文件。

    ⚠️ 已踩的坑（GitHub 对空仓库的限制）：
      空仓库上 **任何** Git Data 端点（POST /git/blobs、/git/trees、
      /git/commits、/git/refs）都返回 409 "Git Repository is empty."。
      解决办法：先用 Contents API 放一个种子文件（如 README.md）建出
      首个 commit 把分支打通，之后 Git Data API 才可用。
      （repo PUT 的 auto_init 端点已废弃，不再返回 404，故不能用。）
    """
    print("空仓库 → 先建种子 commit，再走 Git Data API")

    # ① 种子文件打通分支
    readme = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")
    with open(readme, "rb") as f:
        seed_b64 = base64.b64encode(f.read()).decode()
    req("PUT", f"{API}/contents/.seed", {
        "message": "chore: init (seed)",
        "content": seed_b64,
        "branch": BRANCH,
    })
    print("✓ 种子 commit 已建，分支已打通")
    time.sleep(DELAY)

    # ② 全部文件走 blob → tree → commit
    entries = []
    for i, (rel, path) in enumerate(files, 1):
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        blob = req("POST", f"{API}/git/blobs", {"content": b64, "encoding": "base64"})
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  blob [{i:2d}/{len(files)}] {rel}")
        time.sleep(DELAY)

    tree = req("POST", f"{API}/git/trees", {"tree": entries})
    print(f"✓ tree 已建：{tree['sha'][:8]}")

    commit = req("POST", f"{API}/git/commits", {
        "message": "feat: market_guard v1.0.0 首个版本\n\n"
                   "账户级风控与趋势工具包，零第三方依赖（仅标准库）。\n\n"
                   "模块：\n"
                   "- datafeed   多源容错行情抓取（腾讯/新浪/东财自动回退）\n"
                   "- indicators 趋势引擎（体系均线 + 月线阶段判定）\n"
                   "- stoploss   市值止损三轨制（百分比/结构/速率）\n"
                   "- cycle      大周期定性三问（不使用比值定档）\n"
                   "- radar      账户级风险雷达，输出可执行减仓清单\n\n"
                   "工程：24 个零网络单元测试；CI 三平台矩阵；PyPI OIDC 发布；完整脱敏。",
        "tree": tree["sha"],
    })
    print(f"✓ commit 已建：{commit['sha'][:8]}")

    # 更新分支指向
    ref = req("PATCH", f"{API}/git/refs/heads/{BRANCH}", {"sha": commit["sha"], "force": True})
    print(f"✓ 分支已更新：{BRANCH} → {ref['object']['sha'][:8]}")

    # 清理种子文件
    try:
        seed = req("GET", f"{API}/contents/.seed?ref={BRANCH}", allow_empty=True)
        if seed and seed.get("sha"):
            req("DELETE", f"{API}/contents/.seed", {"sha": seed["sha"], "branch": BRANCH})
            print("✓ 种子文件已清理")
    except Exception as e:
        print(f"! 种子清理失败（不影响功能）：{e}")


def main():
    print(f"目标仓库：{REPO}")
    user = req("GET", "https://api.github.com/user")
    print(f"认证账号：{user['login']}")

    files = collect_files()
    print(f"待上传 {len(files)} 个文件\n")

    # 判断分支是否已存在
    ref = req("GET", f"{API}/git/ref/heads/{BRANCH}", allow_empty=True)

    if ref is None:
        bootstrap_via_git_data(files)
        print(f"\n✓ 发布完成：https://github.com/{REPO}")
        return 0

    print(f"分支 {BRANCH} 已存在，逐文件更新\n")
    ok = fail = 0
    for i, (rel, path) in enumerate(files, 1):
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        quoted = urllib.parse.quote(rel)
        try:
            existing = req("GET", f"{API}/contents/{quoted}?ref={BRANCH}", allow_empty=True)
            payload = {"message": f"chore: 更新 {rel}", "content": b64, "branch": BRANCH}
            if existing and existing.get("sha"):
                payload["sha"] = existing["sha"]
            req("PUT", f"{API}/contents/{quoted}", payload)
            ok += 1
            print(f"  [{i:2d}/{len(files)}] ✓ {rel}")
        except Exception as e:
            fail += 1
            print(f"  [{i:2d}/{len(files)}] ✗ {rel} → {e}")
        time.sleep(DELAY)

    print(f"\n结果：成功 {ok}，失败 {fail}")
    if fail:
        return 1
    print(f"✓ 发布完成：https://github.com/{REPO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
