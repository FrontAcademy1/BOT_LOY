"""
🏭 AI SOFTWARE FACTORY — Termux/Linux Edition
═══════════════════════════════════════════════════════════════════════
Turn your idea into software — AI LOYAL Edition.

الميزات:
  ✅ Setup Wizard عند أول تشغيل (توكن + ID + ربط AI/n8n)
  ✅ تخزين آمن في ~/.ai-factory/config.json (chmod 600)
  ✅ أوامر باسم AI LOYAL
  ✅ بناء APK عبر GitHub Actions
  ✅ كريدت + مكافآت + لوحة أدمن
  ✅ شفافية كاملة: لا نجاح وهمي

التشغيل:
    python main.py           # يشغّل Setup تلقائيًا لو أول مرة
    python main.py --reset   # يمسح الإعداد ويعيد Setup
"""
from __future__ import annotations

import asyncio
import base64
import getpass
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from telegram import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)

# ══════════════════════════════════════════════════════════════════
# ثوابت عامة
# ══════════════════════════════════════════════════════════════════

APP_NAME = "AI LOYAL FACTORY"
CONFIG_DIR = Path.home() / ".ai-factory"
CONFIG_FILE = CONFIG_DIR / "config.json"

# ألوان الطرفية
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    BLUE = "\033[94m"


def color(text: str, c: str) -> str:
    return f"{c}{text}{C.RESET}"


