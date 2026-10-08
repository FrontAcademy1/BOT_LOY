"""
🏭 AI SOFTWARE FACTORY — نسخة احترافية كاملة في ملف واحد
═══════════════════════════════════════════════════════════
حوّل فكرة نصية إلى تطبيق Android حقيقي.

المبادئ:
  ✅ معرّفات فريدة لكل كيان (U_, P_, TX_, AI_, LOG_, B_)
  ✅ لا ندّعي نجاح عملية لم تُنفَّذ فعليًا
  ✅ نظام Credits + Daily Reward بتحقق سيرفر
  ✅ عزل المشاريع حسب المالك
  ✅ بناء APK حقيقي عبر GitHub Actions
  ✅ لوحة أدمن + سجل تدقيق
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from telegram import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)

load_dotenv()

# ══════════════════════════════════════════════════════════════════
# 1) الإعدادات
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: frozenset[int]
    ai_key: str
    ai_base: str
    ai_model: str
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
    def load() -> "Config":
        e = lambda k, d="": os.getenv(k, d).strip()
        i = lambda k, d=0: int(e(k, str(d)))

        admins = frozenset(
            int(x) for x in e("ADMIN_TELEGRAM_IDS").split(",") if x.strip().isdigit()
        )
        return Config(
            token=e("TELEGRAM_BOT_TOKEN"),
            admin_ids=admins,
            ai_key=e("OPENAI_API_KEY"),
            ai_base=e("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            ai_model=e("AI_MODEL", "gpt-4o-mini"),
            gh_token=e("GITHUB_TOKEN"),
            gh_user=e("GITHUB_USER"),
            gh_repo=e("GITHUB_REPO"),
            db_path=e("DATABASE_PATH", "factory.db"),
            workspaces=Path(e("WORKSPACES_PATH", "workspaces")),
            log_level=e("LOG_LEVEL", "INFO"),
            starting_credits=i("STARTING_CREDITS", 30),
            cost_analysis=i("COST_ANALYSIS", 2),
            cost_generation=i("COST_GENERATION", 10),
            cost_apk_build=i("COST_APK_BUILD", 15),
            cost_daily_reward=i("COST_DAILY_REWARD", 5),
        )

CFG = Config.load()

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
# 2) قاعدة البيانات
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
# 3) خدمات المستخدم / الكريدت / المكافآت
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
# 4) عميل AI موحّد
# ══════════════════════════════════════════════════════════════════

@dataclass
class AIResult:
    ok: bool
    text: str = ""
    error: str = ""
    duration_ms: int = 0


class AIClient:
    def __init__(self, key: str, base: str, model: str):
        self.key = key
        self.base = base.rstrip("/")
        self.model = model

    @property
    def configured(self) -> bool:
        return bool(self.key)

    async def complete(self, prompt: str, system: str = "",
                       max_tokens: int = 2000) -> AIResult:
        if not self.configured:
            return AIResult(False, error="OPENAI_API_KEY غير مُهيّأ")
        t0 = time.time()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.post(
                    f"{self.base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if r.status_code >= 400:
                return AIResult(
                    False, error=f"HTTP {r.status_code}: {r.text[:180]}",
                    duration_ms=int((time.time() - t0) * 1000),
                )
            text = r.json()["choices"][0]["message"]["content"]
            return AIResult(True, text, duration_ms=int((time.time() - t0) * 1000))
        except Exception as e:
            return AIResult(False, error=str(e)[:180],
                            duration_ms=int((time.time() - t0) * 1000))


AI = AIClient(CFG.ai_key, CFG.ai_base, CFG.ai_model)


async def ai_call(uid: str, agent: str, prompt: str, system: str = "",
                  max_tokens: int = 2000) -> AIResult:
    result = await AI.complete(prompt, system, max_tokens)
    DB.exec(
        "INSERT INTO ai_requests(ai_id, user_id, agent, model, duration_ms, "
        "status, created_at) VALUES (?,?,?,?,?,?,?)",
        (new_id("AI"), uid, agent, AI.model, result.duration_ms,
         "OK" if result.ok else "ERROR", utcnow()),
    )
    return result


# ══════════════════════════════════════════════════════════════════
# 5) تكامل GitHub — بناء APK
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
# 6) الوكلاء — المتطلبات + توليد Flutter
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

    depth, end, in_str, esc = 0, -1, False, False
    for i in range(start, len(text)):
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
description: Generated by AI Software Factory
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
      title: 'AI Factory App',
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
        child: Text('تم التوليد بواسطة AI Software Factory'),
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
        return AIResult(False, error="فشل استخراج JSON"), {}

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
# 7) الأزرار والقوائم
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


# ══════════════════════════════════════════════════════════════════
# 8) النصوص
# ══════════════════════════════════════════════════════════════════

def welcome_text(user_row) -> str:
    badge = "👑 أدمن" if user_row["is_admin"] else "👤 مستخدم"
    return (
        "╔══════════════════════════╗\n"
        "║   🏭  *AI SOFTWARE FACTORY*   ║\n"
        "╚══════════════════════════╝\n\n"
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
        "*3.* يبدأ التحليل تلقائيًا\n"
        "*4.* ولّد كود Flutter\n"
        "*5.* ابنِ APK حقيقي\n\n"
        "🎁 *مكافأة يومية:* كل 24 ساعة\n"
        "⭐ *الكريدت:* يُخصم عند العمليات المكلفة\n"
        "💰 *الاسترجاع:* تلقائي عند الفشل\n\n"
        "⚠️ *شفافية:* لا ندّعي نجاح عملية لم تُنفَّذ فعليًا."
    )


def health_text() -> str:
    def dot(v): return "🟢" if v else "🔴"
    return (
        "📊 *حالة النظام*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"{dot(True)} قاعدة البيانات\n"
        f"{dot(AI.configured)} مزوّد الذكاء الاصطناعي\n"
        f"{dot(GH.configured)} تكامل GitHub (لبناء APK)\n\n"
        "🟢 = يعمل   🔴 = غير مُهيّأ"
    )


# ══════════════════════════════════════════════════════════════════
# 9) المعالجات
# ══════════════════════════════════════════════════════════════════

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
        f"🧠 وكيل Flutter يعمل الآن\n"
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
            "لتفعيل بناء APK، أضف في `.env`:\n"
            "• `GITHUB_TOKEN`\n"
            "• `GITHUB_USER`\n"
            "• `GITHUB_REPO`\n\n"
            "_سيبدأ العمل فورًا بعد الإعداد._",
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
            f"[افتح صفحة البناء]({html_url}) ← ثم نزّل `app-release`\n\n"
            f"⚠️ رابط GitHub يتطلب تسجيل دخول لتحميل الـ artifact.\n"
            f"لمشاركة مباشرة، فعّل Object Storage (S3/R2).",
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
            f"[عرض سجل البناء]({html_url})\n"
            f"الأسباب الشائعة: خطأ في الكود المولّد أو تبعية غير متوافقة.",
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
            f"🤖 طلبات AI: *{n_ai}* (ناجحة: {n_ok})\n\n"
            f"{'🟢' if AI.configured else '🔴'} AI\n"
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


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    row = _user(update)
    text = (update.message.text or "").strip()

    if not text:
        return

    state = PENDING.get(u.id)
    if not state or state.get("step") != "awaiting_idea":
        await update.message.reply_text(
            "اختر من القائمة 👇",
            reply_markup=main_menu(bool(row["is_admin"])),
        )
        return

    cost = CFG.cost_analysis
    try:
        Users.charge(row["user_id"], cost, "analysis")
    except ValueError:
        PENDING.pop(u.id, None)
        await update.message.reply_text(
            f"💸 *رصيد غير كافٍ*\nتحتاج *{cost}* كريدت.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(bool(row["is_admin"])),
        )
        return

    PENDING.pop(u.id, None)

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
        f"🧠 وكيل المتطلبات يعمل الآن",
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
            f"🤖 `{AI.model}` ⏱ {result.duration_ms}ms",
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


# ══════════════════════════════════════════════════════════════════
# 10) الإقلاع
# ══════════════════════════════════════════════════════════════════

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 القائمة الرئيسية"),
        BotCommand("health", "📊 حالة النظام"),
    ])


def main() -> None:
    if not CFG.token:
        log.error("TELEGRAM_BOT_TOKEN غير مهيّأ — راجع .env")
        sys.exit(1)

    log.info("━" * 60)
    log.info("🏭 AI SOFTWARE FACTORY")
    log.info("━" * 60)
    log.info("AI Provider:  %s",
             "🟢 configured" if AI.configured else "🔴 NOT configured")
    log.info("GitHub:       %s",
             "🟢 configured" if GH.configured else "🔴 NOT configured")
    log.info("Admins:       %s", sorted(CFG.admin_ids) or "none")
    log.info("Database:     %s", CFG.db_path)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("Polling… (Ctrl+C للإيقاف)")

    app = (
        Application.builder()
        .token(CFG.token)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()