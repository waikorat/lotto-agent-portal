"""
LuckyNumber Agent Portal (ระบบตัวแทน) — ฉบับแก้ไขเต็ม
รัน:  DB_URI=... SECRET_KEY=... uvicorn agent_app:app --host 0.0.0.0 --port 8001
"""
import itertools
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import DictLoader, Environment

import common
from common import PLAYS, RATE_DEFAULTS, RATE_KEYS, db

log = logging.getLogger("agent_app")


@asynccontextmanager
async def lifespan(_app):
    if os.environ.get("RUN_MIGRATIONS", "1") == "1":
        print("common.py build:", common.BUILD)
        common.run_migrations()
    yield


app = FastAPI(title="LuckyNumber Agent Portal", lifespan=lifespan)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

MAX_AMOUNT = 1_000_000
MAX_NUMS_PER_SUBMIT = 500
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,50}$")


# ============================================================ ตัวช่วย

def redir(path, **params):
    params = {k: v for k, v in params.items() if v not in (None, "")}
    return RedirectResponse(path + ("?" + urlencode(params) if params else ""), status_code=303)


def render(request, name, **ctx):
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("error", request.query_params.get("error"))
    return HTMLResponse(env.get_template(name).render(**ctx))


def get_me(c, request):
    return common.get_session_user(c, request.cookies.get(common.SESSION_COOKIE))


def to_login():
    return RedirectResponse("/login", status_code=303)


def is_manager(me):
    return me["role"] in common.MANAGER_ROLES


class RateForm:
    """รับค่าเรต 9 ช่องจากฟอร์ม แล้วตรวจช่วงค่าผ่าน common.clean_rates"""

    def __init__(self, pay_3d: float = Form(500), pay_3tod: float = Form(100), pay_2d: float = Form(70),
                 pay_run_top: float = Form(3.2), pay_run_bot: float = Form(4.2),
                 disc_3d: float = Form(0), disc_2d: float = Form(0), disc_run: float = Form(0),
                 disc_total: float = Form(0)):
        self.values = common.clean_rates(dict(
            pay_3d=pay_3d, pay_3tod=pay_3tod, pay_2d=pay_2d, pay_run_top=pay_run_top, pay_run_bot=pay_run_bot,
            disc_3d=disc_3d, disc_2d=disc_2d, disc_run=disc_run, disc_total=disc_total))


# ---- จำกัดจำนวนครั้งล็อกอินผิด (ในหน่วยความจำ ต่อ IP+username) ----
_FAILS = {}


def _throttled(key):
    now = time.time()
    _FAILS[key] = [t for t in _FAILS.get(key, []) if now - t < 300]
    return len(_FAILS[key]) >= 5


# ============================================================ เทมเพลต