def banner() -> None:
    print(color("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║        🏭   A I   L O Y A L   F A C T O R Y   🏭             ║
║                                                              ║
║           Turn your idea into software.                      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""", C.CYAN + C.BOLD))


# ══════════════════════════════════════════════════════════════════
# SETUP WIZARD — أول تشغيل
# ══════════════════════════════════════════════════════════════════

def _ask(prompt: str, default: str = "", required: bool = True,
         secret: bool = False) -> str:
    """سؤال تفاعلي مع قيمة افتراضية وتحقق."""
    suffix = f" {color(f'[{default}]', C.DIM)}" if default else ""
    try:
        if secret:
            val = getpass.getpass(f"{color('▸', C.CYAN)} {prompt}{suffix}: ").strip()
        else:
            val = input(f"{color('▸', C.CYAN)} {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print(color("\n\nتم الإلغاء.", C.RED))
        sys.exit(1)

    if not val:
        val = default
    if required and not val:
        print(color("  ✗ هذا الحقل مطلوب.", C.RED))
        return _ask(prompt, default, required, secret)
    return val


def _ask_int(prompt: str, default: int, min_val: int = 0) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            n = int(raw)
            if n < min_val:
                print(color(f"  ✗ يجب أن يكون ≥ {min_val}", C.RED))
                continue
            return n
        except ValueError:
            print(color("  ✗ رقم غير صالح.", C.RED))


def _validate_bot_token(token: str) -> bool:
    """شكل توكن تيليجرام: 123456:ABC-DEF..."""
    return bool(re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$", token))


def _validate_admin_ids(raw: str) -> list[int]:
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def setup_wizard(force: bool = False) -> dict:
    """يعرض معالج الإعداد التفاعلي."""
    banner()
    print(color("╭─ معالج الإعداد الأول ─────────────────────────────╮", C.MAGENTA))
    print(color("│  سنقوم بإعداد المصنع خطوة بخطوة.                    │", C.MAGENTA))
    print(color("│  الإعدادات ستُحفظ في ~/.ai-factory/config.json      │", C.MAGENTA))
    print(color("╰────────────────────────────────────────────────────╯", C.MAGENTA))
    print()

    # ─── القسم 1: تيليجرام ───
    print(color("①  حساب تيليجرام", C.BOLD + C.YELLOW))
    print(color("   احصل على التوكن من @BotFather في تيليجرام.", C.DIM))
    while True:
        token = _ask("توكن البوت", secret=True)
        if _validate_bot_token(token):
            break
        print(color("  ✗ شكل التوكن غير صحيح. مثال: 123456789:ABC...", C.RED))

    print(color("\n   معرّف الأدمن (ID) — احصل عليه من @userinfobot", C.DIM))
    while True:
        admin_raw = _ask("معرّفات الأدمن (افصل بفواصل)", required=True)
        ids = _validate_admin_ids(admin_raw)
        if ids:
            break
        print(color("  ✗ أدخل رقمًا واحدًا على الأقل.", C.RED))

    # ─── القسم 2: ربط AI (n8n) ───
    print()
    print(color("②  ربط الذكاء الاصطناعي (n8n Webhook)", C.BOLD + C.YELLOW))
    print(color("   رابط الـ webhook الذي سيتولّى التحليل والتوليد.", C.DIM))
    print(color("   مثال: https://xxx.app.n8n.cloud/webhook/xxx", C.DIM))
    while True:
        n8n_url = _ask("رابط n8n Webhook", required=True)
        if n8n_url.startswith(("http://", "https://")):
            break
        print(color("  ✗ يجب أن يبدأ بـ http:// أو https://", C.RED))

    print(color("\n   حماية الـ webhook (اختياري — Enter للتخطي)", C.DIM))
    auth_header = _ask("اسم Header الحماية", default="", required=False)
    auth_token = ""
    if auth_header:
        auth_token = _ask("قيمة التوكن", secret=True)

    # ─── القسم 3: GitHub (اختياري — لبناء APK) ───
    print()
    print(color("③  بناء APK عبر GitHub (اختياري)", C.BOLD + C.YELLOW))
    print(color("   اتركها فارغة لو مش عايز تفعّل بناء APK الآن.", C.DIM))
    gh_token = _ask("GitHub Token", default="", required=False, secret=True)
    gh_user = ""
    gh_repo = ""
    if gh_token:
        gh_user = _ask("GitHub Username")
        gh_repo = _ask("GitHub Repository")

    # ─── القسم 4: النظام ───
    print()
    print(color("④  إعدادات النظام", C.BOLD + C.YELLOW))
    starting_credits = _ask_int("رصيد البداية لكل مستخدم", 30, 0)

    # ─── حفظ ───
    config = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "telegram": {
            "token": token,
            "admin_ids": ids,
        },
        "n8n": {
            "url": n8n_url,
            "auth_header": auth_header,
            "auth_token": auth_token,
            "timeout": 120,
        },
        "github": {
            "token": gh_token,
            "user": gh_user,
            "repo": gh_repo,
        },
        "system": {
            "db_path": str(CONFIG_DIR / "factory.db"),
            "workspaces": str(CONFIG_DIR / "workspaces"),
            "log_level": "INFO",
        },
        "credits": {
            "starting": starting_credits,
            "cost_analysis": 2,
            "cost_generation": 10,
            "cost_apk_build": 15,
            "cost_daily_reward": 5,
        },
    }

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except Exception:
        pass

    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass

    print()
    print(color("╭─ ✅ تم الإعداد بنجاح ─────────────────────────────╮", C.GREEN))
    print(color(f"│  📁  {CONFIG_FILE}", C.GREEN))
    print(color("│  🔒  صلاحيات محمية (600)", C.GREEN))
    print(color("│", C.GREEN))
    print(color("│  للتعديل لاحقًا:  python main.py --reset", C.GREEN))
    print(color("╰────────────────────────────────────────────────────╯", C.GREEN))
    print()
    return config


def load_config() -> dict:
    """يحمّل الإعداد أو يشغّل Setup لو غير موجود."""
    force = "--reset" in sys.argv or "--setup" in sys.argv

    if force:
        if CONFIG_FILE.exists():
            confirm = input(
                color(f"⚠️  سيتم استبدال {CONFIG_FILE}. متابعة؟ (y/N): ", C.YELLOW)
            ).strip().lower()
            if confirm != "y":
                print(color("تم الإلغاء.", C.RED))
                sys.exit(0)
        return setup_wizard(force=True)

    if not CONFIG_FILE.exists():
        print(color("🔧 لم يتم العثور على إعداد سابق — سأشغّل معالج الإعداد.", C.YELLOW))
        print()
        return setup_wizard()
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        # تأكيد الحقول الأساسية
        if not cfg.get("telegram", {}).get("token"):
            raise ValueError("missing telegram token")
        return cfg
    except Exception as e:
        print(color(f"⚠️  ملف الإعداد تالف: {e}", C.RED))
        return setup_wizard(force=True)


# ══════════════════════════════════════════════════════════════════
# الإعدادات — من ملف JSON
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: frozenset[int]

    n8n_url: str
    n8n_auth_header: str
    n8n_auth_token: str
    n8n_timeout: int

    gh_token: str
    gh_user: str
    gh_repo: str

    db_path: str
    workspaces: Path
    log_level: str

    starting_credits: int
    cost_analysis: int
    cost_generation: int
    cost_apk_build: int
    cost_daily_reward: int

    @staticmethod
    def from_dict(d: dict) -> "Config":
        tg = d.get("telegram", {})
        n8n = d.get("n8n", {})
        gh = d.get("github", {})
        sys_ = d.get("system", {})
        cr = d.get("credits", {})
        return Config(
            token=tg.get("token", ""),
            admin_ids=frozenset(int(x) for x in tg.get("admin_ids", [])),
            n8n_url=n8n.get("url", ""),
            n8n_auth_header=n8n.get("auth_header", ""),
            n8n_auth_token=n8n.get("auth_token", ""),
            n8n_timeout=int(n8n.get("timeout", 120)),
            gh_token=gh.get("token", ""),
            gh_user=gh.get("user", ""),
            gh_repo=gh.get("repo", ""),
            db_path=sys_.get("db_path", str(CONFIG_DIR / "factory.db")),
            workspaces=Path(sys_.get("workspaces", str(CONFIG_DIR / "workspaces"))),
            log_level=sys_.get("log_level", "INFO"),
            starting_credits=int(cr.get("starting", 30)),
            cost_analysis=int(cr.get("cost_analysis", 2)),
            cost_generation=int(cr.get("cost_generation", 10)),
            cost_apk_build=int(cr.get("cost_apk_build", 15)),
            cost_daily_reward=int(cr.get("cost_daily_reward", 5)),
        )


_RAW_CFG = load_config()
CFG = Config.from_dict(_RAW_CFG)

# تأكد من وجود المجلدات
CFG.workspaces.mkdir(parents=True, exist_ok=True)
Path(CFG.db_path).parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s │ %(levelname)-7s │ %(name)-12s │ %(message)s",
    level=getattr(logging, CFG.log_level.upper(), logging.INFO),
    stream=sys.stdout,
)
log = logging.getLogger("factory")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4).upper()}"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


# ══════════════════════════════════════════════════════════════════
# قاعدة البيانات
# ══════════════════════════════════════════════════════════════════

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    telegram_id INTEGER UNIQUE NOT NULL,
    username    TEXT,
    plan        TEXT NOT NULL DEFAULT 'FREE',
    credits     INTEGER NOT NULL DEFAULT 0,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    project_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    name         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'DRAFT',
    idea         TEXT,
    requirements TEXT,
    flutter_code TEXT,
    build_id     TEXT,
    apk_url      TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credit_transactions (
    tx_id         TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    delta         INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    balance_after INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_rewards (
    user_id    TEXT NOT NULL,
    claimed_on TEXT NOT NULL,
    amount     INTEGER NOT NULL,
    PRIMARY KEY (user_id, claimed_on)
);
CREATE TABLE IF NOT EXISTS ai_requests (
    ai_id       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    agent       TEXT NOT NULL,
    model       TEXT NOT NULL,
    duration_ms INTEGER,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id     TEXT PRIMARY KEY,
    actor      TEXT,
    action     TEXT NOT NULL,
    target     TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_tx_user ON credit_transactions(user_id);
"""


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def one(self, sql: str, p: tuple = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, p).fetchone()

    def all(self, sql: str, p: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, p).fetchall()

    def exec(self, sql: str, p: tuple = ()) -> None:
        with self.tx() as c:
            c.execute(sql, p)


DB = DB(CFG.db_path)


def audit(actor: str, action: str, target: str = "") -> None:
    DB.exec(
        "INSERT INTO audit_logs(log_id, actor, action, target, created_at) "
        "VALUES (?,?,?,?,?)",
        (new_id("LOG"), actor, action, target, utcnow()),
    )


# ══════════════════════════════════════════════════════════════════
# خدمات المستخدم / الكريدت / المكافآت
# ══════════════════════════════════════════════════════════════════

class Users:
    @staticmethod
    def ensure(tg_id: int, username: str | None):
        row = DB.one("SELECT * FROM users WHERE telegram_id=?", (tg_id,))
        if row:
            return row
        uid = new_id("U")
        is_admin = 1 if tg_id in CFG.admin_ids else 0
        DB.exec(
            "INSERT INTO users(user_id, telegram_id, username, plan, credits, "
            "is_admin, created_at) VALUES (?,?,?,?,?,?,?)",
            (uid, tg_id, username, "FREE", CFG.starting_credits, is_admin, utcnow()),
        )
        audit(uid, "user.create")
        return DB.one("SELECT * FROM users WHERE user_id=?", (uid,))

    @staticmethod
    def adjust_credits(uid: str, delta: int, reason: str) -> int:
        row = DB.one("SELECT credits FROM users WHERE user_id=?", (uid,))
        if not row:
            raise ValueError("المستخدم غير موجود")
        new_balance = row["credits"] + delta
        if new_balance < 0:
            raise ValueError("رصيد غير كافٍ")
        with DB.tx() as c:
            c.execute("UPDATE users SET credits=? WHERE user_id=?", (new_balance, uid))
            c.execute(
                "INSERT INTO credit_transactions(tx_id, user_id, delta, reason, "
                "balance_after, created_at) VALUES (?,?,?,?,?,?)",
                (new_id("TX"), uid, delta, reason, new_balance, utcnow()),
            )
        return new_balance

    @staticmethod
    def charge(uid: str, cost: int, reason: str) -> None:
        if cost > 0:
            Users.adjust_credits(uid, -cost, reason)

    @staticmethod
    def refund(uid: str, amount: int, reason: str) -> None:
        if amount > 0:
            Users.adjust_credits(uid, amount, reason)


class Rewards:
    @staticmethod
    def claim_daily(uid: str) -> tuple[bool, int, str]:
        d = today()
        if DB.one("SELECT 1 FROM daily_rewards WHERE user_id=? AND claimed_on=?",
                  (uid, d)):
            return False, 0, "⏳ استلمت مكافأة اليوم بالفعل، عد غدًا!"
        amount = CFG.cost_daily_reward
        with DB.tx() as c:
            c.execute("INSERT INTO daily_rewards(user_id, claimed_on, amount) "
                      "VALUES (?,?,?)", (uid, d, amount))
        Users.adjust_credits(uid, amount, "daily_reward")
        return True, amount, f"🎁 مبروك! تمت إضافة *{amount}* كريدت لرصيدك."


# ══════════════════════════════════════════════════════════════════
# عميل n8n
# ══════════════════════════════════════════════════════════════════

@dataclass
class AIResult:
    ok: bool
    text: str = ""
    error: str = ""
    duration_ms: int = 0


class N8NClient:
    def __init__(self, url: str, auth_header: str, auth_token: str, timeout: int):
        self.url = url
        self.auth_header = auth_header
        self.auth_token = auth_token
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.auth_header and self.auth_token:
            h[self.auth_header] = self.auth_token
        return h

    @staticmethod
    def _extract_text(data) -> str:
        if isinstance(data, dict):
            for key in ("text", "output", "response", "message", "content", "answer"):
                v = data.get(key)
                if isinstance(v, str) and v.strip():
                    return v
            for k in ("json", "data", "result"):
                if k in data:
                    return N8NClient._extract_text(data[k])
            return json.dumps(data, ensure_ascii=False)
        if isinstance(data, list) and data:
            return N8NClient._extract_text(data[0])
        if isinstance(data, str):
            return data
        return str(data)

    async def complete(self, prompt: str, system: str = "",
                       agent: str = "generic", user_id: str = "system",
                       max_tokens: int = 2000) -> AIResult:
        if not self.configured:
            return AIResult(False, error="N8N URL غير مُهيّأ")

        t0 = time.time()
        payload = {
            "agent": agent,
            "system": system,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "user_id": user_id,
            "ts": utcnow(),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(self.url, headers=self._headers(), json=payload)
            dur = int((time.time() - t0) * 1000)
            if r.status_code >= 400:
                return AIResult(False, error=f"HTTP {r.status_code}: {r.text[:200]}",
                                duration_ms=dur)
            try:
                data = r.json()
                text = self._extract_text(data)
            except Exception:
                text = r.text
            if not text or not text.strip():
                return AIResult(False, error="رد فارغ من n8n", duration_ms=dur)
            return AIResult(True, text=text, duration_ms=dur)
        except httpx.TimeoutException:
            return AIResult(False, error=f"انتهت المدة ({self.timeout}s)",
                            duration_ms=int((time.time() - t0) * 1000))
        except Exception as e:
            return AIResult(False, error=str(e)[:200],
                            duration_ms=int((time.time() - t0) * 1000))


AI = N8NClient(CFG.n8n_url, CFG.n8n_auth_header, CFG.n8n_auth_token, CFG.n8n_timeout)


async def ai_call(uid: str, agent: str, prompt: str, system: str = "",
                  max_tokens: int = 2000) -> AIResult:
    result = await AI.complete(prompt=prompt, system=system, agent=agent,
                               user_id=uid, max_tokens=max_tokens)
    DB.exec(
        "INSERT INTO ai_requests(ai_id, user_id, agent, model, duration_ms, "
        "status, created_at) VALUES (?,?,?,?,?,?,?)",
        (new_id("AI"), uid, agent, "n8n", result.duration_ms,
         "OK" if result.ok else "ERROR", utcnow()),
    )
    return result


# ══════════════════════════════════════════════════════════════════
# تكامل GitHub
# ══════════════════════════════════════════════════════════════════

GH_API = "https://api.github.com"

WORKFLOW_CONTENT = """\
name: Build APK
on:
  workflow_dispatch:
  push:
    branches: [ "build/**" ]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"
      - uses: subosito/flutter-action@v2
        with:
          channel: stable
          cache: true
      - run: flutter pub get
      - run: flutter build apk --release
      - uses: actions/upload-artifact@v4
        with:
          name: app-release
          path: build/app/outputs/flutter-apk/app-release.apk
"""

WORKFLOW_PATH = ".github/workflows/build-apk.yml"


class GitHubClient:
    def __init__(self, token: str, user: str, repo: str):
        self.token = token
        self.user = user
        self.repo = repo

    @property
    def configured(self) -> bool:
        return bool(self.token and self.user and self.repo)

    def _headers(self) -> dict:
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _url(self, suffix: str = "") -> str:
        return f"{GH_API}/repos/{self.user}/{self.repo}{suffix}"

    async def _main_sha(self, c: httpx.AsyncClient) -> str | None:
        for name in ("main", "master"):
            r = await c.get(self._url(f"/git/ref/heads/{name}"),
                            headers=self._headers())
            if r.status_code == 200:
                return r.json()["object"]["sha"]
        return None

    async def _ensure_branch(self, c: httpx.AsyncClient,
                             branch: str, sha: str) -> None:
        r = await c.get(self._url(f"/git/ref/heads/{branch}"),
                        headers=self._headers())
        if r.status_code == 404:
            await c.post(self._url("/git/refs"), headers=self._headers(),
                         json={"ref": f"refs/heads/{branch}", "sha": sha})

    async def _put_file(self, c: httpx.AsyncClient, branch: str,
                        path: str, content: str) -> bool:
        existing = await c.get(self._url(f"/contents/{path}"),
                               headers=self._headers(),
                               params={"ref": branch})
        body = {
            "message": f"Update {path}",
            "content": base64.b64encode(content.encode("utf-8")).decode(),
            "branch": branch,
        }
        if existing.status_code == 200:
            body["sha"] = existing.json()["sha"]
        r = await c.put(self._url(f"/contents/{path}"),
                        headers=self._headers(), json=body)
        return r.status_code in (200, 201)

    async def push_project(self, branch: str,
                           files: dict[str, str]) -> tuple[bool, str]:
        if not self.configured:
            return False, "GitHub غير مُهيّأ"
        async with httpx.AsyncClient(timeout=60.0) as c:
            main_sha = await self._main_sha(c)
            if not main_sha:
                return False, "لم يُعثر على فرع main أو master"
            await self._ensure_branch(c, branch, main_sha)
            all_files = dict(files)
            all_files[WORKFLOW_PATH] = WORKFLOW_CONTENT
            for path, content in all_files.items():
                if not await self._put_file(c, branch, path, content):
                    return False, f"فشل رفع: {path}"
        return True, "تم الرفع"

    async def trigger_build(self, branch: str) -> tuple[bool, str]:
        if not self.configured:
            return False, "GitHub غير مُهيّأ"
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                self._url("/actions/workflows/build-apk.yml/dispatches"),
                headers=self._headers(), json={"ref": branch},
            )
        if r.status_code == 204:
            return True, "تم التشغيل"
        return False, f"HTTP {r.status_code}"

    async def poll_build(self, branch: str, timeout_s: int = 900) -> dict:
        if not self.configured:
            return {"status": "error", "message": "GitHub غير مُهيّأ"}
        deadline = time.time() + timeout_s
        run_id = None
        async with httpx.AsyncClient(timeout=30.0) as c:
            while time.time() < deadline:
                r = await c.get(self._url("/actions/runs"),
                                headers=self._headers(),
                                params={"branch": branch, "per_page": 1})
                if r.status_code == 200:
                    runs = r.json().get("workflow_runs", [])
                    if runs:
                        run_id = runs[0]["id"]
                        break
                await asyncio.sleep(5)
            if not run_id:
                return {"status": "timeout", "message": "لم يبدأ البناء"}
            while time.time() < deadline:
                r = await c.get(self._url(f"/actions/runs/{run_id}"),
                                headers=self._headers())
                if r.status_code != 200:
                    await asyncio.sleep(10)
                    continue
                data = r.json()
                if data["status"] == "completed":
                    return {
                        "status": "completed",
                        "conclusion": data["conclusion"],
                        "run_id": run_id,
                        "html_url": data["html_url"],
                    }
                await asyncio.sleep(15)
        return {"status": "timeout", "message": "انتهت المدة"}


GH = GitHubClient(CFG.gh_token, CFG.gh_user, CFG.gh_repo)


# ══════════════════════════════════════════════════════════════════
# الوكلاء
# ══════════════════════════════════════════════════════════════════

REQ_SYSTEM = """أنت وكيل تحليل المتطلبات في مصنع برمجيات آلي.
استلم فكرة المستخدم وأنتج مواصفات منظّمة بالعربية بهذه الأقسام حرفيًا:

🎯 الهدف:
👥 المستخدمون:
🔑 الأدوار:
⚙️ المزايا:
📱 الشاشات:
🗄 قاعدة البيانات:
🔌 التكاملات:
🔒 الأمان:
📦 المنصات:
✅ MVP:
🚀 مستقبلًا:

كن عمليًا. لا تخترع علامات تجارية. لا تنسخ محتوى محميًا.
لا تتجاوز 350 كلمة."""


async def run_requirements(uid: str, idea: str) -> AIResult:
    return await ai_call(uid, "requirements", idea, REQ_SYSTEM, max_tokens=1200)


FLUTTER_SYSTEM = """أنت مهندس Flutter خبير. مهمتك توليد مشروع Flutter كامل.

أعِد **JSON فقط** (بدون أي نص إضافي، بدون ```json) بهذه البنية:

{
  "pubspec.yaml": "<محتوى>",
  "lib/main.dart": "<محتوى>",
  "README.md": "<محتوى>"
}

القواعد:
- pubspec.yaml يحتوي sdk: '>=3.0.0 <4.0.0'
- main.dart يعمل مباشرة بعد flutter pub get && flutter build apk
- استخدم Material 3
- لا تكتب أي شيء قبل { أو بعد }
- كل القيم نصية صحيحة (escape \\n و \\" جيدًا)
"""


def extract_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start == -1:
        return None
    depth, end, in_str, esc = 0, -1, False, False    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


DEFAULT_PUBSPEC = """name: app
description: Generated by AI LOYAL FACTORY
publish_to: 'none'
version: 1.0.0+1
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
  cupertino_icons: ^1.0.6
dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.0
flutter:
  uses-material-design: true
"""

DEFAULT_MAIN = """import 'package:flutter/material.dart';

void main() => runApp(const MyApp());

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI LOYAL App',
      theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.deepPurple),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My App')),
      body: const Center(
        child: Text('Generated by AI LOYAL FACTORY'),
      ),
    );
  }
}
"""


async def run_flutter_gen(uid: str, requirements: str) -> tuple[AIResult, dict]:
    prompt = (
        f"حوّل هذه المواصفات إلى مشروع Flutter كامل.\n"
        f"اسم المشروع: app\n\n"
        f"═══ المواصفات ═══\n{requirements[:3000]}\n"
        f"═══════════════\n\nأعِد JSON فقط."
    )
    result = await ai_call(uid, "coding", prompt, FLUTTER_SYSTEM, max_tokens=4000)
    if not result.ok:
        return result, {}
    files = extract_json(result.text)
    if not files:
        return AIResult(False, error="فشل استخراج JSON من الرد"), {}
    files.setdefault("pubspec.yaml", DEFAULT_PUBSPEC)
    files.setdefault("lib/main.dart", DEFAULT_MAIN)
    return result, files


def write_project_files(pid: str, files: dict[str, str]) -> Path:
    root = CFG.workspaces / pid
    for rel, content in files.items():
        rel = rel.strip().lstrip("/")
        if ".." in rel.split("/"):
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return root


# ══════════════════════════════════════════════════════════════════
# الأزرار والقوائم
# ══════════════════════════════════════════════════════════════════

def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🚀  إنشاء مشروع جديد", callback_data="new_project")],
        [
            InlineKeyboardButton("📂  مشاريعي", callback_data="my_projects"),
            InlineKeyboardButton("🎁  مكافأة اليوم", callback_data="daily"),
        ],
        [
            InlineKeyboardButton("⭐  رصيدي", callback_data="credits"),
            InlineKeyboardButton("📊  حالة النظام", callback_data="health"),
        ],
        [InlineKeyboardButton("🤖  AI LOYAL", callback_data="ai_loyal")],
        [InlineKeyboardButton("❓  مساعدة", callback_data="help")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("👑  لوحة الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def cancel_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌  إلغاء", callback_data="cancel")],
    ])


