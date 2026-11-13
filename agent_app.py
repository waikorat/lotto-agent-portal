"""
LuckyNumber Agent Portal (ระบบตัวแทน) — ฉบับแก้ไขเต็ม
รัน:  DB_URI=... SECRET_KEY=... uvicorn agent_app:app --host 0.0.0.0 --port 8001
"""
import logging
import os
import re
import time
from contextlib import asynccontextmanager
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
      {% if user.role == 'Admin' %}<a href="/live-sales" class="text-info">📈 ยอดขายสด</a>{% endif %}
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
        c.execute(f"SELECT {_USER_COLS} FROM Users WHERE LOWER(parent_user)=LOWER(%s) AND id<>%s ORDER BY id DESC",
                  (me["username"], me["id"]))
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
        allowed = t and user_id != me["id"] and (t[1] or "").lower() == me["username"].lower()
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


# ============================================================ เส้นทางเดิมที่ย้ายไปอยู่ในระบบหลัก

@app.get("/admin-campaigns")
@app.get("/admin-blocked")
@app.get("/system-reset")
def moved_to_main():
    return redir("/select-market", msg="ฟังก์ชันนี้ใช้งานที่ระบบหลักเท่านั้น (จัดการงวด/เลขอั้น/รีเซ็ตระบบ)")