BASE = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}LuckyNumber ERP{% endblock %}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
 * { box-sizing: border-box; }
 body { background:#f7e6d0; font-family:'Segoe UI',Tahoma,sans-serif; margin:0; overflow-x:hidden; }
 .top-navbar { background:#000; border-bottom:2px solid #d4af37; padding:8px 15px; display:flex; flex-wrap:wrap;
               gap:8px; align-items:center; justify-content:space-between; }
 .logo-text { font-family:Georgia,serif; font-style:italic; font-weight:bold; font-size:1.3rem; color:#f3e5ab; margin-right:10px; }
 .top-nav-menu { display:flex; flex-wrap:wrap; gap:4px; align-items:center; }
 .top-nav-menu a { color:#fff; text-decoration:none; font-size:.8rem; padding:4px 8px; border-radius:4px;
                   background:#1a1a1a; border:1px solid #333; white-space:nowrap; }
 .top-nav-menu a:hover { background:#d4af37; color:#000; font-weight:bold; }
 .table-responsive { width:100%; overflow-x:auto; }
 .card { max-width:100%; word-break:break-word; }
</style>
{% block head %}{% endblock %}
</head>
<body>
{% if user %}
<div class="top-navbar">
  <div class="d-flex align-items-center flex-wrap">
    <span class="logo-text">LuckyNumber ERP</span>
    <div class="top-nav-menu">
      <a href="/select-market">บันทึกโพย</a>
      <a href="/agent-reports">รายงานผล</a>
      {% if user.role == 'Admin' %}
      <a href="/live-sales" class="text-info">📈 ยอดขายสด</a>
      <a href="/campaigns" class="text-warning">📌 จัดการงวด</a>
      <a href="/blocked-numbers">🚫 เลขอั้น</a>
      <a href="/results">🏆 ผลรางวัล</a>
      <a href="/audit-all">🔍 ตรวจสอบทั้งหมด</a>
      <a href="/db-inspector">🗄️ ตรวจสอบ DB</a>
      {% endif %}
      {% if user.role in ['Admin','Master Agent','Agent'] %}<a href="/dashboard">📊 แดชบอร์ด</a><a href="/audit-discount">🔍 ส่วนลด</a>{% endif %}
      {% if user.role in ['Admin','Master Agent','Agent'] %}
      <a href="/admin-users">จัดการผู้ใช้</a>
      <a href="/manage-customers">จัดการลูกค้า</a>
      <a href="/customer-rates-page">เรตลูกค้าแยกหวย</a>
      {% endif %}
      <a href="/change-password" class="text-warning">เปลี่ยนรหัสผ่าน</a>
    </div>
  </div>
  <div class="d-flex align-items-center gap-2">
    <span class="text-warning small">สถานะ: <b>{{ user.role }} ({{ user.username }})</b></span>
    {% if user.role == 'Admin' %}<a href="/system-reset" class="btn btn-outline-danger btn-sm fw-bold px-2 py-1" style="font-size:.75rem;">⚠️ รีเซ็ตระบบ</a>{% endif %}
    <a href="/logout" class="btn btn-danger btn-sm fw-bold px-2 py-1" style="font-size:.75rem;">ออกจากระบบ</a>
  </div>
</div>
{% endif %}
{% if msg %}<div class="alert alert-success text-center fw-bold m-2">{{ msg }}</div>{% endif %}
{% if error %}<div class="alert alert-danger text-center fw-bold m-2">❌ {{ error }}</div>{% endif %}
{% block body %}{% endblock %}
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
{% block scripts %}{% endblock %}
</body>
</html>"""

MACROS = """
{% macro num(name, label, val, col=4, step='any') -%}
<div class="col-{{ col }}"><label class="form-label small mb-0">{{ label }}</label>
<input type="number" step="{{ step }}" min="0" name="{{ name }}" class="form-control form-control-sm" value="{{ val }}"></div>
{%- endmacro %}

{% macro rate_fields(v) %}
<h6 class="fw-bold text-primary small mt-2">💰 อัตราจ่าย</h6>
<div class="row g-2 mb-2">
  {{ num('pay_3d','3ตัวตรง',v.pay_3d) }}{{ num('pay_3tod','3ตัวโต๊ด',v.pay_3tod) }}{{ num('pay_2d','2ตัว',v.pay_2d) }}
  {{ num('pay_run_top','วิ่งบน',v.pay_run_top,6) }}{{ num('pay_run_bot','วิ่งล่าง',v.pay_run_bot,6) }}
</div>
<h6 class="fw-bold text-success small">📉 ส่วนลด (%)</h6>
<div class="row g-2 mb-3">
  {{ num('disc_3d','3ตัว',v.disc_3d,6) }}{{ num('disc_2d','2ตัว',v.disc_2d,6) }}
  {{ num('disc_run','วิ่ง',v.disc_run,6) }}{{ num('disc_total','รวม (ใช้เมื่อช่องอื่น=0)',v.disc_total,6) }}
</div>
{% endmacro %}
"""

LIVE_SALES = """{% extends "base.html" %}
{% block title %}ยอดขายเรียลไทม์{% endblock %}
{% block body %}
<div class="container-fluid my-3 px-4">
  <h3 class="fw-bold text-primary mb-3">📈 ยอดขายเรียลไทม์</h3>
  {{ inner|safe }}
</div>
{% endblock %}"""

LOGIN = """{% extends "base.html" %}
{% block head %}<style>body{height:100vh;display:flex;align-items:center;justify-content:center;flex-direction:column}
.login-card{width:100%;max-width:400px;background:#000;border:2px solid #d4af37;padding:30px;border-radius:10px;color:#fff}
.logo-text{font-size:2.2rem;text-align:center;display:block;margin-bottom:20px}</style>{% endblock %}
{% block body %}
<div class="login-card">
  <span class="logo-text" style="font-family:Georgia,serif;font-style:italic;font-weight:bold;color:#f3e5ab">LuckyNumber</span>
  <form method="POST" action="/login">
    <div class="mb-3"><label class="form-label small fw-bold">Username</label>
      <input type="text" name="username" class="form-control" required autofocus></div>
    <div class="mb-3"><label class="form-label small fw-bold">Password</label>
      <input type="password" name="password" class="form-control" required></div>
    <button class="btn btn-warning w-100 fw-bold text-dark py-2">เข้าสู่ระบบ</button>
  </form>
</div>
{% endblock %}"""

SELECT_MARKET = """{% extends "base.html" %}
{% block title %}เลือกงวดหวย{% endblock %}
{% block body %}
<div class="container-fluid my-4 px-4">
  <h3 class="fw-bold mb-1 text-primary">📌 เลือกงวดหวยที่ต้องการคีย์โพย</h3>
  <p class="text-muted small">กล่องสีเขียว = เปิดรับแทง (เรียงตามเวลาที่เหลือก่อนปิดรับ น้อยที่สุดอยู่ก่อน) · กล่องสีขาว = ปิดรับแล้วหรือยังไม่ถึงเวลาเปิดรับ</p>
  {{ cards_html|safe }}
</div>
{% endblock %}"""

PORTAL = """{% extends "base.html" %}
{% block title %}บันทึกโพยหวย{% endblock %}
{% block head %}<style>
 .main-container{display:flex;width:100%;min-height:calc(100vh - 60px)}
 .sidebar-left{width:260px;background:#000;color:#fff;border-right:2px solid #d4af37;padding:12px;flex-shrink:0}
 .content-center{flex-grow:1;padding:15px;min-width:0}
 .sidebar-right{width:300px;background:rgba(255,255,255,.4);border-left:2px solid #d4af37;padding:15px;flex-shrink:0}
 .market-banner{background:#dc3545;color:#fff;padding:10px 15px;border-radius:6px;display:flex;justify-content:space-between;
   align-items:center;font-weight:bold;margin-bottom:15px;flex-wrap:wrap;gap:6px}
 .timer{background:#198754;color:#fff;padding:4px 10px;border-radius:6px;font-weight:bold;font-size:.85rem;border:2px solid #fff}
 .quick-btn{background:#0d6efd;color:#fff;font-weight:bold;border:none;padding:8px 15px;border-radius:6px;flex-grow:1;font-size:.9rem}
 .preview-box{background:#ccfeff;border:2px solid #0dcaf0;padding:10px;border-radius:6px;font-family:monospace;font-weight:bold;
   margin-bottom:12px;min-height:45px;display:flex;align-items:center;flex-wrap:wrap;gap:5px}
 .rate-table th,.rate-table td{font-size:.78rem;padding:4px!important;color:#fff;background:#1a1a1a!important;border-color:#444!important}
 .menu-title{color:#fff;font-weight:bold;font-size:.88rem;margin:15px 0 6px;border-bottom:1px solid #444;padding-bottom:3px}
 .menu-item{display:block;text-decoration:none;padding:5px 8px;font-size:.83rem;margin-bottom:3px;border-radius:4px}
 .menu-item:hover{background:#222}
 @media (max-width:992px){.main-container{flex-direction:column}.sidebar-left,.sidebar-right{width:100%}}
</style>{% endblock %}
{% block body %}
<div class="main-container">
  <div class="sidebar-left">
    <form method="GET" action="/portal" id="customerForm">
      <input type="hidden" name="campaign_id" value="{{ camp.id }}">
      <label class="form-label small fw-bold text-warning">เลือกลูกค้า / สายงาน:</label>
      <select name="customer_id" class="form-select form-select-sm mb-3" onchange="this.form.submit()">
        {% for t in targets %}<option value="{{ t.key }}" {% if t.key == customer_id %}selected{% endif %}>{{ t.label }}</option>{% endfor %}
      </select>
    </form>
    <div class="small fw-bold text-info mb-1">อัตราจ่าย: {{ camp.lotto_name }}</div>
    <div class="text-warning mb-1" style="font-size:.75rem">({{ current_name }})
      {% if rate_source == 'default' %}<span class="badge bg-secondary">เรตพื้นฐาน</span>{% endif %}</div>
    {% if rates %}
    <table class="table table-bordered rate-table text-center">
      <thead><tr><th>ประเภท</th><th>จ่าย</th><th>ลด</th></tr></thead>
      <tbody>
        <tr><td>3ตัวตรง</td><td>{{ rates.pay_3d }}</td><td>{{ eff.d3 }}%</td></tr>
        <tr><td>3ตัวโต๊ด</td><td>{{ rates.pay_3tod }}</td><td>{{ eff.d3 }}%</td></tr>
        <tr><td>2ตัวบน/ล่าง</td><td>{{ rates.pay_2d }}</td><td>{{ eff.d2 }}%</td></tr>
        <tr><td>วิ่งบน/ล่าง</td><td>{{ rates.pay_run_top }}/{{ rates.pay_run_bot }}</td><td>{{ eff.drun }}%</td></tr>
      </tbody>
    </table>
    {% else %}<div class="alert alert-warning py-2 small text-center">ยังไม่พบเรตของผู้ซื้อรายนี้</div>{% endif %}
    <div class="menu-title">เมนูด่วน</div>
    {% if user.role in ['Admin','Master Agent','Agent'] %}
    <a href="/admin-users" class="menu-item text-warning">👥 จัดการผู้ใช้</a>
    <a href="/manage-customers" class="menu-item text-info">👤 จัดการลูกค้า</a>
    <a href="/customer-rates-page" class="menu-item text-warning">⚙️ ตั้งเรตแยกตามหวย</a>
    {% endif %}
    <a href="/select-market" class="menu-item text-primary">🏠 กลับหน้าเลือกหวย</a>
    <a href="/agent-reports" class="menu-item text-success">📊 รายงานผล & สรุปยอด</a>
    {% if user.role == 'Admin' %}<a href="/live-sales" class="menu-item text-info">📈 ยอดขายสด (เรียลไทม์)</a>{% endif %}
  </div>

  <div class="content-center">
    <div class="market-banner">
      <div>🎟️ {{ camp.lotto_name }} (งวด {{ camp.draw_date }})</div>
      <div>
        <span id="timer" class="timer" data-seconds="{{ seconds_left if seconds_left is not none else '' }}">⏳</span>
        <span class="small ms-2">ผู้ซื้อ: {{ current_name }}</span>
      </div>
    </div>

    {% if not is_open %}<div class="alert alert-secondary fw-bold text-center">🔒 {{ closed_reason }} — ไม่สามารถเพิ่มโพยหรือออกบิลได้</div>{% endif %}

    {% if not rates %}
    <div class="alert alert-danger text-center bg-white border border-danger border-2 p-4">
      <h5 class="text-danger fw-bold">ยังไม่ได้ตั้งค่าเรตของผู้ซื้อรายนี้</h5>
      {% if user.role in ['Admin','Master Agent','Agent'] %}
      <a href="/customer-rates-page?target_id={{ customer_id }}&lotto_name={{ camp.lotto_name|urlencode }}" class="btn btn-danger fw-bold">⚙️ ไปตั้งเรต ➡️</a>
      {% endif %}
    </div>
    {% elif is_open %}
    <div class="d-flex gap-2 mb-3">
      <button type="button" class="quick-btn" onclick="apply6Box()">6กลับ</button>
      <button type="button" class="quick-btn" onclick="apply19Door()">รูด19ประตู</button>
      <button type="button" class="quick-btn" onclick="applyFrontRoot()">รูดหน้า</button>
      <button type="button" class="quick-btn" onclick="applyBackRoot()">รูดหลัง</button>
    </div>
    <div class="preview-box" id="previewContent"><span class="text-muted small">preview:- (พิมพ์เลข 1 ตัวแล้วกดรูด หรือเลข 3 ตัวแล้วกด 6กลับ)</span></div>

    <form method="POST" action="/portal-add-draft" class="p-3 bg-white rounded shadow-sm border mb-3" onreset="resetPreview()">
      <input type="hidden" name="campaign_id" value="{{ camp.id }}">
      <input type="hidden" name="customer_id" value="{{ customer_id }}">
      <input type="hidden" id="hiddenGeneratedNums" name="generated_nums" value="">
      <div class="row g-2 align-items-center">
        <div class="col-md-4"><label class="form-label small fw-bold mb-1">ตัวเลข</label>
          <input type="text" id="mainNumInput" name="num_input" class="form-control" placeholder="พิมพ์เลข... (คั่นหลายเลขด้วย ,)" oninput="refreshPreview()" required autofocus autocomplete="off"></div>
        <div class="col-md-4"><label class="form-label small fw-bold mb-1">บน / 3ตัวตรง / 2ตัวบน</label>
          <input type="number" step="any" min="0" id="topAmtInput" name="top_amt" class="form-control" placeholder="จำนวนเงิน" oninput="refreshPreview()"></div>
        <div class="col-md-4"><label class="form-label small fw-bold mb-1">ล่าง / 3ตัวโต๊ด / 2ตัวล่าง</label>
          <input type="number" step="any" min="0" id="botAmtInput" name="bot_amt" class="form-control" placeholder="จำนวนเงิน" oninput="refreshPreview()"></div>
      </div>
      <div class="d-flex gap-2 mt-2">
        <button type="reset" class="btn btn-danger btn-sm fw-bold px-4">ยกเลิก</button>
        <button type="submit" class="btn btn-primary btn-sm fw-bold px-4">เพิ่มรายการ</button>
      </div>
    </form>
    {% endif %}

    {% if rates %}
    <div class="card shadow-sm p-3 bg-white">
      <h5 class="fw-bold mb-2 text-center text-primary">📋 โพยร่าง (รอออกบิล)</h5>
      <div class="table-responsive">
        <table class="table table-sm table-bordered text-center align-middle" style="font-size:.85rem">
          <thead class="table-dark"><tr><th>#</th><th>เลข</th><th>ประเภท</th><th>เดิมพัน</th><th>อัตราจ่าย</th><th>ส่วนลด(฿)</th><th>สุทธิ</th><th>สถานะ</th><th></th></tr></thead>
          <tbody>
          {% for d in drafts %}
            <tr>
              <td>{{ loop.index }}</td><td><b>{{ d[1] }}</b></td><td>{{ d[4] }}</td>
              <td>{{ '{:,.2f}'.format(d[2]|float) }}</td><td>{{ d[5]|float }}</td>
              <td class="text-danger">{{ '{:,.2f}'.format(d[6]|float) }}</td>
              <td class="fw-bold text-success">{{ '{:,.2f}'.format(d[7]|float) }}</td>
              <td><span class="badge {% if d[3]=='ปกติ' %}bg-success{% else %}bg-warning text-dark{% endif %}">{{ d[3] }}</span></td>
              <td><form method="POST" action="/portal-delete-item" class="m-0">
                <input type="hidden" name="campaign_id" value="{{ camp.id }}"><input type="hidden" name="customer_id" value="{{ customer_id }}">
                <input type="hidden" name="item_id" value="{{ d[0] }}">
                <button class="btn btn-link btn-sm text-danger p-0 fw-bold">ลบ</button></form></td>
            </tr>
          {% else %}
            <tr><td colspan="9" class="text-muted py-3">ยังไม่มีรายการโพยร่าง</td></tr>
          {% endfor %}
          </tbody>
          {% if drafts %}
          <tfoot class="table-light fw-bold"><tr>
            <td colspan="3" class="text-end">รวม</td><td>{{ '{:,.2f}'.format(totals.amt) }}</td><td></td>
            <td class="text-danger">{{ '{:,.2f}'.format(totals.disc) }}</td><td class="text-success">{{ '{:,.2f}'.format(totals.net) }}</td><td colspan="2"></td>
          </tr></tfoot>
          {% endif %}
        </table>
      </div>
    </div>
    <div class="d-flex gap-2 mt-3">
      <form method="POST" action="/portal-confirm-bill" class="flex-grow-1" onsubmit="return confirm('ยืนยันออกบิลยอดสุทธิ ฿{{ '{:,.2f}'.format(totals.net) }} ?')">
        <input type="hidden" name="campaign_id" value="{{ camp.id }}"><input type="hidden" name="customer_id" value="{{ customer_id }}">
        <button class="btn btn-primary w-100 fw-bold" {% if not drafts or not is_open %}disabled{% endif %}>ยืนยันโพย & ออกบิล</button>
      </form>
      <form method="POST" action="/portal-clear-draft" onsubmit="return confirm('ยืนยันล้างรายการทั้งหมด?')">
        <input type="hidden" name="campaign_id" value="{{ camp.id }}"><input type="hidden" name="customer_id" value="{{ customer_id }}">
        <button class="btn btn-danger fw-bold px-4" {% if not drafts %}disabled{% endif %}>ล้างรายการ</button>
      </form>
    </div>
    {% endif %}
  </div>

  <div class="sidebar-right">
    <h6 class="text-center fw-bold text-danger mb-3">🚫 เลขอั้นประจำงวด</h6>
    <label class="fw-bold small">1. เลขอั้นปิดรับ:</label>
    <textarea class="form-control form-control-sm mb-2 bg-light text-danger fw-bold" rows="3" readonly>{{ block_closed }}</textarea>
    <label class="fw-bold small">2. เลขอั้น 3 ตัวจ่ายครึ่ง:</label>
    <textarea class="form-control form-control-sm mb-2 bg-light" rows="3" readonly>{{ block_3d }}</textarea>
    <label class="fw-bold small">3. เลขอั้น 2 ตัวจ่ายครึ่ง:</label>
    <textarea class="form-control form-control-sm mb-3 bg-light" rows="3" readonly>{{ block_2d }}</textarea>
    <h6 class="fw-bold text-primary">🧾 บิลล่าสุดของผู้ซื้อรายนี้</h6>
    <table class="table table-sm table-bordered bg-white text-center" style="font-size:.75rem">
      {% for b in recent_bills %}
      <tr><td><a href="/bill?{{ b.qs }}"><code>{{ b.bill_no }}</code></a></td><td>฿{{ '{:,.0f}'.format(b.net) }}</td></tr>
      {% else %}<tr><td class="text-muted">ยังไม่มีบิล</td></tr>{% endfor %}
    </table>
  </div>
</div>
{% endblock %}
{% block scripts %}
<script>
(function(){
  var el=document.getElementById('timer'); if(!el) return;
  var s=el.getAttribute('data-seconds');
  if(s===''||s===null){el.textContent='⏰ ไม่ระบุเวลาปิดรับ';el.style.background='#6c757d';return;}
  var left=parseInt(s,10);
  function tick(){
    if(left<=0){el.textContent='⏰ ปิดรับแทงแล้ว';el.style.background='#6c757d';
      if({{ 'true' if is_open else 'false' }}){setTimeout(function(){location.reload()},1000)} return;}
    var h=Math.floor(left/3600),m=Math.floor((left%3600)/60),x=left%60;
    el.textContent='⏳ เหลือเวลา: '+h+'ช. '+m+'น. '+x+'ว.'; left--; setTimeout(tick,1000);
  }
  tick();
})();
function val(id){return document.getElementById(id).value;}
function setPreview(nums){
  var box=document.getElementById('previewContent'); if(!box) return; box.textContent='';
  var s=document.createElement('span'); s.className='text-primary fw-bold'; s.style.wordBreak='break-all'; s.textContent=nums||'-'; box.appendChild(s);
  var d=document.createElement('div'); d.className='w-100 mt-1';
  d.textContent='➡️ บน '+(val('topAmtInput')||'0')+' | ล่าง '+(val('botAmtInput')||'0'); box.appendChild(d);
}
function resetPreview(){
  document.getElementById('hiddenGeneratedNums').value='';
  var box=document.getElementById('previewContent'); box.textContent='preview:-';
}
function refreshPreview(){ document.getElementById('hiddenGeneratedNums').value=''; setPreview(val('mainNumInput')); }
function generated(nums){ setPreview(nums); document.getElementById('hiddenGeneratedNums').value=nums; }
function apply6Box(){
  var n=val('mainNumInput').trim(); if(!/^[0-9]{3}$/.test(n)){alert('กรุณากรอกตัวเลข 3 หลัก');return;}
  var perms=new Set(), a=n.split('');
  (function p(l){ if(l===2){perms.add(a.join(''));return;} for(var i=l;i<3;i++){[a[l],a[i]]=[a[i],a[l]];p(l+1);[a[l],a[i]]=[a[i],a[l]];} })(0);
  generated(Array.from(perms).join(','));
}
function digit1(){ var d=val('mainNumInput').trim(); if(!/^[0-9]$/.test(d)){alert('กรุณากรอกตัวเลข 1 หลัก');return null;} return d; }
function apply19Door(){ var d=digit1(); if(d===null) return; var o=[];
  for(var i=0;i<=9;i++){var a=d+i,b=i+d; if(o.indexOf(a)<0)o.push(a); if(o.indexOf(b)<0)o.push(b);} generated(o.join(',')); }
function applyFrontRoot(){ var d=digit1(); if(d===null) return; var o=[]; for(var i=0;i<=9;i++)o.push(d+i); generated(o.join(',')); }
function applyBackRoot(){ var d=digit1(); if(d===null) return; var o=[]; for(var i=0;i<=9;i++)o.push(i+d); generated(o.join(',')); }
</script>
{% endblock %}"""

BILL = """<!DOCTYPE html>
<html lang="th"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>สลิปบิล {{ bill_no }}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
 body{background:#f8f9fa}
 .slip{max-width:320px;margin:20px auto;background:#fff;padding:15px;border:1px dashed #ccc;font-family:'Courier New',monospace}
 .dash{border-top:1px dashed #000;margin:10px 0}
 .t{width:100%;font-size:.85rem}.t th{border-bottom:1px dashed #000}
 .row2{display:flex;justify-content:space-between;font-size:.85rem}
 @media print{body{background:none}.slip{border:none;margin:0}.no-print{display:none!important}}
</style></head>
<body>
<div class="slip">
  <div class="text-center fw-bold fs-5">{{ lotto }}</div>
  <div class="text-center small">งวดวันที่: {{ draw }}</div>
  <div class="text-center small mt-1">ผู้ซื้อ: {{ customer }}</div>
  <div class="text-center small">แคชเชียร์: {{ cashier }}</div>
  <div class="text-center fw-bold mt-2">{{ bill_no }}</div>
  <div class="text-center small">{{ ts }}</div>
  <div class="dash"></div>
  <table class="t"><thead><tr><th class="text-start">เลข</th><th class="text-start">ประเภท</th><th class="text-end">ราคา</th></tr></thead>
  <tbody>{% for i in items %}<tr><td class="fw-bold">{{ i.num }}</td><td>{{ i.type }}</td><td class="text-end">{{ '{:,.0f}'.format(i.amount) }}</td></tr>{% endfor %}</tbody></table>
  <div class="dash"></div>
  <div class="row2"><span>ยอดรวม:</span><span>{{ '{:,.2f}'.format(total_amt) }}</span></div>
  <div class="row2"><span>ส่วนลด:</span><span>-{{ '{:,.2f}'.format(total_disc) }}</span></div>
  <div class="dash"></div>
  <div class="row2 fw-bold" style="font-size:1.1rem"><span>ยอดสุทธิ:</span><span>{{ '{:,.2f}'.format(total_net) }}</span></div>
  <div class="text-center small mt-3">--- ขอให้โชคดี ---</div>
</div>
<div class="container no-print" style="max-width:320px">
  <button onclick="window.print()" class="btn btn-dark w-100 fw-bold mb-2">🖨️ พิมพ์สลิป</button>
  <a href="{{ back_url }}" class="btn btn-primary w-100 fw-bold mb-3">⬅️ กลับไปหน้าบันทึกโพย</a>
</div>
</body></html>"""

REPORTS = """{% extends "base.html" %}
{% block title %}รายงานผล{% endblock %}
{% block body %}
<div class="container my-4">
  <h3 class="fw-bold text-primary mb-3">📊 รายงานผล & สรุปยอด <small class="text-muted fs-6">(รวมสายงานของคุณทั้งหมด)</small></h3>
  <form method="GET" class="row g-2 bg-white p-3 border rounded shadow-sm mb-3">
    <div class="col-md-4"><label class="form-label small fw-bold">ตั้งแต่วันที่</label><input type="date" name="start_date" class="form-control" value="{{ start_date }}"></div>
    <div class="col-md-4"><label class="form-label small fw-bold">ถึงวันที่</label><input type="date" name="end_date" class="form-control" value="{{ end_date }}"></div>
    <div class="col-md-4 d-flex align-items-end"><button class="btn btn-primary w-100 fw-bold">ค้นหา</button></div>
  </form>
  <div class="row text-center g-2 mb-3">
    <div class="col-md-3"><div class="p-3 bg-white border border-primary rounded"><div class="small">ยอดขายรวม</div><h4 class="text-primary fw-bold">฿{{ '{:,.2f}'.format(tot.amt) }}</h4></div></div>
    <div class="col-md-3"><div class="p-3 bg-white border border-danger rounded"><div class="small">ส่วนลดรวม</div><h4 class="text-danger fw-bold">฿{{ '{:,.2f}'.format(tot.disc) }}</h4></div></div>
    <div class="col-md-3"><div class="p-3 bg-white border border-success rounded"><div class="small">ยอดสุทธิรวม</div><h4 class="text-success fw-bold">฿{{ '{:,.2f}'.format(tot.net) }}</h4></div></div>
    <div class="col-md-3"><div class="p-3 bg-white border border-warning rounded"><div class="small">เงินรางวัล (งวดที่ออกผลแล้ว)</div><h4 class="fw-bold">฿{{ '{:,.2f}'.format(tot.payout) }}</h4></div></div>
  </div>
  <div class="card shadow-sm p-3 mb-3"><h5 class="fw-bold">แยกตามหวย / งวด</h5>
    <div class="table-responsive"><table class="table table-sm table-bordered text-center align-middle">
      <thead class="table-dark"><tr><th>หวย</th><th>งวด</th><th>ยอดขาย</th><th>ส่วนลด</th><th>ยอดสุทธิ</th><th>เงินรางวัล</th><th>สุทธิ − รางวัล</th></tr></thead>
      <tbody>{% for g in groups %}<tr>
        <td class="text-start fw-bold">{{ g.lotto }}</td><td>{{ g.draw }}</td>
        <td>{{ '{:,.2f}'.format(g.amt) }}</td><td class="text-danger">{{ '{:,.2f}'.format(g.disc) }}</td><td>{{ '{:,.2f}'.format(g.net) }}</td>
        {% if g.has_result %}<td class="text-danger fw-bold">{{ '{:,.2f}'.format(g.payout) }}</td>
          <td class="fw-bold {% if g.net - g.payout >= 0 %}text-success{% else %}text-danger{% endif %}">{{ '{:,.2f}'.format(g.net - g.payout) }}</td>
        {% else %}<td colspan="2"><span class="badge bg-secondary">ยังไม่ออกผล</span></td>{% endif %}
      </tr>{% else %}<tr><td colspan="7" class="text-muted">ไม่มีข้อมูลในช่วงเวลานี้</td></tr>{% endfor %}</tbody>
    </table></div></div>
  <div class="card shadow-sm p-3"><h5 class="fw-bold">แยกตามผู้บันทึก</h5>
    <div class="table-responsive"><table class="table table-sm table-bordered text-center align-middle">
      <thead class="table-dark"><tr><th>ผู้ใช้</th><th>ยอดขาย</th><th>ส่วนลด</th><th>ยอดสุทธิ</th><th>เงินรางวัล</th></tr></thead>
      <tbody>{% for u in by_user %}<tr><td class="text-start fw-bold">{{ u.name }}</td>
        <td>{{ '{:,.2f}'.format(u.amt) }}</td><td class="text-danger">{{ '{:,.2f}'.format(u.disc) }}</td>
        <td>{{ '{:,.2f}'.format(u.net) }}</td><td>{{ '{:,.2f}'.format(u.payout) }}</td></tr>
      {% else %}<tr><td colspan="5" class="text-muted">ไม่มีข้อมูล</td></tr>{% endfor %}</tbody>
    </table></div></div>
</div>
{% endblock %}"""

USERS = """{% extends "base.html" %}{% from "macros.html" import rate_fields, num %}
{% block title %}จัดการผู้ใช้{% endblock %}
{% block body %}
<div class="container-fluid my-4 px-4"><div class="row">
  <div class="col-lg-4 mb-4"><div class="card shadow p-4">
    {% if edit_user %}
      <h5 class="fw-bold text-warning">✏️ แก้ไข: {{ edit_user.username }} <span class="badge bg-secondary">{{ edit_user.role }}</span></h5>
      <form method="POST" action="/admin-users/update">
        <input type="hidden" name="user_id" value="{{ edit_user.id }}">
        <div class="mb-3"><label class="form-label small fw-bold">ตั้งรหัสผ่านใหม่ (เว้นว่าง = ไม่เปลี่ยน)</label>
          <input type="password" name="new_password" class="form-control form-control-sm" autocomplete="new-password"></div>
        {{ rate_fields(edit_user.rates) }}
        <button class="btn btn-warning w-100 fw-bold mb-2">💾 บันทึก</button>
        <a href="/admin-users" class="btn btn-outline-secondary w-100 fw-bold">ยกเลิก</a>
      </form>
    {% elif can_create %}
      <h5 class="fw-bold text-success">➕ สร้างสมาชิกใต้สายงาน</h5>
      <form method="POST" action="/admin-users/create">
        <div class="mb-2"><label class="form-label small fw-bold">Username (a-z 0-9 _ . -  3-50 ตัว)</label>
          <input type="text" name="new_username" class="form-control form-control-sm" required pattern="[A-Za-z0-9_.\\-]{3,50}"></div>
        <div class="mb-2"><label class="form-label small fw-bold">Password (อย่างน้อย 6 ตัว)</label>
          <input type="password" name="new_password" class="form-control form-control-sm" required minlength="6" autocomplete="new-password"></div>
        <div class="mb-2"><label class="form-label small fw-bold">ระดับสิทธิ์</label>
          <select name="new_role" class="form-select form-select-sm">{% for r in creatable %}<option>{{ r }}</option>{% endfor %}</select></div>
        {{ rate_fields(defaults) }}
        <button class="btn btn-success w-100 fw-bold">💾 บันทึกสมาชิก</button>
      </form>
    {% else %}<div class="alert alert-info mb-0">บัญชีระดับ {{ user.role }} ไม่สามารถสร้างสมาชิกได้</div>{% endif %}
  </div></div>
  <div class="col-lg-8"><div class="card shadow p-4">
    <h5 class="fw-bold text-primary">🗂️ รายชื่อสมาชิก{% if user.role == 'Admin' %}ทั้งระบบ{% else %}ใต้สายงาน{% endif %}</h5>
    <div class="table-responsive"><table class="table table-striped table-bordered text-center align-middle" style="font-size:.85rem">
      <thead class="table-dark"><tr><th>ID</th><th>Username</th><th>สิทธิ์</th><th>สายบน</th><th>3ตรง</th><th>2ตัว</th><th>วิ่งบน/ล่าง</th><th>ลดรวม%</th><th></th></tr></thead>
      <tbody>{% for u in users_list %}<tr>
        <td>{{ u[0] }}</td><td><b>{{ u[1] }}</b></td><td><span class="badge bg-secondary">{{ u[2] }}</span></td><td>{{ u[3] or '-' }}</td>
        <td>{{ u[4]|float }}</td><td>{{ u[5]|float }}</td><td>{{ u[6]|float }}/{{ u[7]|float }}</td><td>{{ u[8]|float }}</td>
        <td><a href="/admin-users?edit_id={{ u[0] }}" class="btn btn-warning btn-sm fw-bold py-0">✏️ แก้ไข</a></td>
      </tr>{% else %}<tr><td colspan="9" class="text-muted">ยังไม่มีสมาชิก</td></tr>{% endfor %}</tbody>
    </table></div>
  </div></div>
</div></div>
{% endblock %}"""

CUSTOMERS = """{% extends "base.html" %}{% from "macros.html" import rate_fields %}
{% block title %}จัดการลูกค้า{% endblock %}
{% block body %}
<div class="container-fluid my-4 px-4"><div class="row">
  <div class="col-lg-4 mb-4"><div class="card shadow p-4">
    {% if edit_customer %}
      <h5 class="fw-bold text-warning">✏️ แก้ไขลูกค้า</h5>
      <form method="POST" action="/manage-customers/update">
        <input type="hidden" name="customer_id" value="{{ edit_customer.id }}">
        <div class="mb-3"><label class="form-label small fw-bold">ชื่อลูกค้า</label>
          <input type="text" name="name" class="form-control form-control-sm" value="{{ edit_customer.name }}" required maxlength="100"></div>
        {{ rate_fields(edit_customer.rates) }}
        <button class="btn btn-warning w-100 fw-bold mb-2">💾 บันทึก</button>
        <a href="/manage-customers" class="btn btn-outline-secondary w-100 fw-bold">ยกเลิก</a>
      </form>
    {% else %}
      <h5 class="fw-bold text-success">➕ เพิ่มลูกค้าใหม่</h5>
      <form method="POST" action="/manage-customers/create">
        <div class="mb-3"><label class="form-label small fw-bold">ชื่อลูกค้า</label>
          <input type="text" name="name" class="form-control form-control-sm" required maxlength="100"></div>
        {{ rate_fields(defaults) }}
        <button class="btn btn-success w-100 fw-bold">บันทึกลูกค้า</button>
      </form>
    {% endif %}
  </div></div>
  <div class="col-lg-8"><div class="card shadow p-4">
    <h5 class="fw-bold text-primary">👥 รายชื่อลูกค้า</h5>
    <div class="table-responsive"><table class="table table-striped table-bordered text-center align-middle" style="font-size:.85rem">
      <thead class="table-dark"><tr><th>ID</th><th>ชื่อ</th>{% if user.role == 'Admin' %}<th>เจ้าของ</th>{% endif %}<th>3ตรง</th><th>2ตัว</th><th>วิ่งบน/ล่าง</th><th>ลดรวม%</th><th></th></tr></thead>
      <tbody>{% for c in customers_list %}<tr>
        <td>{{ c[0] }}</td><td><b>{{ c[1] }}</b></td>{% if user.role == 'Admin' %}<td>{{ c[2] }}</td>{% endif %}
        <td>{{ c[3]|float }}</td><td>{{ c[4]|float }}</td><td>{{ c[5]|float }}/{{ c[6]|float }}</td><td>{{ c[7]|float }}</td>
        <td><a href="/manage-customers?edit_id={{ c[0] }}" class="btn btn-warning btn-sm fw-bold py-0">✏️ แก้ไข</a></td>
      </tr>{% else %}<tr><td colspan="8" class="text-muted">ยังไม่มีลูกค้า</td></tr>{% endfor %}</tbody>
    </table></div>
  </div></div>
</div></div>
{% endblock %}"""

RATES = """{% extends "base.html" %}{% from "macros.html" import rate_fields %}
{% block title %}เรตแยกตามหวย{% endblock %}
{% block body %}
<div class="container my-4" style="max-width:900px">
  <h3 class="fw-bold mb-3 text-warning">⚙️ กำหนดเรตและส่วนลดพิเศษ แยกตามหวย</h3>
  <div class="card shadow p-4 bg-white mb-4">
    <form method="POST" action="/save-lotto-rate">
      <div class="row g-3 mb-3">
        <div class="col-md-6"><label class="form-label fw-bold small">เลือกหวย:</label>
          <select name="lotto_name" class="form-select form-select-sm" required>
            {% for l in lotto_list %}<option value="{{ l }}" {% if l == sel_lotto %}selected{% endif %}>{{ l }}</option>{% endfor %}
          </select></div>
        <div class="col-md-6"><label class="form-label fw-bold small">เลือกลูกค้า / ผู้ใช้:</label>
          <select name="target_id" class="form-select form-select-sm" required>
            {% for t in targets %}<option value="{{ t.key }}" {% if t.key == sel_target %}selected{% endif %}>{{ t.label }}</option>{% endfor %}
          </select></div>
      </div>
      {{ rate_fields(vals) }}
      <button class="btn btn-warning w-100 fw-bold">💾 บันทึกเรตเฉพาะหวยนี้</button>
    </form>
  </div>
  <div class="card shadow-sm p-3 bg-white"><h6 class="fw-bold">เรตที่ตั้งไว้แล้ว (กด "แก้" เพื่อโหลดค่าเดิมเข้าฟอร์ม)</h6>
    <div class="table-responsive"><table class="table table-sm table-bordered text-center" style="font-size:.8rem">
      <thead class="table-dark"><tr><th>ผู้ซื้อ</th><th>หวย</th><th>3ตรง</th><th>โต๊ด</th><th>2ตัว</th><th>วิ่งบน/ล่าง</th><th>ลด 3/2/วิ่ง/รวม %</th><th></th></tr></thead>
      <tbody>{% for r in existing %}<tr>
        <td class="text-start">{{ r.label }}</td><td>{{ r.lotto }}</td><td>{{ r.v.pay_3d }}</td><td>{{ r.v.pay_3tod }}</td><td>{{ r.v.pay_2d }}</td>
        <td>{{ r.v.pay_run_top }}/{{ r.v.pay_run_bot }}</td><td>{{ r.v.disc_3d }}/{{ r.v.disc_2d }}/{{ r.v.disc_run }}/{{ r.v.disc_total }}</td>
        <td><a class="btn btn-sm btn-outline-primary py-0" href="/customer-rates-page?{{ r.qs }}">แก้</a></td>
      </tr>{% else %}<tr><td colspan="8" class="text-muted">ยังไม่มีเรตแยกหวย</td></tr>{% endfor %}</tbody>
    </table></div>
  </div>
</div>
{% endblock %}"""

PASSWORD = """{% extends "base.html" %}
{% block title %}เปลี่ยนรหัสผ่าน{% endblock %}
{% block body %}
<div class="container my-5" style="max-width:480px"><div class="card shadow p-4">
  <h4 class="fw-bold text-primary mb-3">🔑 เปลี่ยนรหัสผ่าน</h4>
  <form method="POST" action="/change-password">
    <div class="mb-3"><label class="form-label fw-bold">รหัสผ่านปัจจุบัน</label><input type="password" name="old_password" class="form-control" required autocomplete="current-password"></div>
    <div class="mb-3"><label class="form-label fw-bold">รหัสผ่านใหม่ (อย่างน้อย 6 ตัว)</label><input type="password" name="new_password" class="form-control" required minlength="6" autocomplete="new-password"></div>
    <div class="mb-3"><label class="form-label fw-bold">ยืนยันรหัสผ่านใหม่</label><input type="password" name="confirm_password" class="form-control" required minlength="6" autocomplete="new-password"></div>
    <button class="btn btn-primary w-100 fw-bold">💾 บันทึกรหัสผ่าน</button>
  </form>
</div></div>
{% endblock %}"""

env = Environment(
    loader=DictLoader({
        "base.html": BASE, "macros.html": MACROS, "login.html": LOGIN, "live_sales.html": LIVE_SALES, "select_market.html": SELECT_MARKET,
        "portal.html": PORTAL, "bill.html": BILL, "reports.html": REPORTS, "users.html": USERS,
        "customers.html": CUSTOMERS, "rates.html": RATES, "password.html": PASSWORD,
    }),
    autoescape=True,   # ป้องกัน XSS ทุกจุด (ของเดิมใช้ Template() ที่ไม่ escape)
)


# ============================================================ Login / Logout

@app.get("/", response_class=HTMLResponse)
def index():
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", user=None)


@app.post("/login")
def login_action(request: Request, username: str = Form(...), password: str = Form(...)):
    key = f"{request.client.host if request.client else '?'}|{username.lower()}"
    if _throttled(key):
        return redir("/login", error="ล็อกอินผิดหลายครั้ง กรุณารอ 5 นาที")
    with db() as conn:
        c = conn.cursor()
        c.execute("SELECT username, password FROM Users WHERE username=%s", (username,))
        row = c.fetchone()
    if not row or not common.verify_password(row[1], password):
        _FAILS.setdefault(key, []).append(time.time())
        return redir("/login", error="Username หรือ Password ไม่ถูกต้อง")
    resp = redir("/select-market")
    resp.set_cookie(common.SESSION_COOKIE, common.make_session(row[0]), max_age=common.SESSION_TTL,
                    httponly=True, samesite="lax", secure=os.environ.get("COOKIE_SECURE", "0") == "1")
    return resp


@app.get("/live-sales", response_class=HTMLResponse)
def live_sales_page(request: Request):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if me["role"] != "Admin":
            return redir("/select-market", error="เมนูนี้สำหรับแอดมินเท่านั้น")
        inner = common.render_live_sales(c, "/live-sales-data")
    return render(request, "live_sales.html", user=me, inner=inner)


@app.get("/live-sales-data")
def live_sales_data_api(request: Request, node: str = "", f: str = ""):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me or me["role"] != "Admin":
            return JSONResponse({"error": "forbidden"}, status_code=403)
        data = common.live_sales_data(c, me["username"], node or me["username"], f)
    return JSONResponse(data)


@app.get("/logout")
def logout():
    resp = redir("/login")
    resp.delete_cookie(common.SESSION_COOKIE)
    return resp


# ============================================================ เลือกตลาด

@app.get("/select-market", response_class=HTMLResponse)
def select_market(request: Request):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        c.execute("SELECT id, lotto_name, draw_date, status, open_time, close_time, result_timestamp FROM LotteryCampaigns "
                  "ORDER BY id DESC LIMIT 300")
        rows = [dict(id=r[0], lotto_name=r[1], draw_date=r[2], status=r[3], open_time=r[4], close_time=r[5],
                     result_timestamp=r[6]) for r in c.fetchall()]
    cards_html = common.render_campaign_cards(rows, lambda r: f"/portal?campaign_id={r['id']}", show_old_toggle=True)
    return render(request, "select_market.html", user=me, cards_html=cards_html)


# ============================================================ หน้าคีย์โพย

def _draft_filter():
    return "username=%s AND customer_id=%s AND customer_type=%s AND lotto_name=%s AND draw_date=%s"


@app.get("/portal", response_class=HTMLResponse)
def portal_page(request: Request, campaign_id: int, customer_id: str = None):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        camp = common.get_campaign(c, campaign_id)
        if not camp:
            return redir("/select-market", error="ไม่พบงวดหวยนี้")
        targets = common.get_targets(c, me)
        keys = [t["key"] for t in targets]
        if customer_id not in keys:
            customer_id = keys[0]
        current = next(t for t in targets if t["key"] == customer_id)

        rates, source = common.get_rates(c, customer_id, camp["lotto_name"])
        eff = None
        if rates:
            eff = {"d3": common.disc_pct(rates, "3d"), "d2": common.disc_pct(rates, "2d"),
                   "drun": common.disc_pct(rates, "run")}

        is_open, reason = common.campaign_open(camp)
        t_type, t_id = common.parse_target(customer_id)
        c.execute(f"SELECT id, num, amt_teng, status, type, payout_rate, discount, net FROM TempDraft "
                  f"WHERE {_draft_filter()} ORDER BY id",
                  (me["username"], str(t_id), t_type, camp["lotto_name"], camp["draw_date"]))
        drafts = c.fetchall()
        totals = {"amt": sum(float(d[2] or 0) for d in drafts),
                  "disc": sum(float(d[6] or 0) for d in drafts),
                  "net": sum(float(d[7] or 0) for d in drafts)}

        b_closed, b_3d, b_2d = common.get_blocked_display(c, camp["lotto_name"], camp["draw_date"])

        c.execute("SELECT bill_no, SUM(net) FROM Transactions WHERE username=%s AND customer_id=%s AND "
                  "customer_type=%s AND lotto_name=%s AND draw_date=%s GROUP BY bill_no ORDER BY MAX(id) DESC LIMIT 10",
                  (me["username"], t_id, t_type, camp["lotto_name"], camp["draw_date"]))
        recent = [{"bill_no": r[0], "net": float(r[1] or 0),
                   "qs": urlencode({"bill_no": r[0], "campaign_id": camp["id"], "customer_id": customer_id})}
                  for r in c.fetchall()]

    return render(request, "portal.html", user=me, camp=camp, targets=targets, customer_id=customer_id,
                  current_name=current["label"], rates=rates, rate_source=source, eff=eff,
                  is_open=is_open, closed_reason=reason, seconds_left=common.seconds_until(camp["close_time"]),
                  drafts=drafts, totals=totals, block_closed=b_closed, block_3d=b_3d, block_2d=b_2d,
                  recent_bills=recent)


def _portal_back(campaign_id, customer_id, **kw):
    return redir("/portal", campaign_id=campaign_id, customer_id=customer_id, **kw)


@app.post("/portal-add-draft")
def portal_add_draft(request: Request, campaign_id: int = Form(...), customer_id: str = Form(...),
                     num_input: str = Form(""), generated_nums: str = Form(""),
                     top_amt: float = Form(0), bot_amt: float = Form(0)):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        back = lambda **kw: _portal_back(campaign_id, customer_id, **kw)
        camp = common.get_campaign(c, campaign_id)
        if not camp:
            return redir("/select-market", error="ไม่พบงวดหวยนี้")
        if customer_id not in [t["key"] for t in common.get_targets(c, me)]:
            return back(error="คุณไม่มีสิทธิ์บันทึกโพยให้ผู้ซื้อรายนี้")
        ok, reason = common.campaign_open(camp)
        if not ok:
            return back(error=reason)
        if not (0 <= top_amt <= MAX_AMOUNT and 0 <= bot_amt <= MAX_AMOUNT):
            return back(error=f"จำนวนเงินต้องอยู่ระหว่าง 0 ถึง {MAX_AMOUNT:,}")
        if top_amt <= 0 and bot_amt <= 0:
            return back(error="กรุณาระบุจำนวนเงินอย่างน้อย 1 ช่อง")

        rates, _ = common.get_rates(c, customer_id, camp["lotto_name"])
        if not rates:
            return back(error="ไม่พบเรตของผู้ซื้อรายนี้")

        src = generated_nums.strip() or num_input
        raw = list(dict.fromkeys(n.strip() for n in src.replace(" ", ",").split(",") if n.strip()))
        if len(raw) > MAX_NUMS_PER_SUBMIT:
            return back(error=f"เพิ่มได้ครั้งละไม่เกิน {MAX_NUMS_PER_SUBMIT} เลข")
        valid = [n for n in raw if re.fullmatch(r"[0-9]{1,3}", n)]
        invalid = [n for n in raw if n not in valid]

        blocked = common.get_blocked_map(c, camp["lotto_name"], camp["draw_date"])
        t_type, t_id = common.parse_target(customer_id)
        rows, rejected = [], []
        for n in valid:
            st = blocked.get(n, "ปกติ")
            if st == "ปิดรับ":
                rejected.append(n)
                continue
            for amt, (ptype, pay_key, kind) in zip((top_amt, bot_amt), PLAYS[len(n)]):
                if amt <= 0:
                    continue
                disc_amt = round(amt * common.disc_pct(rates, kind) / 100.0, 2)   # เก็บเป็น "บาท"
                rows.append((me["username"], str(t_id), t_type, n, amt, ptype, rates[pay_key],
                             disc_amt, round(amt - disc_amt, 2), st, camp["lotto_name"], camp["draw_date"]))
        if rows:
            c.executemany(
                "INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, "
                "discount, net, status, lotto_name, draw_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)

    warn = []
    if rejected:
        warn.append("เลขปิดรับ ไม่ได้บันทึก: " + ", ".join(rejected[:30]))
    if invalid:
        warn.append("เลขไม่ถูกต้อง (ต้องเป็นตัวเลข 1-3 หลัก): " + ", ".join(invalid[:30]))
    if not rows and not warn:
        warn.append("ไม่มีรายการที่บันทึกได้")
    return back(msg=f"เพิ่ม {len(rows)} รายการ" if rows else None, error=" | ".join(warn) or None)


@app.post("/portal-delete-item")
def portal_delete_item(request: Request, campaign_id: int = Form(...), customer_id: str = Form(...),
                       item_id: int = Form(...)):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        c.execute("DELETE FROM TempDraft WHERE id=%s AND username=%s", (item_id, me["username"]))
    return _portal_back(campaign_id, customer_id)


@app.post("/portal-clear-draft")
def portal_clear_draft(request: Request, campaign_id: int = Form(...), customer_id: str = Form(...)):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        camp = common.get_campaign(c, campaign_id)
        if not camp:
            return redir("/select-market", error="ไม่พบงวดหวยนี้")
        try:
            t_type, t_id = common.parse_target(customer_id)
        except ValueError:
            return redir("/select-market", error="ข้อมูลผู้ซื้อไม่ถูกต้อง")
        c.execute(f"DELETE FROM TempDraft WHERE {_draft_filter()}",
                  (me["username"], str(t_id), t_type, camp["lotto_name"], camp["draw_date"]))
    return _portal_back(campaign_id, customer_id, msg="ล้างรายการร่างแล้ว")


@app.post("/portal-confirm-bill")
def portal_confirm_bill(request: Request, campaign_id: int = Form(...), customer_id: str = Form(...)):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        back = lambda **kw: _portal_back(campaign_id, customer_id, **kw)
        camp = common.get_campaign(c, campaign_id)
        if not camp:
            return redir("/select-market", error="ไม่พบงวดหวยนี้")
        targets = common.get_targets(c, me)
        if customer_id not in [t["key"] for t in targets]:
            return back(error="คุณไม่มีสิทธิ์ออกบิลให้ผู้ซื้อรายนี้")
        ok, reason = common.campaign_open(camp)
        if not ok:
            return back(error=reason + " ไม่สามารถออกบิลได้")

        t_type, t_id = common.parse_target(customer_id)
        # FOR UPDATE: กันกดยืนยันซ้ำ/สองแท็บพร้อมกัน แถวร่างจะถูกใช้ได้แค่ครั้งเดียว
        c.execute(f"SELECT id, num, type, amt_teng, payout_rate, discount, net FROM TempDraft "
                  f"WHERE {_draft_filter()} ORDER BY id FOR UPDATE",
                  (me["username"], str(t_id), t_type, camp["lotto_name"], camp["draw_date"]))
        drafts = c.fetchall()
        if not drafts:
            return back(error="ไม่มีรายการในโพยร่าง")

        # ตรวจเลขอั้นซ้ำอีกครั้ง เผื่อแอดมินเพิ่งเพิ่มเลขอั้นหลังจากคีย์ร่างไว้
        blocked = common.get_blocked_map(c, camp["lotto_name"], camp["draw_date"])
        now_closed = sorted({d[1] for d in drafts if blocked.get(d[1]) == "ปิดรับ"})
        if now_closed:
            return back(error="มีเลขที่เพิ่งถูกปิดรับ กรุณาลบออกก่อนออกบิล: " + ", ".join(now_closed))

        cust_name = common.get_target_name(c, t_type, t_id)
        if cust_name is None:
            return back(error="ไม่พบข้อมูลผู้ซื้อ")
        bill_no = common.generate_bill_no(c, camp["lotto_name"], camp["draw_date"], t_type, t_id)
        ts = common.get_thai_time().strftime("%d/%m/%Y %H:%M:%S")      # ฟอร์แมตเดียวกับระบบหลัก
        c.executemany(
            "INSERT INTO Transactions (draw_date, timestamp, username, customer_id, customer_name, customer_type, "
            "bill_no, num, type, amount, status, discount, net, payout_rate, lotto_name) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(camp["draw_date"], ts, me["username"], t_id, cust_name, t_type, bill_no, d[1], d[2], d[3],
              blocked.get(d[1], "ปกติ"), d[5], d[6], d[4], camp["lotto_name"]) for d in drafts])
        c.execute("DELETE FROM TempDraft WHERE id = ANY(%s)", ([d[0] for d in drafts],))
    return redir("/bill", bill_no=bill_no, campaign_id=campaign_id, customer_id=customer_id)


@app.get("/bill", response_class=HTMLResponse)
def bill_page(request: Request, bill_no: str, campaign_id: int = None, customer_id: str = None):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        c.execute("SELECT username, timestamp, customer_name, lotto_name, draw_date, num, type, amount, discount, net "
                  "FROM Transactions WHERE bill_no=%s ORDER BY id", (bill_no,))
        rows = c.fetchall()
        if not rows:
            return redir("/select-market", error="ไม่พบบิลนี้")
        if me["role"] != "Admin" and rows[0][0] not in common.get_subtree(c, me["username"]):
            return redir("/select-market", error="คุณไม่มีสิทธิ์ดูบิลนี้")
    back_url = "/select-market"
    if campaign_id and customer_id:
        back_url = "/portal?" + urlencode({"campaign_id": campaign_id, "customer_id": customer_id})
    items = [{"num": r[5], "type": r[6], "amount": float(r[7] or 0)} for r in rows]
    return HTMLResponse(env.get_template("bill.html").render(
        bill_no=bill_no, lotto=rows[0][3], draw=rows[0][4], customer=rows[0][2], cashier=rows[0][0], ts=rows[0][1],
        items=items, total_amt=sum(i["amount"] for i in items),
        total_disc=sum(float(r[8] or 0) for r in rows), total_net=sum(float(r[9] or 0) for r in rows),
        back_url=back_url))


# ============================================================ รายงานผล  (/agent-reports)

def _parse_date(s, end=False):
    from datetime import datetime
    try:
        d = datetime.strptime(s, "%Y-%m-%d") if s else None
    except ValueError:
        return None
    return d.replace(hour=23, minute=59, second=59) if (d and end) else d


@app.get("/agent-reports", response_class=HTMLResponse)
def agent_reports(request: Request, start_date: str = None, end_date: str = None):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        sql = ("SELECT username, COALESCE(lotto_name,'ไม่ระบุหวย'), draw_date, timestamp, amount, discount, net, "
               "num, type, payout_rate FROM Transactions")
        if me["role"] == "Admin":
            c.execute(sql)
        else:
            c.execute(sql + " WHERE username = ANY(%s)", (common.get_subtree(c, me["username"]),))
        rows = c.fetchall()
        c.execute("SELECT draw_date, prize_1, bottom_2 FROM DrawResults")
        results = {r[0]: (str(r[1] or "").strip(), str(r[2] or "").strip()) for r in c.fetchall()}
        c.execute("SELECT draw_date, lotto_name, raw_num FROM BlockedNumbers WHERE status <> 'ปิดรับ'")
        half_rows = c.fetchall()

    sd, ed = _parse_date(start_date), _parse_date(end_date, end=True)
    groups, by_user = {}, {}
    for uname, lotto, draw, ts, amt, disc, net, num, ttype, rate in rows:
        t = common.parse_timestamp(ts)
        if sd or ed:
            if not t or (sd and t < sd) or (ed and t > ed):
                continue
        groups.setdefault((lotto, draw), []).append((uname, float(amt or 0), float(disc or 0), float(net or 0), num, ttype, rate))

    out_groups, tot = [], {"amt": 0.0, "disc": 0.0, "net": 0.0, "payout": 0.0}
    for (lotto, draw), items in sorted(groups.items(), key=lambda kv: (kv[0][1] or "", kv[0][0]), reverse=True):
        res = common.find_result(results, draw)
        half = {str(n).strip() for d, l, n in half_rows if n and common._draw_match(draw, d) and (l is None or l == lotto)}
        g = {"lotto": lotto, "draw": draw, "amt": 0.0, "disc": 0.0, "net": 0.0, "payout": 0.0, "has_result": bool(res)}
        for uname, amt, disc, net, num, ttype, rate in items:
            pay = common.row_payout(num, ttype, amt, rate, res[0], res[1], half) if res else 0.0
            g["amt"] += amt; g["disc"] += disc; g["net"] += net; g["payout"] += pay
            u = by_user.setdefault(uname, {"name": uname, "amt": 0.0, "disc": 0.0, "net": 0.0, "payout": 0.0})
            u["amt"] += amt; u["disc"] += disc; u["net"] += net; u["payout"] += pay
        for k in tot:
            tot[k] += g[k]
        out_groups.append(g)

    return render(request, "reports.html", user=me, groups=out_groups, tot=tot,
                  by_user=sorted(by_user.values(), key=lambda x: -x["amt"]),
                  start_date=start_date or "", end_date=end_date or "")


# ============================================================ จัดการผู้ใช้  (/admin-users)

_USER_COLS = "id, username, role, parent_user, pay_3d, pay_2d, pay_run_top, pay_run_bot, disc_total"


def _row_rates(row, keys):
    return {k: (float(v) if v is not None else RATE_DEFAULTS[k]) for k, v in zip(keys, row)}


@app.get("/admin-users", response_class=HTMLResponse)
def admin_users_page(request: Request, edit_id: int = None):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if not is_manager(me):
            return redir("/select-market", error="บัญชีของคุณไม่มีสิทธิ์จัดการผู้ใช้")
        # แสดง/แก้ไขเฉพาะผู้ใช้ที่ตัวเองเป็น upline โดยตรง (ทุกบทบาท รวมแอดมิน) — ลูกข่ายชั้นลึกลงไปเป็นหน้าที่ upline ของเขา
        kids = [r[0] for r in common.direct_children(c, me)]
        c.execute(f"SELECT {_USER_COLS} FROM Users WHERE id = ANY(%s) ORDER BY id DESC", (kids,))
        users_list = c.fetchall()
        edit_user = None
        if edit_id:
            row = next((r for r in users_list if r[0] == edit_id), None)   # แก้ไขได้เฉพาะคนในรายการที่เห็น
            if row:
                c.execute(f"SELECT {', '.join(RATE_KEYS)} FROM Users WHERE id=%s", (edit_id,))
                edit_user = {"id": row[0], "username": row[1], "role": row[2], "rates": _row_rates(c.fetchone(), RATE_KEYS)}
    creatable = common.CREATABLE_ROLES[me["role"]]
    return render(request, "users.html", user=me, users_list=users_list, edit_user=edit_user,
                  creatable=creatable, can_create=bool(creatable), defaults=RATE_DEFAULTS)


@app.post("/admin-users/create")
def admin_users_create(request: Request, new_username: str = Form(...), new_password: str = Form(...),
                       new_role: str = Form(...), rf: RateForm = Depends()):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if new_role not in common.CREATABLE_ROLES[me["role"]]:
            return redir("/admin-users", error="คุณไม่มีสิทธิ์สร้างผู้ใช้ระดับนี้")
        new_username = new_username.strip()
        if not USERNAME_RE.match(new_username):
            return redir("/admin-users", error="Username ใช้ได้เฉพาะ a-z A-Z 0-9 _ . - ความยาว 3-50 ตัว")
        if len(new_password) < 6:
            return redir("/admin-users", error="รหัสผ่านต้องมีอย่างน้อย 6 ตัว")
        c.execute("SELECT 1 FROM Users WHERE LOWER(username)=LOWER(%s)", (new_username,))
        if c.fetchone():
            return redir("/admin-users", error="มี Username นี้อยู่แล้ว")
        v = rf.values
        over = common.check_rates_within(c, me, v)
        if over:
            return redir("/admin-users", error=over)
        c.execute(f"INSERT INTO Users (username, password, role, parent_user, {', '.join(RATE_KEYS)}) "
                  f"VALUES (%s,%s,%s,%s,{', '.join(['%s'] * len(RATE_KEYS))})",
                  (new_username, common.store_password(new_password), new_role, me["username"], *[v[k] for k in RATE_KEYS]))
    return redir("/admin-users", msg=f"สร้างสมาชิก {new_username} สำเร็จ")


@app.post("/admin-users/update")
def admin_users_update(request: Request, user_id: int = Form(...), new_password: str = Form(""),
                       rf: RateForm = Depends()):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        c.execute("SELECT username, parent_user FROM Users WHERE id=%s", (user_id,))
        t = c.fetchone()
        allowed = t and user_id != me["id"] and common.is_direct_child(c, me, user_id)
        if not allowed or not is_manager(me):
            return redir("/admin-users", error="แก้ไขได้เฉพาะผู้ใช้ที่คุณเป็น upline โดยตรง (ไม่สามารถแก้เรตของตัวเองได้)")
        v = rf.values
        over = common.check_rates_within(c, me, v)
        if over:
            return redir("/admin-users", edit_id=user_id, error=over)
        sets = ", ".join(f"{k}=%s" for k in RATE_KEYS)
        c.execute(f"UPDATE Users SET {sets} WHERE id=%s", (*[v[k] for k in RATE_KEYS], user_id))
        if new_password:
            if len(new_password) < 6:
                conn.rollback()
                return redir("/admin-users", edit_id=user_id, error="รหัสผ่านต้องมีอย่างน้อย 6 ตัว")
            c.execute("UPDATE Users SET password=%s WHERE id=%s", (common.store_password(new_password), user_id))
    return redir("/admin-users", msg=f"บันทึกข้อมูล {t[0]} สำเร็จ")


# ============================================================ จัดการลูกค้า  (/manage-customers)

_CUST_COLS = "id, name, owner_username, pay_3d, pay_2d, pay_run_top, pay_run_bot, disc_total"


@app.get("/manage-customers", response_class=HTMLResponse)
def manage_customers_page(request: Request, edit_id: int = None):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if not is_manager(me):
            return redir("/select-market", error="บัญชีของคุณไม่มีสิทธิ์จัดการลูกค้า")
        c.execute(f"SELECT {_CUST_COLS} FROM Customers WHERE LOWER(owner_username)=LOWER(%s) ORDER BY id DESC",
                  (me["username"],))
        customers_list = c.fetchall()
        edit_customer = None
        if edit_id and any(r[0] == edit_id for r in customers_list):
            c.execute(f"SELECT name, {', '.join(RATE_KEYS)} FROM Customers WHERE id=%s", (edit_id,))
            row = c.fetchone()
            edit_customer = {"id": edit_id, "name": row[0], "rates": _row_rates(row[1:], RATE_KEYS)}
    return render(request, "customers.html", user=me, customers_list=customers_list,
                  edit_customer=edit_customer, defaults=RATE_DEFAULTS)


@app.post("/manage-customers/create")
def manage_customers_create(request: Request, name: str = Form(...), rf: RateForm = Depends()):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if not is_manager(me):
            return redir("/select-market", error="บัญชีของคุณไม่มีสิทธิ์เพิ่มลูกค้า")
        name = name.strip()[:100]
        if not name:
            return redir("/manage-customers", error="กรุณาระบุชื่อลูกค้า")
        v = rf.values
        over = common.check_rates_within(c, me, v)
        if over:
            return redir("/manage-customers", error=over)
        c.execute(f"INSERT INTO Customers (name, owner_username, discount_type, {', '.join(RATE_KEYS)}) "
                  f"VALUES (%s,%s,1,{', '.join(['%s'] * len(RATE_KEYS))})",
                  (name, me["username"], *[v[k] for k in RATE_KEYS]))
    return redir("/manage-customers", msg=f"เพิ่มลูกค้า {name} สำเร็จ")


@app.post("/manage-customers/update")
def manage_customers_update(request: Request, customer_id: int = Form(...), name: str = Form(...),
                            rf: RateForm = Depends()):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        c.execute("SELECT owner_username FROM Customers WHERE id=%s", (customer_id,))
        r = c.fetchone()
        if not r or not is_manager(me) or (r[0] or "").lower() != me["username"].lower():
            return redir("/manage-customers", error="แก้ไขได้เฉพาะลูกค้าที่คุณเป็นผู้สร้าง")
        name = name.strip()[:100]
        if not name:
            return redir("/manage-customers", edit_id=customer_id, error="กรุณาระบุชื่อลูกค้า")
        v = rf.values
        over = common.check_rates_within(c, me, v)
        if over:
            return redir("/manage-customers", edit_id=customer_id, error=over)
        sets = ", ".join(f"{k}=%s" for k in RATE_KEYS)
        c.execute(f"UPDATE Customers SET name=%s, {sets} WHERE id=%s", (name, *[v[k] for k in RATE_KEYS], customer_id))
    return redir("/manage-customers", msg="แก้ไขลูกค้าสำเร็จ")


# ============================================================ เรตแยกตามหวย

@app.get("/customer-rates-page", response_class=HTMLResponse)
def customer_rates_page(request: Request, target_id: str = None, lotto_name: str = None):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if not is_manager(me):
            return redir("/select-market", error="บัญชีของคุณไม่มีสิทธิ์ตั้งเรต")
        targets = common.get_rate_targets(c, me)      # ลูกค้าของตัวเอง + ผู้ใช้ที่ตัวเองเป็น upline โดยตรง (ไม่รวมตัวเอง)
        label = {t["key"]: t["label"] for t in targets}
        c.execute("SELECT DISTINCT lotto_name FROM LotteryCampaigns WHERE lotto_name IS NOT NULL ORDER BY lotto_name")
        lotto_list = [r[0] for r in c.fetchall()]
        cols = ", ".join(RATE_KEYS)
        keys = list(label)
        existing = []
        if keys:
            c.execute(f"SELECT target_id, lotto_name, {cols} FROM CustomerLottoRates WHERE target_id = ANY(%s) "
                      f"ORDER BY id DESC", (keys,))
            seen = set()
            for r in c.fetchall():
                if (r[0], r[1]) in seen:
                    continue
                seen.add((r[0], r[1]))
                existing.append({"label": label[r[0]], "lotto": r[1], "v": _row_rates(r[2:], RATE_KEYS),
                                 "qs": urlencode({"target_id": r[0], "lotto_name": r[1]})})
        vals = dict(RATE_DEFAULTS)
        if target_id in label and lotto_name:
            hit = next((e for e in existing if e["qs"] == urlencode({"target_id": target_id, "lotto_name": lotto_name})), None)
            if hit:
                vals = hit["v"]
            else:
                base, _ = common.get_rates(c, target_id, lotto_name)
                vals = base or vals
    return render(request, "rates.html", user=me, targets=targets, lotto_list=lotto_list, existing=existing,
                  vals=vals, sel_target=target_id, sel_lotto=lotto_name)


@app.post("/save-lotto-rate")
def save_lotto_rate(request: Request, target_id: str = Form(...), lotto_name: str = Form(...),
                    rf: RateForm = Depends()):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if not is_manager(me):
            return redir("/select-market", error="บัญชีของคุณไม่มีสิทธิ์ตั้งเรต")
        try:
            t_type, t_id = common.parse_target(target_id)
        except ValueError:
            return redir("/customer-rates-page", error="ผู้ซื้อไม่ถูกต้อง")
        if not common.can_set_rates_for(c, me, t_type, t_id):
            return redir("/customer-rates-page", error="ตั้งเรตได้เฉพาะลูกค้าที่คุณสร้างและผู้ใช้ที่คุณเป็น upline โดยตรง (ตั้งให้ตัวเองไม่ได้)")
        lotto_name = common.clean_name(lotto_name)
        if not lotto_name:
            return redir("/customer-rates-page", error="กรุณาเลือกหวย")
        v = rf.values
        over = common.check_rates_within(c, me, v, lotto_name)
        if over:
            return redir("/customer-rates-page", target_id=target_id, lotto_name=lotto_name, error=over)
        # ลบ+เพิ่มใน transaction เดียว (ถ้า INSERT พัง DELETE จะถูก rollback ให้เอง)
        c.execute("DELETE FROM CustomerLottoRates WHERE target_id=%s AND lotto_name=%s", (target_id, lotto_name))
        c.execute(f"INSERT INTO CustomerLottoRates (customer_id, target_type, target_id, lotto_name, {', '.join(RATE_KEYS)}) "
                  f"VALUES (%s,%s,%s,%s,{', '.join(['%s'] * len(RATE_KEYS))})",
                  (t_id if t_type == "Customer" else None, t_type, target_id, lotto_name, *[v[k] for k in RATE_KEYS]))
    return redir("/customer-rates-page", target_id=target_id, lotto_name=lotto_name,
                 msg=f"บันทึกเรตหวย '{lotto_name}' สำเร็จ")


# ============================================================ เปลี่ยนรหัสผ่าน

@app.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    with db() as conn:
        me = get_me(conn.cursor(), request)
    if not me:
        return to_login()
    return render(request, "password.html", user=me)


@app.post("/change-password")
def change_password_action(request: Request, old_password: str = Form(...), new_password: str = Form(...),
                           confirm_password: str = Form(...)):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if new_password != confirm_password:
            return redir("/change-password", error="รหัสผ่านใหม่ไม่ตรงกัน")
        if len(new_password) < 6:
            return redir("/change-password", error="รหัสผ่านต้องมีอย่างน้อย 6 ตัว")
        c.execute("SELECT password FROM Users WHERE id=%s", (me["id"],))
        row = c.fetchone()
        if not row or not common.verify_password(row[0], old_password):
            return redir("/change-password", error="รหัสผ่านเดิมไม่ถูกต้อง")
        c.execute("UPDATE Users SET password=%s WHERE id=%s", (common.store_password(new_password), me["id"]))
    return redir("/change-password", msg="เปลี่ยนรหัสผ่านสำเร็จ")


# ============================================================ เมนูแอดมินทั้งหมด (เหมือนระบบหลัก)
# เส้นทาง/พารามิเตอร์ใช้ชื่อเดียวกับระบบหลัก  ผู้ใช้มาจาก session cookie เสมอ (พารามิเตอร์ user/username ที่ส่งมาจะถูกเมิน)

ADM_SYSTEM_RESET_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>LuckyNumber - System Reset (Go-Live)</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-danger-subtle d-flex align-items-center justify-content-center" style="height: 100vh;">
    <div class="card shadow-lg p-5 border border-danger border-3 bg-white" style="max-width: 600px; width: 100%;">
        <div class="text-center mb-4">
            <i class="fa-solid fa-triangle-exclamation text-danger fa-4x mb-3"></i>
            <h2 class="text-danger fw-bold">⚠️ พื้นที่อันตราย: รีเซ็ตระบบเพื่อใช้งานจริง (Factory Reset)</h2>
            <p class="text-muted small mt-2">คำสั่งนี้จะล้างข้อมูลการทดสอบทั้งหมดในฐานข้อมูลออกอย่างถาวร (โพย, ลูกค้า, สมาชิกทดสอบ, เลขอั้น, เรต, และงวดหวย) เพื่อให้ระบบสะอาดพร้อมเริ่มต้นใช้งานจริง</p>
        </div>

        {% if error %}
        <div class="alert alert-danger text-center fw-bold">{{ error }}</div>
        {% endif %}

        <form method="POST" action="/execute-system-reset" onsubmit="return confirm('⚠️ คำเตือนขั้นเด็ดขาด! คุณแน่ใจจริงๆ หรือไม่ที่จะล้างข้อมูลทั้งหมดในระบบออก? ข้อมูลที่ถูกลบจะไม่สามารถกู้คืนได้!');">
            <input type="hidden" name="username" value="{{ username }}">
            
            <div class="mb-3">
                <label class="form-label fw-bold text-dark">🔑 ยืนยันรหัสผ่าน Admin ของคุณ:</label>
                <input type="password" name="admin_password" class="form-control form-control-lg" placeholder="กรอกรหัสผ่านเพื่อยืนยัน..." required autofocus>
            </div>

            <div class="d-grid gap-2 mt-4">
                <button type="submit" class="btn btn-danger btn-lg fw-bold py-3">
                    <i class="fa-solid fa-bomb"></i> ยืนยันล้างข้อมูลและรีเซ็ตระบบทั้งหมด
                </button>
                <a href="/campaigns?user={{ username }}" class="btn btn-outline-secondary btn-lg fw-bold py-2">
                    ❌ ยกเลิกและกลับสู่หน้าหลัก
                </a>
            </div>
        </form>
    </div>
</body>
</html>
"""

ADM_CAMPAIGN_TEMPLATE = """
<div class="container-fluid my-3 px-3">
    {% if missing_close_time_campaigns %}
    <div class="alert alert-danger border border-danger shadow p-3 mb-4 rounded">
        <h5 class="fw-bold text-danger"><i class="fa-solid fa-triangle-exclamation"></i> แจ้งเตือนสำคัญ: พบงวดหวยที่ยังไม่ได้กำหนด "เวลาปิดรับ" จำนวน {{ missing_close_time_campaigns | length }} งวด</h5>
        <ul class="mb-0 fw-bold text-danger">
            {% for mc in missing_close_time_campaigns %}
                <li>งวด: {{ mc['draw_date'] }} (ID: {{ mc['id'] }}) — <a href="/campaigns?user={{ username }}&edit_id={{ mc['id'] }}" class="btn btn-sm btn-outline-danger py-0 fw-bold">แก้ไขด่วนที่นี่</a></li>
            {% endfor %}
        </ul>
    </div>
    {% endif %}

    <div class="card bg-white p-4 shadow border mb-4">
        <h2 class="text-center text-primary mb-4 fw-bold">📌 จัดการและเลือกงวดหวย</h2>
        
        {% if role == 'Admin' %}
            {% if edit_campaign %}
            <div class="card bg-warning-subtle p-3 mb-4 border border-warning">
                <h5 class="text-dark mb-3 fw-bold">✏️ แก้ไขงวดหวยและเวลาปิดรับ</h5>
                <form method="POST" action="/update-campaign">
                    <input type="hidden" name="user" value="{{ username }}">
                    <input type="hidden" name="campaign_id" value="{{ edit_campaign[3] }}">
                    <div class="mb-2">
                        <label class="form-label fw-bold text-dark">ชื่อหวย:</label>
                        <input type="text" name="lotto_name" class="form-control" value="{{ edit_campaign[0] }}" required>
                    </div>
                    <div class="mb-2">
                        <label class="form-label fw-bold text-dark">งวดวันที่:</label>
                        <input type="text" name="draw_date" class="form-control" value="{{ edit_campaign[1] }}" required>
                    </div>
                    <div class="row mb-3">
                        <div class="col-md-6"><label class="form-label fw-bold text-success">🟢 เวลาเปิดรับแทง:</label>
                        <input type="datetime-local" name="open_time" class="form-control" value="{{ edit_campaign[5] or '' }}" required></div>
                        <div class="col-md-6"><label class="form-label fw-bold text-danger">⏰ เวลาปิดรับแทง:</label>
                        <input type="datetime-local" name="close_time" class="form-control" value="{{ edit_campaign[4] or '' }}" required></div>
                        <div class="form-text">ระบบเปิด-ปิดรับให้อัตโนมัติตามเวลาที่กำหนด (ก่อนเวลาเปิด/หลังเวลาปิดจะบันทึกโพยไม่ได้)</div>
                    </div>
                    <div class="d-flex gap-2">
                        <button type="submit" class="btn btn-warning w-100 fw-bold py-2">💾 บันทึกการแก้ไข</button>
                        <a href="/campaigns?user={{ username }}" class="btn btn-outline-dark w-100 fw-bold py-2">ยกเลิก</a>
                    </div>
                </form>
            </div>
            {% else %}
            <div class="card bg-light p-3 mb-4 border border-primary">
                <h5 class="text-primary mb-3 fw-bold">➕ เปิดงวดหวยใหม่ (Admin)</h5>
                <form method="POST" action="/create-campaign">
                    <input type="hidden" name="user" value="{{ username }}">
                    <div class="mb-2">
                        <label class="form-label fw-bold text-dark">ชื่อหวย:</label>
                        <input type="text" name="lotto_name" class="form-control" placeholder="เช่น หวยรัฐบาล, หวยลาว" required>
                    </div>
                    <div class="mb-2">
                        <label class="form-label fw-bold text-dark">งวดวันที่:</label>
                        <input type="text" name="draw_date" class="form-control" placeholder="เช่น 16 ตุลาคม 2026" required>
                    </div>
                    <div class="row mb-3">
                        <div class="col-md-6"><label class="form-label fw-bold text-success">🟢 เวลาเปิดรับแทง:</label>
                        <input type="datetime-local" name="open_time" class="form-control" value="{{ now_local }}" required></div>
                        <div class="col-md-6"><label class="form-label fw-bold text-danger">⏰ เวลาปิดรับแทง:</label>
                        <input type="datetime-local" name="close_time" class="form-control" required></div>
                        <div class="form-text">ระบบเปิด-ปิดรับให้อัตโนมัติตามเวลาที่กำหนด</div>
                    </div>
                    <button type="submit" class="btn btn-primary w-100 fw-bold py-2">เปิดงวดใหม่ (กำหนดเวลาเปิด-ปิดรับ)</button>
                </form>
            </div>
            {% endif %}
        {% endif %}
        
        {{ cards_html|safe }}
    </div>
</div>
"""

ADM_BLOCKED_TEMPLATE = """
<div class="row">
    <div class="col-md-5 mb-4">
        <div class="card shadow p-4">
            {% if edit_blocked %}
                <h4 class="text-warning mb-3 fw-bold">✏️ แก้ไขเลขอั้น</h4>
                <form method="POST" action="/update-blocked">
                    <input type="hidden" name="user" value="{{ username }}">
                    <input type="hidden" name="draw" value="{{ draw_date }}">
                    <input type="hidden" name="blocked_id" value="{{ edit_blocked[0] }}">
                    <div class="mb-3"><label class="form-label fw-bold">หมายเลขเลขอั้น:</label><input type="text" name="raw_num" class="form-control" value="{{ edit_blocked[2] }}" required></div>
                    <div class="mb-3"><label class="form-label fw-bold">สถานะ:</label><select name="status" class="form-select"><option value="ปิดรับ" {% if edit_blocked[3] == 'ปิดรับ' %}selected{% endif %}>ปิดรับ</option><option value="จ่ายครึ่ง" {% if edit_blocked[3] == 'จ่ายครึ่ง' %}selected{% endif %}>จ่ายครึ่ง</option></select></div>
                    <button type="submit" class="btn btn-warning w-100 fw-bold mb-2">💾 บันทึก</button>
                    <a href="/blocked-numbers?user={{ username }}&draw={{ draw_date|urlencode }}" class="btn btn-outline-secondary w-100 fw-bold">ยกเลิก</a>
                </form>
            {% else %}
                <h4 class="text-danger mb-3 fw-bold">🚫 นำเข้าเลขอั้น</h4>
                <form method="POST" action="/save-blocked">
                    <input type="hidden" name="user" value="{{ username }}">
                    <input type="hidden" name="draw" value="{{ draw_date }}">
                    <div class="mb-3"><label class="form-label fw-bold">ข้อมูลดิบ (ใช้คอมม่าคั่น):</label><textarea name="raw_input" class="form-control" rows="5" required autofocus></textarea></div>
                    <div class="mb-3"><label class="form-label fw-bold">สถานะ:</label><select name="status" class="form-select"><option value="ปิดรับ">ปิดรับ</option><option value="จ่ายครึ่ง">จ่ายครึ่ง</option></select></div>
                    <button type="submit" class="btn btn-danger w-100 fw-bold py-2">💾 ประมวลผลเลขอั้น</button>
                </form>
            {% endif %}
        </div>
    </div>
    <div class="col-md-7">
        <div class="card shadow p-4">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="text-primary mb-0 fw-bold">📋 รายการเลขอั้นงวดนี้</h4>
                {% if blocked_list %}
                <a href="/clear-blocked?user={{ username }}&draw={{ draw_date|urlencode }}" class="btn btn-outline-danger btn-sm fw-bold" onclick="return confirm('⚠️ ล้างข้อมูลทั้งหมด?')">🗑️ ล้างข้อมูลเลขอั้น</a>
                {% endif %}
            </div>
            <div class="table-responsive" style="max-height: 500px; overflow-y: auto;">
                <table class="table table-striped table-bordered text-center align-middle" style="font-size: 0.9rem;">
                    <thead class="table-dark sticky-top">
                        <tr><th>ID</th><th>หมายเลข</th><th>สถานะ</th><th>ประเภท</th><th>จัดการ</th></tr>
                    </thead>
                    <tbody>
                        {% for b in blocked_list %}
                        <tr>
                            <td>{{ b[0] }}</td><td><b class="text-danger fs-6">{{ b[2] }}</b></td><td><span class="badge {% if b[3] == 'ปิดรับ' %}bg-danger{% else %}bg-warning text-dark{% endif %}">{{ b[3] }}</span></td><td>{{ b[4] }}</td>
                            <td><a href="/blocked-numbers?user={{ username }}&draw={{ draw_date|urlencode }}&edit_id={{ b[0] }}" class="btn btn-warning btn-sm py-0 px-1 fw-bold">✏️</a> <a href="/delete-blocked?id={{ b[0] }}&user={{ username }}&draw={{ draw_date|urlencode }}" class="btn btn-outline-danger btn-sm py-0 px-1 fw-bold">🗑️</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>
"""

ADM_RESULTS_CONTENT = """
<div class="card shadow p-4 mb-4">
    <h2 class="text-success mb-3 fw-bold">🏆 บันทึกผลการออกรางวัลประจำงวด</h2>
    <form method="POST" action="/save-results" class="row g-3">
        <input type="hidden" name="user" value="{{ username }}">
        <input type="hidden" name="draw" value="{{ draw_date }}">
        <div class="col-md-6">
            <label class="form-label fw-bold text-dark">รางวัลที่ 1 (3 ตัวตรง):</label>
            <input type="text" name="prize_1" class="form-control form-control-lg" value="{{ prize_1 }}" required>
        </div>
        <div class="col-md-6">
            <label class="form-label fw-bold text-dark">เลขท้าย 2 ตัว:</label>
            <input type="text" name="bottom_2" class="form-control form-control-lg" value="{{ bottom_2 }}" required>
        </div>
        <div class="col-12">
            <button type="submit" class="btn btn-success btn-lg w-100 fw-bold">💾 บันทึกและคำนวณผลชนะ/แพ้</button>
        </div>
    </form>
</div>

<div class="card shadow p-4">
    <h3 class="text-primary mb-3 fw-bold">📊 รายงานสรุปผลรางวัล (แพ้/ชนะ)</h3>
    <div class="row text-center mb-4">
        <div class="col-md-6 mb-2"><div class="p-3 bg-white border rounded shadow-sm"><h5>จ่ายเงินรางวัลรวม</h5><h3 class="text-danger fw-bold">฿{{ "{:,.2f}".format(total_payout) }}</h3></div></div>
        <div class="col-md-6 mb-2"><div class="p-3 bg-warning text-dark border rounded shadow-sm"><h5>กำไรสุทธิ (หลังหักจ่าย)</h5><h3 class="fw-bold">฿{{ "{:,.2f}".format(total_net - total_payout) }}</h3></div></div>
    </div>
    <div class="table-responsive">
        <table class="table table-striped table-bordered text-center align-middle">
            <thead class="table-dark">
                <tr><th>ลูกค้า</th><th>ผู้บันทึก</th><th>หมายเลข</th><th>ประเภท</th><th>ยอดซื้อ</th><th>เงินรางวัลที่ได้รับ</th></tr>
            </thead>
            <tbody>
                {% for w in winners %}
                <tr>
                    <td><b>{{ w[0] }}</b></td><td><span class="badge bg-secondary">{{ w[1] }}</span></td><td><code class="fs-5">{{ w[2] }}</code></td><td>{{ w[3] }}</td><td>{{ "{:,.2f}".format(w[4] | float) }}</td><td class="text-success fw-bold fs-5">฿{{ "{:,.2f}".format(w[6] | float) }}</td>
                </tr>
                {% else %}
                <tr><td colspan="6" class="text-muted">ยังไม่มีผู้ถูกรางวัลในงวดนี้</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
"""

ADM_DASHBOARD_CONTENT = """
<div class="card shadow p-4 mb-4">
    <h2 class="text-primary mb-3 fw-bold"><i class="fa-solid fa-chart-pie"></i> แดชบอร์ดสรุปยอดขาย</h2>
    
    <!-- ฟอร์มเลือกช่วงเวลา -->
    <form method="GET" action="/dashboard" class="row g-3 mb-4 bg-light p-3 border rounded shadow-sm">
        <input type="hidden" name="user" value="{{ username }}">
        <input type="hidden" name="draw" value="{{ draw_date }}">
        <div class="col-md-4">
            <label class="form-label fw-bold text-dark">📅 ตั้งแต่วันที่:</label>
            <input type="date" name="start_date" class="form-control" value="{{ start_date }}">
        </div>
        <div class="col-md-4">
            <label class="form-label fw-bold text-dark">📅 ถึงวันที่:</label>
            <input type="date" name="end_date" class="form-control" value="{{ end_date }}">
        </div>
        <div class="col-md-4 d-flex align-items-end">
            <button type="submit" class="btn btn-primary w-100 fw-bold"><i class="fa-solid fa-magnifying-glass"></i> ค้นหาข้อมูล</button>
        </div>
    </form>

    <!-- สรุปยอดรวม -->
    <div class="row text-center mb-4">
        <div class="col-md-6 mb-2">
            <div class="p-3 bg-white border border-primary border-2 rounded shadow-sm">
                <h5 class="text-muted fw-bold">ยอดขายรวมช่วงเวลาที่เลือก</h5>
                <h1 class="text-primary fw-bold">฿{{ "{:,.2f}".format(total_sales) }}</h1>
            </div>
        </div>
        <div class="col-md-6 mb-2">
            <div class="p-3 bg-white border border-success border-2 rounded shadow-sm">
                <h5 class="text-muted fw-bold">ยอดสุทธิรวม</h5>
                <h1 class="text-success fw-bold">฿{{ "{:,.2f}".format(total_net) }}</h1>
            </div>
        </div>
    </div>
</div>

<div class="row">
    <!-- รายละเอียดแบ่งตามผู้ใช้ -->
    <div class="col-md-6 mb-4">
        <div class="card shadow p-3 h-100 border-0">
            <h5 class="text-dark fw-bold mb-3"><i class="fa-solid fa-users"></i> ยอดขายแยกตามผู้ใช้ / เอเย่นต์</h5>
            <ul class="list-group list-group-flush">
                {% for user_sale in user_sales %}
                <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent">
                    <span class="fw-bold text-dark">{{ user_sale[0] }}</span>
                    <span class="badge bg-primary rounded-pill fs-6 px-3 py-2 shadow-sm">฿{{ "{:,.2f}".format(user_sale[1]) }}</span>
                </li>
                {% else %}
                <li class="list-group-item text-muted text-center">ไม่มีข้อมูลในช่วงเวลานี้</li>
                {% endfor %}
            </ul>
        </div>
    </div>
    
    <!-- รายละเอียดแบ่งตามประเภทหวย -->
    <div class="col-md-6 mb-4">
        <div class="card shadow p-3 h-100 border-0">
            <h5 class="text-dark fw-bold mb-3"><i class="fa-solid fa-ticket"></i> ยอดขายแยกตามประเภทหวย</h5>
            <ul class="list-group list-group-flush">
                {% for lotto_sale in lotto_sales %}
                <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent">
                    <span class="fw-bold text-dark">{{ lotto_sale[0] }}</span>
                    <span class="badge bg-danger rounded-pill fs-6 px-3 py-2 shadow-sm">฿{{ "{:,.2f}".format(lotto_sale[1]) }}</span>
                </li>
                {% else %}
                <li class="list-group-item text-muted text-center">ไม่มีข้อมูลในช่วงเวลานี้</li>
                {% endfor %}
            </ul>
        </div>
    </div>
</div>
"""

ADM_AUDIT_ALL_CONTENT = """
<div class="card shadow p-4">
    <h2 class="text-primary mb-4 fw-bold">🔍 ตรวจสอบรายการซื้อทั้งหมดในระบบ</h2>
    <div class="table-responsive">
        <table class="table table-striped table-bordered text-center align-middle">
            <thead class="table-dark">
                <tr><th>เวลาทำรายการ</th><th>เลขที่บิล</th><th>ผู้บันทึก</th><th>ลูกค้า</th><th>ประเภท</th><th>หมายเลข</th><th>ยอดซื้อ</th><th>อัตราจ่าย</th></tr>
            </thead>
            <tbody>
                {% for r in audit_rows %}
                <tr>
                    <td><small>{{ r[2] }}</small></td><td><code>{{ r[7] }}</code></td><td><span class="badge bg-secondary">{{ r[3] }}</span></td><td><b>{{ r[5] }}</b></td><td>{{ r[9] }}</td><td><b class="text-primary">{{ r[8] }}</b></td><td>{{ "{:,.2f}".format(r[10] | float) }}</td><td><span class="badge bg-success">{{ r[14] }}</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
"""

ADM_AUDIT_DISCOUNT_CONTENT = """
<div class="card shadow p-4">
    <h2 class="text-primary mb-3 fw-bold">🔍 ตรวจสอบส่วนลดลูกค้า</h2>
    <div class="table-responsive mt-3">
        <table class="table table-striped table-bordered text-center align-middle">
            <thead class="table-dark">
                <tr><th>เวลา</th><th>เลขที่บิล</th><th>ลูกค้า</th><th>ประเภท</th><th>หมายเลข</th><th>ยอดซื้อ</th><th>ส่วนลด</th><th>ยอดสุทธิ</th></tr>
            </thead>
            <tbody>
                {% for r in discount_rows %}
                <tr>
                    <td><small>{{ r[2] }}</small></td><td><code>{{ r[7] }}</code></td><td><b>{{ r[5] }}</b></td><td>{{ r[9] }}</td><td><b class="text-primary">{{ r[8] }}</b></td><td>{{ "{:,.2f}".format(r[10] | float) }}</td><td class="text-danger fw-bold">{{ "{:,.2f}".format(r[12] | float) }}</td><td class="text-success fw-bold">{{ "{:,.2f}".format(r[13] | float) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
"""

ADM_DB_INSPECTOR_TEMPLATE = """
<div class="card shadow p-4">
    <h2 class="text-primary mb-3 fw-bold">🗄️ Database Inspector</h2>
    <form method="GET" action="/db-inspector" class="mb-4">
        <input type="hidden" name="user" value="{{ username }}">
        <input type="hidden" name="draw" value="{{ draw_date }}">
        <select name="table_name" class="form-select form-select-lg" onchange="this.form.submit()">
            {% for t in tables %}
                <option value="{{ t }}" {% if selected_table == t %}selected{% endif %}>{{ t }}</option>
            {% endfor %}
        </select>
    </form>
    {% if selected_table %}
        <div class="table-responsive">
            <table class="table table-striped table-bordered text-center">
                <thead class="table-dark">
                    <tr>{% for col in columns %}<th>{{ col }}</th>{% endfor %}</tr>
                </thead>
                <tbody>
                    {% for r in rows %}
                    <tr>{% for val in r %}<td>{{ val }}</td>{% endfor %}</tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    {% endif %}
</div>
"""


ADMIN_PAGE = """{% extends "base.html" %}
{% block body %}
<div class="container-fluid my-3 px-3">
{% if draw_date %}
<div class="alert alert-dark py-2 d-flex flex-wrap gap-2 align-items-center">
  <b class="me-2">งวด: {{ draw_date }}</b>
  <a class="btn btn-sm btn-outline-primary" href="/blocked-numbers?draw={{ draw_date|urlencode }}">🚫 เลขอั้น</a>
  <a class="btn btn-sm btn-outline-success" href="/results?draw={{ draw_date|urlencode }}">🏆 ผลรางวัล</a>
  <a class="btn btn-sm btn-outline-primary" href="/audit-all?draw={{ draw_date|urlencode }}">🔍 ตรวจสอบทั้งหมด</a>
  <a class="btn btn-sm btn-outline-primary" href="/audit-discount?draw={{ draw_date|urlencode }}">🔍 ส่วนลด</a>
  <a class="btn btn-sm btn-outline-secondary" href="/admin-pick?to=/blocked-numbers">เปลี่ยนงวด</a>
</div>
{% endif %}
{{ content|safe }}
</div>
{% endblock %}"""

ADMIN_PICK = """{% extends "base.html" %}
{% block body %}
<div class="container-fluid my-3 px-3"><div class="card p-4 shadow">
<h3 class="fw-bold text-primary text-center mb-1">{{ title }}</h3>
<p class="text-center text-muted">เลือกงวดที่ต้องการ</p>
{{ cards_html|safe }}
</div></div>
{% endblock %}"""

env.loader.mapping.update({"admin_page.html": ADMIN_PAGE, "admin_pick.html": ADMIN_PICK})

_PICK_TITLES = {"/blocked-numbers": "🚫 จัดการเลขอั้น", "/results": "🏆 ออกผลรางวัล", "/audit-all": "🔍 ตรวจสอบรายการทั้งหมด",
                "/audit-discount": "🔍 ตรวจสอบส่วนลดลูกค้า", "/dashboard": "📊 แดชบอร์ด"}


def _split_draw(draw):
    """'หวยลาว งวด 16 ตุลาคม 2026' -> ('หวยลาว', '16 ตุลาคม 2026')"""
    draw = (draw or "").strip()
    if " งวด " in draw:
        name, d = draw.split(" งวด ", 1)
        return name.strip(), d.strip()
    if "งวด " in draw:
        return "", draw.split("งวด ", 1)[1].strip()
    return "", draw


def _csrf_ok(request):
    return request.headers.get("sec-fetch-site", "same-origin") != "cross-site"


def _admin_gate(c, request, mutating=False):
    """คืน (me, None) ถ้าเป็นแอดมิน ไม่เช่นนั้น (None, response)"""
    me = get_me(c, request)
    if not me:
        return None, to_login()
    if me["role"] != "Admin":
        return None, redir("/select-market", error="เมนูนี้สำหรับแอดมินเท่านั้น")
    if mutating and not _csrf_ok(request):
        return None, redir("/campaigns", error="คำขอถูกปฏิเสธ (cross-site)")
    return me, None


def _close_time(c, draw_clean):
    if not draw_clean:
        return None
    c.execute("SELECT close_time FROM LotteryCampaigns WHERE draw_date = %s OR draw_date ILIKE %s ORDER BY id DESC LIMIT 1",
              (draw_clean, f"%{common.like_escape(draw_clean)}%"))
    r = c.fetchone()
    return r[0] if r and r[0] else None


def _admin_render(request, me, template, draw_date="", **ctx):
    content = env.from_string(template).render(username=me["username"], role=me["role"], draw_date=draw_date, **ctx)
    return render(request, "admin_page.html", user=me, content=content, draw_date=draw_date)


def _pick_draw(request, me, c, to):
    c.execute("SELECT id, lotto_name, draw_date, status, open_time, close_time, result_timestamp FROM LotteryCampaigns "
              "ORDER BY id DESC LIMIT 300")
    rows = [dict(id=r[0], lotto_name=r[1], draw_date=r[2], status=r[3], open_time=r[4], close_time=r[5], result_timestamp=r[6])
            for r in c.fetchall()]
    href = lambda r: to + "?" + urlencode({"draw": f"{common.clean_name(r['lotto_name'])} งวด {common.clean_name(r['draw_date'])}"})
    cards = common.render_campaign_cards(rows, href, show_old_toggle=True)
    return render(request, "admin_pick.html", user=me, title=_PICK_TITLES.get(to, "เลือกงวด"), cards_html=cards)


@app.get("/admin-pick", response_class=HTMLResponse)
def admin_pick(request: Request, to: str = "/blocked-numbers"):
    if to not in _PICK_TITLES:
        to = "/blocked-numbers"
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request)
        if bad:
            return bad
        return _pick_draw(request, me, c, to)


# ---------------- จัดการงวด ----------------

def _campaign_times(open_time, close_time):
    ot, ct = common.normalize_dt(open_time), common.normalize_dt(close_time)
    if not ot or not ct:
        return None, None, "กรุณาระบุเวลาเปิดรับและเวลาปิดรับให้ถูกต้อง"
    if ct <= ot:
        return None, None, "เวลาปิดรับต้องอยู่หลังเวลาเปิดรับ"
    return ot, ct, None


@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_page(request: Request, edit_id: int = None):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request)
        if bad:
            return bad
        c.execute("SELECT id, lotto_name, draw_date, status, open_time, close_time, result_timestamp "
                  "FROM LotteryCampaigns ORDER BY id DESC LIMIT 400")
        rows = [dict(id=r[0], lotto_name=r[1], draw_date=r[2], status=r[3], open_time=r[4], close_time=r[5],
                     result_timestamp=r[6]) for r in c.fetchall()]
        missing = [{"id": r["id"], "draw_date": r["draw_date"]} for r in rows if not r["close_time"] and r["status"] == "Active"]
        edit_campaign = None
        if edit_id:
            c.execute("SELECT lotto_name, draw_date, status, id, close_time, open_time FROM LotteryCampaigns WHERE id=%s", (edit_id,))
            edit_campaign = c.fetchone()

    def actions(r):
        d = f"{common.clean_name(r['lotto_name'])} งวด {common.clean_name(r['draw_date'])}"
        q = urlencode({"draw": d})
        return [("✏️ แก้ไข", "/campaigns?" + urlencode({"edit_id": r["id"]})),
                ("🔁 เปิด/ปิดงวด", "/toggle-campaign?" + urlencode({"id": r["id"]})),
                ("🚫 เลขอั้น", "/blocked-numbers?" + q), ("🏆 ผลรางวัล", "/results?" + q)]

    cards_html = common.render_campaign_cards(rows, lambda r: f"/portal?campaign_id={r['id']}", actions, show_old_toggle=True)
    return _admin_render(request, me, ADM_CAMPAIGN_TEMPLATE, missing_close_time_campaigns=missing, edit_campaign=edit_campaign,
                         cards_html=cards_html, now_local=common.get_thai_time().strftime("%Y-%m-%dT%H:%M"))


@app.get("/create-campaign")
@app.get("/update-campaign")
def campaign_get_fallback(request: Request):
    return redir("/campaigns", error="ส่งฟอร์มไม่สำเร็จ (คำขอไม่ใช่ POST) กรุณากรอกแล้วกดปุ่มบนหน้านี้อีกครั้ง")


@app.post("/create-campaign")
def create_campaign(request: Request, lotto_name: str = Form(...), draw_date: str = Form(...),
                    open_time: str = Form(...), close_time: str = Form(...), user: str = Form("")):
    lotto_name, draw_date = common.clean_name(lotto_name), common.clean_name(draw_date)
    ot, ct, err = _campaign_times(open_time, close_time)
    if err or not lotto_name or not draw_date:
        return redir("/campaigns", error=err or "กรุณาระบุชื่อหวยและงวด")
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        c.execute("INSERT INTO LotteryCampaigns (lotto_name, draw_date, status, open_time, close_time) VALUES (%s,%s,'Active',%s,%s)",
                  (lotto_name, draw_date, ot, ct))
    return redir("/campaigns", msg="สร้างงวดหวยสำเร็จ")


@app.post("/update-campaign")
def update_campaign(request: Request, campaign_id: int = Form(...), lotto_name: str = Form(...), draw_date: str = Form(...),
                    open_time: str = Form(...), close_time: str = Form(...), user: str = Form("")):
    lotto_name, draw_date = common.clean_name(lotto_name), common.clean_name(draw_date)
    ot, ct, err = _campaign_times(open_time, close_time)
    if err or not lotto_name or not draw_date:
        return redir("/campaigns", edit_id=campaign_id, error=err or "กรุณาระบุชื่อหวยและงวด")
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        c.execute("UPDATE LotteryCampaigns SET lotto_name=%s, draw_date=%s, open_time=%s, close_time=%s WHERE id=%s",
                  (lotto_name, draw_date, ot, ct, campaign_id))
    return redir("/campaigns", msg="แก้ไขสำเร็จ")


@app.get("/toggle-campaign")
def toggle_campaign(request: Request, id: int):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        c.execute("SELECT status FROM LotteryCampaigns WHERE id=%s", (id,))
        curr = c.fetchone()
        if curr:
            c.execute("UPDATE LotteryCampaigns SET status=%s, result_timestamp=NULL WHERE id=%s",
                      ("Closed" if curr[0] == "Active" else "Active", id))
    return redir("/campaigns")


# ---------------- เลขอั้น ----------------

@app.get("/blocked-numbers", response_class=HTMLResponse)
def blocked_numbers_page(request: Request, draw: str = "", edit_id: int = None):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request)
        if bad:
            return bad
        if not draw:
            return _pick_draw(request, me, c, "/blocked-numbers")
        c.execute("SELECT id, draw_date, raw_num, status, type, is_raw FROM BlockedNumbers "
                  "WHERE (draw_date = %s OR draw_date ILIKE %s) ORDER BY id DESC", (draw, f"%{common.like_escape(draw)}%"))
        blocked_list = c.fetchall()
        edit_blocked = None
        if edit_id:
            c.execute("SELECT id, draw_date, raw_num, status, type FROM BlockedNumbers WHERE id=%s", (edit_id,))
            edit_blocked = c.fetchone()
    return _admin_render(request, me, ADM_BLOCKED_TEMPLATE, draw_date=draw, blocked_list=blocked_list, edit_blocked=edit_blocked)


@app.post("/save-blocked")
def save_blocked(request: Request, draw: str = Form(...), raw_input: str = Form(...),
                 block_status: str = Form(..., alias="status"), user: str = Form("")):
    if block_status not in ("ปิดรับ", "จ่ายครึ่ง"):
        return redir("/blocked-numbers", draw=draw, error="สถานะไม่ถูกต้อง")
    lotto_name, _ = _split_draw(draw)
    cleaned = raw_input.replace("\r\n", ",").replace("\n", ",").replace(" ", ",")
    insert_data, seen = [], set()
    for num_str in [i.strip() for i in cleaned.split(",") if i.strip()]:
        if not num_str.isdigit() or len(num_str) > 3:
            continue
        t_val = "3ตัว" if len(num_str) == 3 else ("2ตัว" if len(num_str) == 2 else "วิ่ง")
        if num_str not in seen:
            insert_data.append((draw.strip(), num_str, block_status, t_val, True, lotto_name or None))
            seen.add(num_str)
        for p_num in set("".join(p) for p in itertools.permutations(num_str)):
            if p_num not in seen:
                insert_data.append((draw.strip(), p_num, block_status, t_val, False, lotto_name or None))
                seen.add(p_num)
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        if insert_data:
            c.executemany("INSERT INTO BlockedNumbers (draw_date, raw_num, status, type, is_raw, lotto_name) "
                          "VALUES (%s,%s,%s,%s,%s,%s)", insert_data)
    return redir("/blocked-numbers", draw=draw, msg="บันทึกเลขอั้นสำเร็จ")


@app.post("/update-blocked")
def update_blocked(request: Request, draw: str = Form(...), blocked_id: int = Form(...), raw_num: str = Form(...),
                   block_status: str = Form(..., alias="status"), user: str = Form("")):
    n = raw_num.strip()
    t_val = "3ตัว" if len(n) == 3 else ("2ตัว" if len(n) == 2 else ("วิ่ง" if len(n) == 1 else "อื่นๆ"))
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        c.execute("UPDATE BlockedNumbers SET raw_num=%s, status=%s, type=%s, is_raw=TRUE WHERE id=%s",
                  (n, block_status, t_val, blocked_id))
    return redir("/blocked-numbers", draw=draw, msg="แก้ไขสำเร็จ")


@app.get("/delete-blocked")
def delete_blocked(request: Request, id: int, draw: str = ""):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        c.execute("DELETE FROM BlockedNumbers WHERE id=%s", (id,))
    return redir("/blocked-numbers", draw=draw)


@app.get("/clear-blocked")
def clear_blocked(request: Request, draw: str):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        c.execute("DELETE FROM BlockedNumbers WHERE draw_date = %s OR draw_date ILIKE %s", (draw, f"%{common.like_escape(draw)}%"))
    return redir("/blocked-numbers", draw=draw)


# ---------------- ผลรางวัล ----------------

@app.get("/results", response_class=HTMLResponse)
def results_page(request: Request, draw: str = ""):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request)
        if bad:
            return bad
        if not draw:
            return _pick_draw(request, me, c, "/results")
        _, draw_clean = _split_draw(draw)
        like = f"%{common.like_escape(draw_clean)}%"
        c.execute("SELECT prize_1, bottom_2 FROM DrawResults WHERE draw_date = %s OR draw_date ILIKE %s", (draw_clean, like))
        res = c.fetchone()
        prize_1 = str(res[0]).strip() if res and res[0] else ""
        bottom_2 = str(res[1]).strip() if res and res[1] else ""
        c.execute("SELECT raw_num, status FROM BlockedNumbers WHERE draw_date = %s OR draw_date ILIKE %s", (draw_clean, like))
        half_pay = {str(n).strip() for n, s in c.fetchall() if s != "ปิดรับ" and n}
        c.execute("SELECT SUM(amount), SUM(net) FROM Transactions WHERE (draw_date = %s OR draw_date ILIKE %s)", (draw_clean, like))
        sr = c.fetchone()
        total_sales = float(sr[0] or 0) if sr else 0.0
        total_net = float(sr[1] or 0) if sr else 0.0
        winners, total_payout = [], 0.0
        c.execute("SELECT customer_name, username, num, type, amount, payout_rate FROM Transactions "
                  "WHERE (draw_date = %s OR draw_date ILIKE %s)", (draw_clean, like))
        for cname, uname, num, ttype, amt, rate in c.fetchall():
            amt_val, rate_val = float(amt or 0), float(rate or 0)
            n, t = str(num).strip(), str(ttype).strip()
            win = False
            if t == "3ตัวตรง" and prize_1 and n == prize_1: win = True
            elif t == "3ตัวโต๊ด" and prize_1 and sorted(n) == sorted(prize_1) and n != prize_1: win = True
            elif t == "2ตัวบน" and prize_1 and len(prize_1) >= 2 and n == prize_1[-2:]: win = True
            elif t == "2ตัวล่าง" and bottom_2 and n == bottom_2: win = True
            elif t == "วิ่งบน" and prize_1 and n in list(prize_1): win = True
            elif t == "วิ่งล่าง" and bottom_2 and n in list(bottom_2): win = True
            if win:
                if n in half_pay:
                    rate_val /= 2.0
                payout = amt_val * rate_val
                winners.append((cname, uname, n, t, amt_val, rate_val, payout))
                total_payout += payout
    return _admin_render(request, me, ADM_RESULTS_CONTENT, draw_date=draw, prize_1=prize_1, bottom_2=bottom_2,
                         total_sales=total_sales, total_net=total_net, winners=winners, total_payout=total_payout)


@app.post("/save-results")
def save_results(request: Request, draw: str = Form(...), prize_1: str = Form(...), bottom_2: str = Form(...), user: str = Form("")):
    _, draw_clean = _split_draw(draw)
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        c.execute("INSERT INTO DrawResults (draw_date, prize_1, bottom_2) VALUES (%s,%s,%s) "
                  "ON CONFLICT (draw_date) DO UPDATE SET prize_1=EXCLUDED.prize_1, bottom_2=EXCLUDED.bottom_2",
                  (draw_clean, prize_1.strip(), bottom_2.strip()))
        c.execute("UPDATE LotteryCampaigns SET result_timestamp=%s WHERE draw_date = %s OR draw_date ILIKE %s",
                  (common.get_thai_time().strftime("%Y-%m-%d %H:%M:%S"), draw_clean, f"%{common.like_escape(draw_clean)}%"))
    return redir("/results", draw=draw, msg="บันทึกผลรางวัลสำเร็จ เริ่มนับถอยหลังปิดงวดอัตโนมัติ 2 วัน")


# ---------------- แดชบอร์ด / ตรวจสอบ / DB ----------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, draw: str = "", start_date: str = None, end_date: str = None):
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if not is_manager(me):
            return redir("/select-market", error="เมนูนี้สำหรับผู้จัดการขึ้นไป")
        if me["role"] == "Admin":
            c.execute("SELECT username, COALESCE(lotto_name,'ไม่ระบุประเภท'), timestamp, amount, net FROM Transactions WHERE timestamp IS NOT NULL")
        else:
            c.execute("SELECT username, COALESCE(lotto_name,'ไม่ระบุประเภท'), timestamp, amount, net FROM Transactions "
                      "WHERE timestamp IS NOT NULL AND username = ANY(%s)", (common.get_subtree(c, me["username"]),))
        rows = c.fetchall()
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if end_date else None
    except ValueError:
        start_dt = end_dt = None
    total_sales = total_net = 0.0
    usd, lsd = {}, {}
    for r_user, r_lotto, r_time, r_amt, r_net in rows:
        row_dt = None
        try:
            r_time = str(r_time)
            if "/" in r_time:
                row_dt = datetime.strptime(r_time[:19], "%d/%m/%Y %H:%M:%S")
            elif "-" in r_time:
                row_dt = datetime.strptime(r_time[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        if row_dt:
            if (start_dt and row_dt < start_dt) or (end_dt and row_dt > end_dt):
                continue
        elif start_dt or end_dt:
            continue
        amt, net = float(r_amt or 0), float(r_net or 0)
        total_sales += amt
        total_net += net
        usd[r_user] = usd.get(r_user, 0.0) + amt
        lsd[r_lotto] = lsd.get(r_lotto, 0.0) + amt
    return _admin_render(request, me, ADM_DASHBOARD_CONTENT, draw_date=draw, start_date=start_date or "", end_date=end_date or "",
                         total_sales=total_sales, total_net=total_net,
                         user_sales=sorted(usd.items(), key=lambda x: x[1], reverse=True),
                         lotto_sales=sorted(lsd.items(), key=lambda x: x[1], reverse=True))


def _audit(request, to, template, key, admin_only):
    draw = request.query_params.get("draw", "")
    with db() as conn:
        c = conn.cursor()
        me = get_me(c, request)
        if not me:
            return to_login()
        if admin_only and me["role"] != "Admin":
            return redir("/select-market", error="เมนูนี้สำหรับแอดมินเท่านั้น")
        if not is_manager(me):
            return redir("/select-market", error="เมนูนี้สำหรับผู้จัดการขึ้นไป")
        if not draw:
            return _pick_draw(request, me, c, to)
        _, draw_clean = _split_draw(draw)
        like = f"%{common.like_escape(draw_clean)}%"
        if me["role"] == "Admin":
            c.execute("SELECT * FROM Transactions WHERE (draw_date = %s OR draw_date ILIKE %s) ORDER BY id DESC LIMIT 5000", (draw_clean, like))
        else:
            c.execute("SELECT * FROM Transactions WHERE ((draw_date = %s OR draw_date ILIKE %s) AND username = ANY(%s)) ORDER BY id DESC LIMIT 5000",
                      (draw_clean, like, common.get_subtree(c, me["username"])))
        rows = c.fetchall()
    return _admin_render(request, me, template, draw_date=draw, **{key: rows})


@app.get("/audit-all", response_class=HTMLResponse)
def audit_all_page(request: Request):
    return _audit(request, "/audit-all", ADM_AUDIT_ALL_CONTENT, "audit_rows", True)


@app.get("/audit-discount", response_class=HTMLResponse)
def audit_discount_page(request: Request):
    return _audit(request, "/audit-discount", ADM_AUDIT_DISCOUNT_CONTENT, "discount_rows", False)


@app.get("/db-inspector", response_class=HTMLResponse)
def db_inspector_page(request: Request, draw: str = "", table_name: str = None):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request)
        if bad:
            return bad
        c.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        tables = [r[0] for r in c.fetchall()]
        selected = table_name if table_name in tables else (tables[0] if tables else None)
        rows, columns = [], []
        if selected:
            c.execute(f'SELECT * FROM "{selected}" ORDER BY 1 DESC LIMIT 100')
            rows = c.fetchall()
            columns = [d[0] for d in c.description]
    return _admin_render(request, me, ADM_DB_INSPECTOR_TEMPLATE, draw_date=draw, tables=tables, selected_table=selected,
                         columns=columns, rows=rows)


# ---------------- รีเซ็ตระบบ ----------------

@app.get("/system-reset", response_class=HTMLResponse)
def system_reset_page(request: Request):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request)
        if bad:
            return bad
    return HTMLResponse(env.from_string(ADM_SYSTEM_RESET_TEMPLATE).render(
        username=me["username"], error=request.query_params.get("error")))


@app.post("/execute-system-reset")
def execute_system_reset(request: Request, admin_password: str = Form(...), username: str = Form("")):
    with db() as conn:
        c = conn.cursor()
        me, bad = _admin_gate(c, request, mutating=True)
        if bad:
            return bad
        c.execute("SELECT password FROM Users WHERE id=%s", (me["id"],))
        row = c.fetchone()
        if not row or not common.verify_password(row[0], admin_password):
            return redir("/system-reset", error="รหัสผ่าน Admin ไม่ถูกต้อง ไม่สามารถรีเซ็ตระบบได้!")
        for tbl in ("Transactions", "TempDraft", "BlockedNumbers", "CustomerLottoRates", "AgentSettlements",
                    "DrawResults", "Customers", "LotteryCampaigns"):
            c.execute(f"DELETE FROM {tbl}")
        c.execute("DELETE FROM Users WHERE id <> %s", (me["id"],))
    return redir("/login", error="รีเซ็ตระบบสำเร็จ! ข้อมูลถูกล้างเรียบร้อยพร้อมเริ่มใช้งานจริงแล้ว")


@app.get("/admin-campaigns")
def old_admin_campaigns():
    return redir("/campaigns")


@app.get("/admin-blocked")
def old_admin_blocked():
    return redir("/blocked-numbers")