def project_actions(pid: str, has_code: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📄  عرض المتطلبات", callback_data=f"req_{pid}")],
    ]
    if not has_code:
        rows.append([
            InlineKeyboardButton("⚙️  توليد كود Flutter", callback_data=f"gen_{pid}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton("📦  بناء APK", callback_data=f"apk_{pid}"),
        ])
    rows.append([InlineKeyboardButton("◀️  رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊  إحصائيات", callback_data="adm_stats")],
        [
            InlineKeyboardButton("👥  المستخدمون", callback_data="adm_users"),
            InlineKeyboardButton("📁  المشاريع", callback_data="adm_projects"),
        ],
        [InlineKeyboardButton("🔐  سجل التدقيق", callback_data="adm_audit")],
        [InlineKeyboardButton("◀️  رجوع", callback_data="main_menu")],
    ])


def ai_loyal_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬  محادثة مباشرة", callback_data="loyal_chat")],
        [InlineKeyboardButton("📖  عن AI LOYAL", callback_data="loyal_about")],
        [InlineKeyboardButton("◀️  رجوع", callback_data="main_menu")],
    ])


# ══════════════════════════════════════════════════════════════════
# النصوص
# ══════════════════════════════════════════════════════════════════

def welcome_text(user_row) -> str:
    badge = "👑 أدمن" if user_row["is_admin"] else "👤 مستخدم"
    return (
        "╔══════════════════════════════╗\n"
        "║   🏭  *AI LOYAL FACTORY*   ║\n"
        "╚══════════════════════════════╝\n\n"
        "_حوّل فكرتك إلى تطبيق حقيقي_\n\n"
        f"┌ 👤 *حسابك*\n"
        f"│ المعرّف: `{user_row['user_id']}`\n"
        f"│ الصلاحية: {badge}\n"
        f"│ الخطة: *{user_row['plan']}*\n"
        f"└ الرصيد: *{user_row['credits']}* ⭐\n\n"
        "اختر من القائمة 👇"
    )


def ask_idea_text() -> str:
    return (
        "🚀 *مشروع جديد*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "أرسل لي فكرتك في رسالة واحدة.\n\n"
        "💡 *أمثلة:*\n"
        "• نظام كاشير لمتجر سوبرماركت\n"
        "• تطبيق متابعة مهام يومية\n"
        "• منصة حجز مواعيد لعيادة\n\n"
        f"💳 *التكلفة:* {CFG.cost_analysis} كريدت\n"
        "⏱ *المدة:* 20-60 ثانية"
    )


def help_text() -> str:
    return (
        "❓ *كيف يعمل المصنع؟*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "*1.* اضغط *🚀 إنشاء مشروع*\n"
        "*2.* أرسل فكرتك بالعربية\n"
        "*3.* يبدأ التحليل تلقائيًا عبر AI LOYAL\n"
        "*4.* ولّد كود Flutter\n"
        "*5.* ابنِ APK حقيقي\n\n"
        "🎁 *مكافأة يومية:* كل 24 ساعة\n"
        "⭐ *الكريدت:* يُخصم عند العمليات المكلفة\n"
        "💰 *الاسترجاع:* تلقائي عند الفشل\n\n"
        "🤖 *AI LOYAL:* مساعدك الشخصي على مدار الساعة\n\n"
        "⚠️ *شفافية:* لا ندّعي نجاح عملية لم تُنفَّذ فعليًا."
    )


def ai_loyal_about() -> str:
    return (
        "🤖 *AI LOYAL*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "مساعدك الذكي المخلص، يعمل على مدار الساعة.\n\n"
        "*القدرات:*\n"
        "• فهم فكرتك وتحويلها لمشروع\n"
        "• الإجابة عن أسئلتك التقنية\n"
        "• اقتراح ميزات وتحسينات\n"
        "• شرح أي جزء من مشروعك\n\n"
        "*كيف تستخدمه؟*\n"
        "اختر *💬 محادثة مباشرة* واكتب سؤالك."
    )


def health_text() -> str:
    def dot(v): return "🟢" if v else "🔴"
    return (
        "📊 *حالة النظام*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"{dot(True)} قاعدة البيانات\n"
        f"{dot(AI.configured)} AI LOYAL (n8n)\n"
        f"{dot(GH.configured)} تكامل GitHub (لبناء APK)\n\n"
        f"📁 البيانات: `{CONFIG_DIR}`\n\n"
        "🟢 = يعمل   🔴 = غير مُهيّأ"
    )


# ══════════════════════════════════════════════════════════════════
# المعالجات
# ══════════════════════════════════════════════════════════════════

# حالات المستخدمين
PENDING: dict[int, dict] = {}


def _user(update: Update):
    u = update.effective_user
    return Users.ensure(u.id, u.username)


async def _edit_or_reply(update: Update, text: str, keyboard=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN,
        )


async def show_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    row = _user(update)
    PENDING.pop(update.effective_user.id, None)
    await _edit_or_reply(update, welcome_text(row), main_menu(bool(row["is_admin"])))


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, ctx)


async def cmd_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(health_text(), parse_mode=ParseMode.MARKDOWN)


async def cmd_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """أمر /ai — يفتح محادثة AI LOYAL."""
    row = _user(update)
    PENDING[update.effective_user.id] = {"step": "loyal_chat"}
    await update.message.reply_text(
        "🤖 *AI LOYAL*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "اكتب سؤالك وسأجيبك فورًا.\n\n"
        "_يمكنك الإلغاء بـ /start_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_only(),
    )


async def cmd_loyal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """أمر /loyal — يعرض قائمة AI LOYAL."""
    await update.message.reply_text(
        "🤖 *AI LOYAL*\n_مساعدك الذكي المخلص._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ai_loyal_menu(),
    )


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    row = _user(update)

    if data == "main_menu":
        await show_main_menu(update, ctx)
        return

    if data == "cancel":
        PENDING.pop(update.effective_user.id, None)
        await q.edit_message_text("تم الإلغاء ✅")
        return

    if data == "help":
        await q.edit_message_text(
            help_text(), parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )
        return

    if data == "health":
        await q.edit_message_text(
            health_text(), parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )
        return

    # ── AI LOYAL ──
    if data == "ai_loyal":
        await q.edit_message_text(
            "🤖 *AI LOYAL*\n_مساعدك الذكي المخلص._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ai_loyal_menu(),
        )
        return

    if data == "loyal_about":
        await q.edit_message_text(
            ai_loyal_about(), parse_mode=ParseMode.MARKDOWN,
            reply_markup=ai_loyal_menu(),
        )
        return

    if data == "loyal_chat":
        PENDING[update.effective_user.id] = {"step": "loyal_chat"}
        await q.edit_message_text(
            "💬 *محادثة AI LOYAL*\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "اكتب سؤالك الآن…",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_only(),
        )
        return

    if data == "daily":
        ok, amount, message = Rewards.claim_daily(row["user_id"])
        fresh = _user(update)
        await q.edit_message_text(
            f"{message}\n\n⭐ *الرصيد:* {fresh['credits']}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )
        return

    if data == "credits":
        txs = DB.all(
            "SELECT * FROM credit_transactions WHERE user_id=? "
            "ORDER BY created_at DESC LIMIT 8", (row["user_id"],),
        )
        lines = [f"⭐ *رصيدك:* {row['credits']} كريدت", "━━━━━━━━━━━━━━━━━━━"]
        if txs:
            lines.append("*آخر العمليات:*")
            for t in txs:
                sign = "➕" if t["delta"] > 0 else "➖"
                lines.append(f"{sign} `{abs(t['delta'])}` — {t['reason']}")
        else:
            lines.append("_لا توجد عمليات بعد_")
        await q.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )
        return

    if data == "new_project":
        PENDING[update.effective_user.id] = {"step": "awaiting_idea"}
        await q.edit_message_text(
            ask_idea_text(), parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_only(),
        )
        return

    if data == "my_projects":
        rows = DB.all(
            "SELECT * FROM projects WHERE user_id=? "
            "ORDER BY created_at DESC LIMIT 15", (row["user_id"],),
        )
        if not rows:
            await q.edit_message_text(
                "📭 *لا توجد مشاريع بعد*\n\nاضغط 🚀 لإنشاء أول مشروع.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu(bool(row["is_admin"])),
            )
            return
        btns = []
        for r in rows:
            icon = {
                "REQUIREMENTS_READY": "📄",
                "CODE_READY": "⚙️",
                "APK_BUILDING": "🔄",
                "APK_READY": "✅",
                "FAILED": "❌",
            }.get(r["status"], "📦")
            btns.append([InlineKeyboardButton(
                f"{icon}  {r['name'][:35]}",
                callback_data=f"open_{r['project_id']}",
            )])
        btns.append([InlineKeyboardButton("◀️ رجوع", callback_data="main_menu")])
        await q.edit_message_text(
            f"📂 *مشاريعك* ({len(rows)})\n━━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(btns),
        )
        return

    if data.startswith("open_"):
        pid = data[5:]
        proj = DB.one(
            "SELECT * FROM projects WHERE project_id=? AND user_id=?",
            (pid, row["user_id"]),
        )
        if not proj:
            await q.answer("مشروع غير موجود", show_alert=True)
            return
        has_code = bool(proj["flutter_code"])
        text = (
            f"📦 *{proj['name']}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 `{pid}`\n"
            f"📌 الحالة: *{proj['status']}*\n"
            f"📅 {proj['created_at'][:10]}\n"
        )
        if proj["apk_url"]:
            text += f"\n✅ *APK جاهز:* [صفحة البناء]({proj['apk_url']})"
        await q.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=project_actions(pid, has_code=has_code),
        )
        return

    if data.startswith("req_"):
        pid = data[4:]
        proj = DB.one(
            "SELECT requirements FROM projects WHERE project_id=? AND user_id=?",
            (pid, row["user_id"]),
        )
        if not proj or not proj["requirements"]:
            await q.answer("لا توجد متطلبات", show_alert=True)
            return
        await q.edit_message_text(
            f"📄 *المتطلبات — {pid}*\n━━━━━━━━━━━━━━━━━━━\n\n"
            f"{proj['requirements'][:3500]}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=project_actions(pid, has_code=True),
        )
        return

    if data.startswith("gen_"):
        await _generate_code(update, ctx, data[4:], row)
        return

    if data.startswith("apk_"):
        await _build_apk(update, ctx, data[4:], row)
        return

    if data == "admin_panel" and row["is_admin"]:
        await q.edit_message_text(
            "👑 *لوحة الأدمن*", parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_panel(),
        )
        return

    if data.startswith("adm_") and row["is_admin"]:
        await _admin_view(update, ctx, data, row)
        return


async def _generate_code(update, ctx, pid: str, row):
    q = update.callback_query
    proj = DB.one(
        "SELECT * FROM projects WHERE project_id=? AND user_id=?",
        (pid, row["user_id"]),
    )
    if not proj or not proj["requirements"]:
        await q.answer("المتطلبات غير جاهزة", show_alert=True)
        return

    cost = CFG.cost_generation
    try:
        Users.charge(row["user_id"], cost, "generate_code")
    except ValueError:
        await q.edit_message_text(
            f"💸 *رصيد غير كافٍ*\nتحتاج *{cost}* كريدت.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )
        return

    await q.edit_message_text(
        f"⚙️ *جاري توليد كود Flutter…*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 `{pid}`\n"
        f"🤖 AI LOYAL يعالج الطلب\n"
        f"⏳ قد يستغرق 30-90 ثانية",
        parse_mode=ParseMode.MARKDOWN,
    )

    result, files = await run_flutter_gen(row["user_id"], proj["requirements"])

    if not result.ok or not files:
        Users.refund(row["user_id"], cost, "generate_refund")
        await q.edit_message_text(
            f"❌ *فشل توليد الكود*\n\nالسبب: {result.error or 'رد غير صالح'}\n"
            f"💰 تم استرجاع الكريدت",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=project_actions(pid, has_code=False),
        )
        return

    root = write_project_files(pid, files)
    files_list = "\n".join(f"  • `{p}`" for p in sorted(files.keys())[:8])

    DB.exec(
        "UPDATE projects SET flutter_code=?, status='CODE_READY', updated_at=? "
        "WHERE project_id=?",
        (str(root), utcnow(), pid),
    )
    audit(row["user_id"], "code.generated", pid)

    await q.edit_message_text(
        f"✅ *تم توليد الكود بنجاح!*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 `{pid}`\n"
        f"📂 الملفات ({len(files)}):\n{files_list}\n\n"
        f"💾 المسار: `{root}`\n\n"
        f"🎯 الخطوة التالية: بناء APK",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=project_actions(pid, has_code=True),
    )


async def _build_apk(update, ctx, pid: str, row):
    q = update.callback_query
    proj = DB.one(
        "SELECT * FROM projects WHERE project_id=? AND user_id=?",
        (pid, row["user_id"]),
    )
    if not proj or not proj["flutter_code"]:
        await q.answer("الكود غير جاهز", show_alert=True)
        return

    if not GH.configured:
        await q.edit_message_text(
            "🔴 *بناء APK غير مُهيّأ*\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            "لتفعيل بناء APK، أعد تشغيل الإعداد:\n"
            "`python main.py --reset`\n\n"
            "وأضف بيانات GitHub.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=project_actions(pid, has_code=True),
        )
        return

    cost = CFG.cost_apk_build
    try:
        Users.charge(row["user_id"], cost, "apk_build")
    except ValueError:
        await q.edit_message_text(
            f"💸 *رصيد غير كافٍ*\nتحتاج *{cost}* كريدت.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=project_actions(pid, has_code=True),
        )
        return

    await q.edit_message_text(
        f"📦 *جاري رفع الكود…*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 `{pid}`\n🔄 GitHub…",
        parse_mode=ParseMode.MARKDOWN,
    )

    root = Path(proj["flutter_code"])
    if not root.exists():
        Users.refund(row["user_id"], cost, "apk_refund")
        await q.edit_message_text(
            "❌ لم يُعثر على ملفات المشروع",
            reply_markup=project_actions(pid, has_code=True),
        )
        return

    files: dict[str, str] = {}
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            try:
                files[str(p.relative_to(root)).replace("\\", "/")] = \
                    p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

    branch = f"build/{pid}"
    ok, message = await GH.push_project(branch, files)
    if not ok:
        Users.refund(row["user_id"], cost, "apk_refund")
        await q.edit_message_text(
            f"❌ *فشل الرفع*\n\nالسبب: {message}\n💰 تم استرجاع الكريدت",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=project_actions(pid, has_code=True),
        )
        return

    await q.edit_message_text(
        f"📦 *جاري بناء APK…*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 `{pid}`\n"
        f"✅ تم رفع الكود\n"
        f"🔄 GitHub Actions يبني الآن…\n"
        f"⏳ المدة: 3-6 دقائق",
        parse_mode=ParseMode.MARKDOWN,
    )

    ok, message = await GH.trigger_build(branch)
    if not ok:
        Users.refund(row["user_id"], cost, "apk_refund")
        await q.edit_message_text(
            f"❌ فشل التشغيل: {message}",
            reply_markup=project_actions(pid, has_code=True),
        )
        return

    DB.exec("UPDATE projects SET status='APK_BUILDING', updated_at=? WHERE project_id=?",
            (utcnow(), pid))

    asyncio.create_task(
        _watch_build(ctx.application, row["user_id"], pid, branch,
                     update.effective_chat.id)
    )


async def _watch_build(app, user_id: str, pid: str, branch: str, chat_id: int):
    try:
        result = await GH.poll_build(branch, timeout_s=900)
    except Exception as e:
        log.exception("poll_build error")
        await app.bot.send_message(chat_id, f"❌ خطأ: `{e}`",
                                   parse_mode=ParseMode.MARKDOWN)
        return

    if result.get("status") != "completed":
        DB.exec("UPDATE projects SET status='FAILED', updated_at=? WHERE project_id=?",
                (utcnow(), pid))
        await app.bot.send_message(
            chat_id,
            f"⏱ *انتهت المدة*\n`{result.get('message','')}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    conclusion = result.get("conclusion")
    html_url = result.get("html_url", "")

    if conclusion == "success":
        run_id = result["run_id"]
        DB.exec(
            "UPDATE projects SET status='APK_READY', apk_url=?, build_id=?, "
            "updated_at=? WHERE project_id=?",
            (html_url, f"B_{run_id}", utcnow(), pid),
        )
        await app.bot.send_message(
            chat_id,
            f"🎉 *تم بناء APK بنجاح!*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📦 `{pid}`\n"
            f"🆔 Build: `B_{run_id}`\n\n"
            f"📥 *تحميل الـ APK:*\n"
            f"[افتح صفحة البناء]({html_url}) ← ثم نزّل `app-release`",
            parse_mode=ParseMode.MARKDOWN,
        )
        audit(user_id, "apk.success", pid)
    else:
        DB.exec("UPDATE projects SET status='FAILED', updated_at=? WHERE project_id=?",
                (utcnow(), pid))
        await app.bot.send_message(
            chat_id,
            f"❌ *فشل بناء APK*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📦 `{pid}`\n\n"
            f"[عرض سجل البناء]({html_url})",
            parse_mode=ParseMode.MARKDOWN,
        )
        audit(user_id, "apk.failed", pid)


async def _admin_view(update: Update, ctx, data: str, row):
    q = update.callback_query

    if data == "adm_stats":
        n_users = DB.one("SELECT COUNT(*) n FROM users")["n"]
        n_proj = DB.one("SELECT COUNT(*) n FROM projects")["n"]
        n_ai = DB.one("SELECT COUNT(*) n FROM ai_requests")["n"]
        n_ok = DB.one("SELECT COUNT(*) n FROM ai_requests WHERE status='OK'")["n"]
        await q.edit_message_text(
            "📊 *إحصائيات المصنع*\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"👥 المستخدمون: *{n_users}*\n"
            f"📁 المشاريع: *{n_proj}*\n"
            f"🤖 طلبات AI LOYAL: *{n_ai}* (ناجحة: {n_ok})\n\n"
            f"{'🟢' if AI.configured else '🔴'} AI LOYAL (n8n)\n"
            f"{'🟢' if GH.configured else '🔴'} GitHub",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_panel(),
        )
        return

    if data == "adm_users":
        rows = DB.all("SELECT * FROM users ORDER BY created_at DESC LIMIT 10")
        lines = ["👥 *آخر 10 مستخدمين*\n━━━━━━━━━━━━━━━━━━━"]
        for r in rows:
            badge = "👑" if r["is_admin"] else "👤"
            lines.append(f"{badge} `{r['user_id']}` — {r['credits']}⭐ — {r['plan']}")
        await q.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_panel(),
        )
        return

    if data == "adm_projects":
        rows = DB.all("SELECT * FROM projects ORDER BY created_at DESC LIMIT 10")
        if not rows:
            await q.edit_message_text("لا مشاريع.", reply_markup=admin_panel())
            return
        lines = ["📁 *آخر 10 مشاريع*\n━━━━━━━━━━━━━━━━━━━"]
        for r in rows:
            lines.append(f"• `{r['project_id']}` — {r['name'][:25]} — {r['status']}")
        await q.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_panel(),
        )
        return

    if data == "adm_audit":
        rows = DB.all("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 12")
        lines = ["🔐 *سجل التدقيق*\n━━━━━━━━━━━━━━━━━━━"]
        for r in rows:
            lines.append(f"• `{r['action']}` → `{r['target']}`")
        await q.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_panel(),
        )
        return


# ══════════════════════════════════════════════════════════════════
# استقبال النصوص — يدير كل من فكرة المشروع + AI LOYAL
# ══════════════════════════════════════════════════════════════════

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    row = _user(update)
    text = (update.message.text or "").strip()

    if not text:
        return

    state = PENDING.get(u.id)

    # ── فكرة مشروع جديدة ──
    if state and state.get("step") == "awaiting_idea":
        await _handle_new_project(update, ctx, text, row)
        return

    # ── محادثة AI LOYAL ──
    if state and state.get("step") == "loyal_chat":
        await _handle_loyal_chat(update, ctx, text, row)
        return

    # ── لا حالة ──
    await update.message.reply_text(
        "اختر من القائمة 👇",
        reply_markup=main_menu(bool(row["is_admin"])),
    )


async def _handle_new_project(update, ctx, text: str, row):
    u = update.effective_user
    PENDING.pop(u.id, None)

    cost = CFG.cost_analysis
    try:
        Users.charge(row["user_id"], cost, "analysis")
    except ValueError:
        await update.message.reply_text(
            f"💸 *رصيد غير كافٍ*\nتحتاج *{cost}* كريدت.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )
        return

    pid = new_id("P")
    DB.exec(
        "INSERT INTO projects(project_id, user_id, name, status, idea, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (pid, row["user_id"], text[:40], "ANALYZING", text, utcnow(), utcnow()),
    )
    audit(row["user_id"], "project.create", pid)

    await update.message.reply_text(
        f"⚙️ *جاري التحليل…*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 المشروع: `{pid}`\n\n"
        f"🤖 AI LOYAL يحلّل الفكرة الآن",
        parse_mode=ParseMode.MARKDOWN,
    )

    result = await run_requirements(row["user_id"], text)

    if result.ok:
        DB.exec(
            "UPDATE projects SET requirements=?, status='REQUIREMENTS_READY', "
            "updated_at=? WHERE project_id=?",
            (result.text, utcnow(), pid),
        )
        audit(row["user_id"], "requirements.ready", pid)
        await update.message.reply_text(
            f"✅ *المتطلبات جاهزة*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📦 `{pid}`\n\n"
            f"{result.text[:3500]}\n\n"
            f"🤖 `AI LOYAL` ⏱ {result.duration_ms}ms",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=project_actions(pid, has_code=False),
        )
    else:
        Users.refund(row["user_id"], cost, "analysis_refund")
        DB.exec("UPDATE projects SET status='FAILED', updated_at=? WHERE project_id=?",
                (utcnow(), pid))
        await update.message.reply_text(
            f"❌ *فشل التحليل*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📦 `{pid}`\n\n"
            f"السبب: {result.error}\n\n"
            f"💰 تم استرجاع الكريدت ✅",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )


async def _handle_loyal_chat(update, ctx, text: str, row):
    """يحوّل الرسالة إلى AI LOYAL عبر n8n."""
    u = update.effective_user

    await update.message.reply_text(
        "🤖 _AI LOYAL يفكّر…_",
        parse_mode=ParseMode.MARKDOWN,
    )

    system_prompt = (
        "أنت AI LOYAL، مساعد ذكي مخلص لمستخدم في مصنع برمجيات آلي. "
        "أجب بالعربية بإيجاز ووضوح. اقترح حلولًا عملية."
    )

    result = await ai_call(
        uid=row["user_id"],
        agent="loyal_chat",
        prompt=text,
        system=system_prompt,
        max_tokens=1500,
    )

    if result.ok:
        PENDING[u.id] = {"step": "loyal_chat"}  # اسمح بالمتابعة
        await update.message.reply_text(
            f"🤖 *AI LOYAL*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{result.text[:3500]}\n\n"
            f"_⏱ {result.duration_ms}ms — اكتب رسالة أخرى أو /start للخروج_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_only(),
        )
    else:
        await update.message.reply_text(
            f"❌ *AI LOYAL غير متاح*\n\n"
            f"السبب: {result.error}\n\n"
            f"تأكد من إعداد n8n (`python main.py --reset`)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )


# ══════════════════════════════════════════════════════════════════
# الإقلاع
# ══════════════════════════════════════════════════════════════════

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 القائمة الرئيسية"),
        BotCommand("ai", "🤖 محادثة AI LOYAL"),
        BotCommand("loyal", "📖 قائمة AI LOYAL"),
        BotCommand("health", "📊 حالة النظام"),
    ])


def print_status_banner() -> None:
    print(color("━" * 62, C.CYAN))
    print(color(f"  🏭  {APP_NAME}", C.BOLD + C.CYAN))
    print(color("━" * 62, C.CYAN))
    print(f"  📁 Config:   {color(str(CONFIG_FILE), C.DIM)}")
    print(f"  💾 DB:       {color(CFG.db_path, C.DIM)}")
    print(f"  📂 Works:    {color(str(CFG.workspaces), C.DIM)}")
    print()
    ok = lambda v: color("🟢", C.GREEN) if v else color("🔴", C.RED)
    print(f"  {ok(AI.configured)}  AI LOYAL (n8n):  {color(CFG.n8n_url or '-', C.DIM)}")
    print(f"  {ok(GH.configured)}  GitHub (APK):   "
          f"{color(f'{CFG.gh_user}/{CFG.gh_repo}' if GH.configured else '-', C.DIM)}")
    print(f"  {ok(True)}  Database:       {color('SQLite', C.DIM)}")
    print(f"  {ok(True)}  Admins:         {color(str(sorted(CFG.admin_ids) or 'none'), C.DIM)}")
    print(color("━" * 62, C.CYAN))
    print(color("  ✓ البوت يعمل الآن. (Ctrl+C للإيقاف)", C.GREEN))
    print(color("━" * 62, C.CYAN))
    print()


def main() -> None:
    if not CFG.token:
        print(color("❌ TELEGRAM_BOT_TOKEN غير مُهيّأ — أعد الإعداد:", C.RED))
        print(color("    python main.py --reset", C.YELLOW))
        sys.exit(1)

    print_status_banner()

    app = (
        Application.builder()
        .token(CFG.token)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("ai",     cmd_ai))
    app.add_handler(CommandHandler("loyal",  cmd_loyal))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
