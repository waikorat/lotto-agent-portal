from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template
import psycopg2
from datetime import datetime, timedelta
import itertools

app = FastAPI(title="LuckyNumber Agent Portal - Enterprise Production")

# เชื่อมต่อฐานข้อมูล Supabase PostgreSQL (ชุดเดียวกับระบบหลัก 100%)
DB_URI = "postgresql://postgres.mpyswshlrxwpirzdexrn:Clublifekorat3888@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"

def connect_db():
    return psycopg2.connect(DB_URI)

def get_thai_time():
    return datetime.utcnow() + timedelta(hours=7)

# --- Startup Migration ตารางชำระบัญชีระหว่างกัน (ถ้ายังไม่มี) ---
@app.on_event("startup")
def startup_agent_db():
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS AgentSettlements (
                id SERIAL PRIMARY KEY,
                agent_username VARCHAR(100),
                target_name VARCHAR(100),
                amount NUMERIC(12,2),
                settle_type VARCHAR(20), -- 'รับชำระ', 'จ่ายชำระ'
                note TEXT,
                timestamp TEXT
            );
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print("Agent DB Init Error:", e)

@app.get("/", response_class=HTMLResponse)
def index():
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

# ================= 1. หน้าจอ LOGIN =================
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>LuckyNumber - Login</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f7e6d0; height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-card { width: 100%; max-width: 400px; background: #000; border: 2px solid #d4af37; padding: 30px; border-radius: 10px; color: white; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 2.2rem; color: #f3e5ab; text-align: center; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo-text">LuckyNumber</div>
        {% if error %}
            <div class="alert alert-danger py-2 small text-center">{{ error }}</div>
        {% endif %}
        <form method="POST" action="/login">
            <div class="mb-3">
                <label class="form-label small fw-bold">Username</label>
                <input type="text" name="username" class="form-control" required autofocus>
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">Password</label>
                <input type="password" name="password" class="form-control" required>
            </div>
            <button type="submit" class="btn btn-warning w-100 fw-bold text-dark py-2">เข้าสู่ระบบ</button>
        </form>
    </div>
</body>
</html>
"""

@app.get("/login", response_class=HTMLResponse)
def login_page(error: str = None):
    return Template(LOGIN_TEMPLATE).render(error=error)

@app.post("/login")
def login_action(username: str = Form(...), password: str = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT username, role FROM Users WHERE username=%s AND password=%s", (username, password))
        user = c.fetchone()
        conn.close()
        
        if user:
            return RedirectResponse(url=f"/select-market?user={username}", status_code=status.HTTP_303_SEE_OTHER)
        else:
            return RedirectResponse(url="/login?error=Username%20or%20Password%20ไม่ถูกต้อง", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return RedirectResponse(url=f"/login?error=DB%20Error", status_code=status.HTTP_303_SEE_OTHER)

# ================= 2. หน้าจอเลือกตลาด / เมนูหลัก (พร้อมรองรับ Admin/Agent Menu) =================
SELECT_MARKET_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>LuckyNumber - เลือกลอตเตอรี่ / ตลาด</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #f7e6d0; font-family: 'Segoe UI', sans-serif; }
        .top-header { background-color: #000; color: white; padding: 10px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #d4af37; }
        .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 1.8rem; color: #f3e5ab; }
        .container-box { max-width: 1000px; margin: 30px auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); border-top: 4px solid #d4af37; }
    </style>
</head>
<body>
    <div class="top-header">
        <span class="logo-text">LuckyNumber Portal</span>
        <div>ยินดีต้อนรับ: <b>{{ username }} ({{ role }})</b> | <a href="/login" class="text-danger text-decoration-none fw-bold">ออกจากระบบ</a></div>
    </div>
    <div class="container container-box">
        <div class="row mb-4">
            <div class="col-12">
                <div class="p-3 bg-dark text-white rounded d-flex justify-content-between align-items-center">
                    <div>
                        <h4 class="text-warning mb-1"><i class="fa-solid fa-gauge-high"></i> แผงควบคุมระบบตัวแทน & จัดการ</h4>
                        <p class="mb-0 small text-muted">เลือกตลาดหวยเพื่อคีย์โพย หรือจัดการระบบสายงานภายใต้สิทธิ์ของคุณ</p>
                    </div>
                    <div class="d-flex gap-2">
                        <a href="/customer-rates-page?user={{ username }}" class="btn btn-warning btn-sm fw-bold text-dark">⚙️ จัดการเรตลูกค้า</a>
                        <a href="/agent-settlement?user={{ username }}" class="btn btn-info btn-sm fw-bold">💰 บัญชีรับ-จ่ายเคลียร์ยอด</a>
                        {% if role in ['Admin', 'Master Agent', 'Agent'] %}
                        <a href="/agent-reports?user={{ username }}" class="btn btn-success btn-sm fw-bold">📊 รายงานยอดขาย & สรุปผล</a>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>

        <h3 class="fw-bold mb-3">📌 เลือกลอตเตอรี่ / ตลาดหวยที่เปิดให้แทง</h3>
        <div class="list-group">
            {% for m in markets %}
            <a href="/portal?user={{ username }}&market={{ m[1] }}&draw={{ m[2] }}" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center py-3 mb-2 border rounded">
                <div>
                    <h5 class="mb-1 text-primary fw-bold">🎟️ {{ m[1] }}</h5>
                    <small class="text-muted">งวดประจำวันที่: {{ m[2] }} | สถานะ: <span class="badge bg-success">{{ m[3] }}</span></small>
                </div>
                <span class="btn btn-outline-primary btn-sm fw-bold">เข้าคีย์โพย ➡️</span>
            </a>
            {% else %}
            <div class="alert alert-warning text-center">ยังไม่มีตลาดหวยที่เปิดอยู่ในขณะนี้ในระบบหลัก</div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

@app.get("/select-market", response_class=HTMLResponse)
def select_market(user: str):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        res = c.fetchone()
        role = res[0] if res else "Agent"

        c.execute("SELECT id, lotto_name, draw_date, status FROM LotteryCampaigns WHERE status='Active' ORDER BY id DESC")
        markets = c.fetchall()
        conn.close()
    except Exception as e:
        print("Select Market Error:", e)
        role = "Agent"
        markets = []
    return Template(SELECT_MARKET_TEMPLATE).render(username=user, role=role, markets=markets)


# ================= Helper สำหรับดึงเลขอั้นแยก 3 กรอบ =================
def get_blocked_display_data(draw_date):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT raw_num, status, type FROM BlockedNumbers WHERE (draw_date = %s OR draw_date ILIKE %s) AND is_raw = TRUE", (draw_date, f"%{draw_date}%"))
        rows = c.fetchall()
        if not rows:
            c.execute("SELECT raw_num, status, type FROM BlockedNumbers WHERE (draw_date = %s OR draw_date ILIKE %s)", (draw_date, f"%{draw_date}%"))
            rows = c.fetchall()
        conn.close()
        l_c, l_3, l_2 = [], [], []
        seen_c, seen_3, seen_2 = set(), set(), set()
        for r_num, status_val, type_val in rows:
            if not r_num: continue
            num_str = str(r_num).strip()
            if status_val == "ปิดรับ":
                if num_str not in seen_c:
                    seen_c.add(num_str)
                    l_c.append(num_str)
            else:
                if len(num_str) == 3 or type_val == "3ตัว":
                    if num_str not in seen_3:
                        seen_3.add(num_str)
                        l_3.append(num_str)
                elif len(num_str) == 2 or type_val == "2ตัว":
                    if num_str not in seen_2:
                        seen_2.add(num_str)
                        l_2.append(num_str)
        return ", ".join(l_c), ", ".join(l_3), ", ".join(l_2)
    except:
        return "", "", ""


# ================= 4. หน้าจอหลัก POS (3 คอลัมน์ คีย์ด่วน + ฟังก์ชัน 6กลับ/19ประตู/รูดหน้า/รูดหลัง) =================
PORTAL_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>LuckyNumber - Agent Portal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #f7e6d0; font-family: 'Segoe UI', sans-serif; overflow-x: hidden; margin: 0; }
        .top-header { background-color: #000; color: white; padding: 5px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #d4af37; height: 50px; }
        .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 1.8rem; color: #f3e5ab; }
        .top-nav-links { display: flex; gap: 20px; align-items: center; }
        .top-nav-links a { color: #fff; text-decoration: none; font-size: 0.9rem; }
        .main-container { display: flex; height: calc(100vh - 50px); }
        .sidebar-left { width: 260px; background-color: #000; color: white; border-right: 2px solid #d4af37; padding: 15px; flex-shrink: 0; overflow-y: auto; }
        .user-box { background-color: #1a1a1a; border: 1px solid #333; padding: 10px; border-radius: 4px; font-size: 0.85rem; margin-bottom: 15px; }
        .rate-table th, .rate-table td { font-size: 0.75rem; padding: 3px !important; color: white; background-color: #1a1a1a !important; border-color: #444 !important; }
        .menu-title { color: #fff; font-weight: bold; font-size: 0.95rem; margin-top: 15px; margin-bottom: 8px; border-bottom: 1px solid #444; padding-bottom: 4px; }
        .menu-item { display: block; color: #ccc; text-decoration: none; padding: 5px 8px; font-size: 0.9rem; margin-bottom: 2px; }
        .menu-item:hover { color: #d4af37; background-color: #222; }
        .content-center { flex-grow: 1; padding: 15px; overflow-y: auto; }
        .market-banner { background-color: #dc3545; color: white; padding: 8px 15px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; font-weight: bold; margin-bottom: 15px; }
        .quick-btn-group { display: flex; gap: 10px; margin-bottom: 10px; }
        .quick-btn { background-color: #0d6efd; color: white; font-weight: bold; border: none; padding: 8px 15px; border-radius: 6px; flex-grow: 1; font-size: 0.9rem; }
        .preview-box { background-color: #ccfeff; border: 2px solid #0dcaf0; padding: 10px; border-radius: 6px; font-family: monospace; font-weight: bold; font-size: 1.05rem; color: #000; margin-bottom: 12px; min-height: 45px; display: flex; align-items: center; flex-wrap: wrap; gap: 5px; }
        .entry-form-box { background-color: rgba(255,255,255,0.8); padding: 10px; border-radius: 6px; margin-bottom: 15px; border: 1px solid #ccc; }
        .sidebar-right { width: 320px; background-color: rgba(255,255,255,0.4); border-left: 2px solid #d4af37; padding: 15px; flex-shrink: 0; overflow-y: auto; }
        .recent-table th, .recent-table td { font-size: 0.75rem; padding: 4px !important; text-align: center; }
    </style>
    <script>
        function updateClock() {
            const now = new Date();
            document.getElementById('live-clock').innerText = now.toLocaleString('th-TH');
        }
        setInterval(updateClock, 1000);

        function apply6Box() {
            let num = document.getElementById('mainNumInput').value.trim();
            if (num.length !== 3) { alert("กรุณากรอกตัวเลข 3 หลัก"); return; }
            let perms = new Set(); let arr = num.split('');
            function permute(a, l, r) {
                if (l === r) { perms.add(a.join('')); }
                else { for (let i = l; i <= r; i++) { [a[l], a[i]] = [a[i], a[l]]; permute(a, l+1, r); [a[l], a[i]] = [a[i], a[l]]; } }
            }
            permute(arr, 0, arr.length - 1);
            updatePreview(Array.from(perms).join(','));
        }
        function apply19Door() {
            let digit = document.getElementById('mainNumInput').value.trim();
            if (digit.length !== 1) { alert("กรุณากรอกตัวเลข 1 หลัก"); return; }
            let doors = [];
            for (let i = 0; i <= 9; i++) {
                let n1 = digit + i, n2 = i + digit;
                if (!doors.includes(n1)) doors.push(n1);
                if (!doors.includes(n2)) doors.push(n2);
            }
            updatePreview(doors.join(','));
        }
        function applyFrontRoot() {
            let digit = document.getElementById('mainNumInput').value.trim();
            if (digit.length !== 1) { alert("กรุณากรอกตัวเลข 1 หลัก"); return; }
            let doors = []; for (let i = 0; i <= 9; i++) { doors.push(digit + i); }
            updatePreview(doors.join(','));
        }
        function applyBackRoot() {
            let digit = document.getElementById('mainNumInput').value.trim();
            if (digit.length !== 1) { alert("กรุณากรอกตัวเลข 1 หลัก"); return; }
            let doors = []; for (let i = 0; i <= 9; i++) { doors.push(i + digit); }
            updatePreview(doors.join(','));
        }
        function updatePreview(nums) {
            let topAmt = document.getElementById('topAmtInput').value || '0';
            let botAmt = document.getElementById('botAmtInput').value || '0';
            document.getElementById('previewContent').innerHTML = `<span>${nums}</span> = <span class="badge bg-white text-dark border px-2">${topAmt}</span> * <span class="badge bg-white text-dark border px-2">${botAmt}</span>`;
            document.getElementById('hiddenGeneratedNums').value = nums;
        }
        function refreshPreviewOnInput() {
            let hiddenNums = document.getElementById('hiddenGeneratedNums').value;
            if(hiddenNums) { updatePreview(hiddenNums); }
            else {
                let num = document.getElementById('mainNumInput').value;
                let topAmt = document.getElementById('topAmtInput').value || '0';
                let botAmt = document.getElementById('botAmtInput').value || '0';
                document.getElementById('previewContent').innerHTML = `<span>${num}</span> = <span class="badge bg-white text-dark border px-2">${topAmt}</span> * <span class="badge bg-white text-dark border px-2">${botAmt}</span>`;
            }
        }
    </script>
</head>
<body onload="updateClock()">
    <div class="top-header">
        <div class="d-flex align-items-center gap-3">
            <span class="logo-text">LuckyNumber Portal</span>
        </div>
        <div class="top-nav-links">
            <span class="text-warning small" id="live-clock">กำลังโหลดเวลา...</span>
            <a href="/select-market?user={{ username }}">เปลี่ยนตลาด</a>
        </div>
        <div>
            <a href="/login" class="btn btn-danger btn-sm fw-bold px-3">log out</a>
        </div>
    </div>

    <div class="main-container">
        <!-- Sidebar ซ้าย: เลือกชื่อลูกค้าในสังกัด และแสดงเรต -->
        <div class="sidebar-left">
            <div class="user-box">
                <div class="fw-bold text-warning mb-1">ข้อมูลผู้ใช้ระบบ</div>
                <div>Username: <b>{{ username }}</b></div>
                <div>ระดับสิทธิ์: <b>{{ role }}</b></div>
            </div>

            <form method="GET" action="/portal" id="customerForm">
                <input type="hidden" name="user" value="{{ username }}">
                <input type="hidden" name="market" value="{{ market }}">
                <input type="hidden" name="draw" value="{{ draw_date }}">
                <div class="mb-3">
                    <label class="form-label small fw-bold text-warning">เลือกลูกค้าในสังกัด:</label>
                    <select name="customer_id" class="form-select form-select-sm" onchange="document.getElementById('customerForm').submit()">
                        {% for cust in customers %}
                        <option value="{{ cust[0] }}" {% if cust[0]|string == customer_id|string %}selected{% endif %}>{{ cust[1] }}</option>
                        {% endfor %}
                    </select>
                </div>
            </form>

            <div class="mb-3">
                <div class="small fw-bold text-info mb-1">อัตราจ่าย: {{ market }}</div>
                {% if has_rate %}
                <table class="table table-bordered rate-table text-center">
                    <thead><tr><th>ประเภท</th><th>รางวัล</th><th>ส่วนลด</th></tr></thead>
                    <tbody>
                        <tr><td>3ตัวตรง</td><td>{{ rates.pay_3d }}</td><td>{{ rates.disc_3d if rates.disc_3d > 0 else rates.disc_total }}%</td></tr>
                        <tr><td>3ตัวโต๊ด</td><td>{{ rates.pay_3tod }}</td><td>{{ rates.disc_3d if rates.disc_3d > 0 else rates.disc_total }}%</td></tr>
                        <tr><td>2ตัวบน/ล่าง</td><td>{{ rates.pay_2d }}</td><td>{{ rates.disc_2d if rates.disc_2d > 0 else rates.disc_total }}%</td></tr>
                        <tr><td>วิ่งบน/ล่าง</td><td>{{ rates.pay_run_top }}/{{ rates.pay_run_bot }}</td><td>{{ rates.disc_run if rates.disc_run > 0 else rates.disc_total }}%</td></tr>
                    </tbody>
                </table>
                {% else %}
                <div class="alert alert-warning py-2 small text-center">ยังไม่ได้ตั้งค่าเรต</div>
                {% endif %}
            </div>

            <div class="menu-title">เมนูด่วน</div>
            <a href="/select-market?user={{ username }}" class="menu-item">▶ เลือกตลาด/งวด</a>
            <a href="/customer-rates-page?user={{ username }}" class="menu-item text-warning">⚙️ กำหนดเรตลูกค้าแยกหวย</a>
            <a href="/agent-settlement?user={{ username }}" class="menu-item text-info">💰 บัญชีรับ-จ่ายเคลียร์ยอด</a>
            <a href="/agent-reports?user={{ username }}" class="menu-item text-success">📊 รายงานสรุปผล & ยอดขาย</a>
        </div>

        <!-- Content ตรงกลาง: คีย์โพย & ฟังก์ชันด่วน -->
        <div class="content-center">
            <div class="market-banner">
                <div>🎟️ {{ market }} งวดประจำวันที่ {{ draw_date }} | ลูกค้า: <span class="text-warning">{{ current_customer_name }}</span></div>
                <div>สถานะระบบ: <span class="text-warning">เปิดรับแทงปกติ</span></div>
            </div>

            {% if error_msg %}
            <div class="alert alert-danger fw-bold text-center">
                ❌ {{ error_msg }}
            </div>
            {% endif %}

            {% if not has_rate %}
            <!-- แจ้งเตือนกรณีลูกค้ายังไม่มีเรตสำหรับหวยนี้ พร้อมปุ่มนำทาง -->
            <div class="alert alert-danger shadow p-4 text-center bg-white border border-danger border-2">
                <h4 class="text-danger fw-bold mb-3"><i class="fa-solid fa-triangle-exclamation"></i> ยังไม่ได้ตั้งค่าเรตอัตราจ่ายของลูกค้ารายนี้</h4>
                <p class="text-dark mb-4">ลูกค้ารายนี้ยังไม่มีการกำหนดอัตราจ่ายและส่วนลดสำหรับหวย <b>{{ market }}</b> กรุณาไปตั้งค่าเรตให้เรียบร้อยก่อนจึงจะสามารถคีย์โพยได้</p>
                <a href="/customer-rates-page?user={{ username }}" class="btn btn-danger btn-lg fw-bold px-5">
                    ⚙️ ไปหน้ากำหนดเรตลูกค้าแยกตามหวย ➡️
                </a>
            </div>
            {% else %}

            <div class="quick-btn-group">
                <button type="button" class="quick-btn" onclick="apply6Box()">6กลับ</button>
                <button type="button" class="quick-btn" onclick="apply19Door()">รูด19ประตู</button>
                <button type="button" class="quick-btn" onclick="applyFrontRoot()">รูดหน้า</button>
                <button type="button" class="quick-btn" onclick="applyBackRoot()">รูดหลัง</button>
            </div>

            <div class="preview-box" id="previewContent">
                <span class="text-muted small">preview:- (เลือกฟังก์ชันคีย์ด่วน หรือพิมพ์เลขในฟอร์มด้านล่าง)</span>
            </div>

            <form method="POST" action="/portal-add-draft" class="entry-form-box">
                <input type="hidden" name="user" value="{{ username }}">
                <input type="hidden" name="market" value="{{ market }}">
                <input type="hidden" name="draw" value="{{ draw_date }}">
                <input type="hidden" name="customer_id" value="{{ customer_id }}">
                <input type="hidden" id="hiddenGeneratedNums" name="generated_nums" value="">

                <div class="row g-2 align-items-center">
                    <div class="col-md-4">
                        <label class="form-label small fw-bold mb-1">ตัวเลข</label>
                        <input type="text" id="mainNumInput" name="num_input" class="form-control" placeholder="พิมพ์เลข..." oninput="refreshPreviewOnInput()" required autofocus>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label small fw-bold mb-1">บน / 3ตัวตรง</label>
                        <input type="number" step="any" id="topAmtInput" name="top_amt" class="form-control" placeholder="จำนวนเงิน" oninput="refreshPreviewOnInput()">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label small fw-bold mb-1">ล่าง / 3ตัวโต๊ด</label>
                        <input type="number" step="any" id="botAmtInput" name="bot_amt" class="form-control" placeholder="จำนวนเงิน" oninput="refreshPreviewOnInput()">
                    </div>
                </div>
                <div class="d-flex gap-2 mt-2">
                    <button type="reset" class="btn btn-danger btn-sm fw-bold px-4">ยกเลิก</button>
                    <button type="submit" class="btn btn-primary btn-sm fw-bold px-4">เพิ่มรายการ</button>
                </div>
            </form>
            {% endif %}

            <div class="card shadow-sm p-3 bg-white mt-3">
                <h5 class="text-center fw-bold mb-2">รายการร่าง (รอการยืนยันโพย)</h5>
                <div class="table-responsive" style="max-height: 200px; overflow-y: auto;">
                    <table class="table table-sm table-striped table-bordered text-center align-middle" style="font-size: 0.85rem;">
                        <thead class="table-dark">
                            <tr><th>ประเภท@หมายเลข</th><th>เดิมพัน</th><th>เรตจ่าย</th><th>ส่วนลด</th><th>จัดการ</th></tr>
                        </thead>
                        <tbody>
                            {% for d in drafts %}
                            <tr>
                                <td><b>{{ d[4] }}@{{ d[1] }}</b></td>
                                <td>{{ "{:,.0f}".format(d[2] | float) }}</td>
                                <td><span class="badge bg-success">{{ d[5] }}</span></td>
                                <td class="text-danger">{{ "{:,.2f}".format(d[6] | float) }}</td>
                                <td>
                                    <a href="/portal-delete-draft?id={{ d[0] }}&user={{ username }}&market={{ market }}&draw={{ draw_date }}&customer_id={{ customer_id }}" class="text-danger"><i class="fa-solid fa-trash-can"></i></a>
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="5" class="text-muted py-2">ยังไม่มีรายการในร่าง</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <div class="d-flex gap-2 mt-3">
                    <form method="POST" action="/portal-confirm-bill" class="flex-grow-1">
                        <input type="hidden" name="user" value="{{ username }}">
                        <input type="hidden" name="market" value="{{ market }}">
                        <input type="hidden" name="draw" value="{{ draw_date }}">
                        <input type="hidden" name="customer_id" value="{{ customer_id }}">
                        <button type="submit" class="btn btn-primary w-100 fw-bold" {% if not has_rate or not drafts %}disabled{% endif %}>ยืนยันโพย & ออกบิล</button>
                    </form>
                    <a href="/portal-clear-draft?user={{ username }}&market={{ market }}&draw={{ draw_date }}&customer_id={{ customer_id }}" class="btn btn-danger fw-bold px-4" onclick="return confirm('ยืนยันล้างรายการ?')">ล้างรายการ</a>
                </div>
            </div>
        </div>

        <!-- Sidebar ขวา: เลขอั้น & รายการล่าสุด -->
        <div class="sidebar-right">
            <div class="card shadow-sm p-3 bg-white mb-4 border">
                <h6 class="text-center fw-bold text-danger mb-3">🚫 รายการเลขอั้นประจำงวด</h6>
                
                <label class="fw-bold text-dark mb-1 small">เลขอั้นปิดรับ:</label>
                <textarea class="form-control form-control-sm mb-2 bg-light text-danger fw-bold" rows="2" readonly>{{ block_closed }}</textarea>
                
                <label class="fw-bold text-dark mb-1 small">เลขอั้น 3ตัว (จ่ายครึ่ง):</label>
                <textarea class="form-control form-control-sm mb-2 bg-light text-dark" rows="2" readonly>{{ block_3d }}</textarea>
                
                <label class="fw-bold text-dark mb-1 small">เลขอั้น 2ตัว (จ่ายครึ่ง):</label>
                <textarea class="form-control form-control-sm bg-light text-dark" rows="2" readonly>{{ block_2d }}</textarea>
            </div>

            <div class="card shadow-sm p-2 bg-white">
                <h6 class="text-center fw-bold mb-2">รายการล่าสุด</h6>
                <div class="table-responsive" style="max-height: 320px; overflow-y: auto;">
                    <table class="table table-sm table-bordered recent-table">
                        <thead class="table-dark">
                            <tr><th>TIME</th><th>Bill</th><th>เลข</th><th>บน</th><th>ล่าง</th><th>สุทธิ</th></tr>
                        </thead>
                        <tbody>
                            {% for tx in recent_transactions %}
                            <tr>
                                <td><small>{{ tx[2][11:16] if tx[2] and tx[2]|length >= 16 else '-' }}</small></td>
                                <td><code>{{ tx[7][-6:] if tx[7] else '-' }}</code></td>
                                <td><b>{{ tx[8] }}</b></td>
                                <td>{{ "{:,.0f}".format(tx[10] | float) if 'บน' in tx[9] or 'ตรง' in tx[9] else '-' }}</td>
                                <td>{{ "{:,.0f}".format(tx[10] | float) if 'ล่าง' in tx[9] or 'โต๊ด' in tx[9] else '-' }}</td>
                                <td class="fw-bold text-success">{{ "{:,.1f}".format(tx[12] | float) }}</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="6" class="text-muted">ยังไม่มีรายการ</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get("/portal", response_class=HTMLResponse)
def portal_page(user: str, market: str, draw: str, customer_id: int = None, error: str = None):
    try:
        conn = connect_db()
        c = conn.cursor()
        
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        user_res = c.fetchone()
        role = user_res[0] if user_res else "Agent"

        # ดึงรายชื่อลูกค้าภายใต้สังกัดของ user นี้ (ถ้าเป็น Admin หรือ Master เห็นสายงานตนเอง)
        if role == 'Admin':
            c.execute("SELECT id, name FROM Customers ORDER BY id DESC")
        else:
            c.execute("SELECT id, name FROM Customers WHERE owner_username = %s ORDER BY id DESC", (user,))
        customers = c.fetchall()

        if not customers:
            # ถ้ายังไม่มีลูกค้าในสังกัด ให้สร้างลูกค้ารายย่อยสำรองอัตโนมัติ
            c.execute("INSERT INTO Customers (name, owner_username, pay_3d, pay_3tod, pay_2d) VALUES (%s, %s, 500, 100, 70)", (f"ลูกค้าของ {user}", user))
            conn.commit()
            if role == 'Admin':
                c.execute("SELECT id, name FROM Customers ORDER BY id DESC")
            else:
                c.execute("SELECT id, name FROM Customers WHERE owner_username = %s ORDER BY id DESC", (user,))
            customers = c.fetchall()

        if not customer_id and customers:
            customer_id = customers[0][0]

        current_customer_name = ""
        for cust in customers:
            if cust[0] == customer_id:
                current_customer_name = cust[1]
                break

        # ตรวจสอบการตั้งค่าเรตเฉพาะลูกค้ารายนี้ กับ lotto_name นี้ใน CustomerLottoRates
        c.execute("""
            SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total 
            FROM CustomerLottoRates WHERE customer_id = %s AND lotto_name = %s
        """, (customer_id, market))
        rate_res = c.fetchone()

        has_rate = True
        user_rates = {"pay_3d": 500, "pay_3tod": 100, "pay_2d": 70, "pay_run_top": 3.2, "pay_run_bot": 4.2, "disc_total": 0, "disc_3d": 0, "disc_2d": 0, "disc_run": 0}

        if rate_res:
            p3d, p3tod, p2d, pr_top, pr_bot, d3d, d2d, drun, dtot = rate_res
            user_rates = {
                "pay_3d": float(p3d or 500), "pay_3tod": float(p3tod or 100), "pay_2d": float(p2d or 70),
                "pay_run_top": float(pr_top or 3.2), "pay_run_bot": float(pr_bot or 4.2),
                "disc_total": float(dtot or 0), "disc_3d": float(d3d or 0), "disc_2d": float(d2d or 0), "disc_run": float(drun or 0)
            }
        else:
            # ถ้ายังไม่มีในตารางแยกหวย ให้ดึงเรต default จากตาราง Customers
            c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_total, disc_run FROM Customers WHERE id = %s", (customer_id,))
            c_default = c.fetchone()
            if c_default:
                user_rates = {
                    "pay_3d": float(c_default[0] or 500), "pay_3tod": float(c_default[1] or 100), "pay_2d": float(c_default[2] or 70),
                    "pay_run_top": float(c_default[3] or 3.2), "pay_run_bot": float(c_default[4] or 4.2),
                    "disc_total": float(c_default[5] or 0), "disc_3d": 0, "disc_2d": 0, "disc_run": float(c_default[6] or 0)
                }
                has_rate = True # ยอมให้ใช้เรต default หรือจะบังคับให้ตั้งค่าก็ได้ตามต้องการ
            else:
                has_rate = False

        c.execute("SELECT id, num, amt_teng, status, type, payout_rate, discount, net FROM TempDraft WHERE username=%s AND customer_id=%s", (user, str(customer_id)))
        drafts = c.fetchall()

        c.execute("SELECT * FROM Transactions WHERE (draw_date = %s OR draw_date ILIKE %s) AND customer_id = %s ORDER BY id DESC LIMIT 15", (draw, f"%{draw}%", customer_id))
        recent_transactions = c.fetchall()

        b_closed, b_3d, b_2d = get_blocked_display_data(draw)
        conn.close()

        return Template(PORTAL_TEMPLATE).render(
            username=user, role=role, market=market, draw_date=draw, 
            customers=customers, customer_id=customer_id, current_customer_name=current_customer_name,
            drafts=drafts, recent_transactions=recent_transactions, 
            block_closed=b_closed, block_3d=b_3d, block_2d=b_2d,
            rates=user_rates, has_rate=has_rate, error_msg=error
        )
    except Exception as e:
        return f"Portal Error: {str(e)}"

@app.post("/portal-add-draft")
def portal_add_draft(
    user: str = Form(...), market: str = Form(...), draw: str = Form(...), 
    num_input: str = Form(None), generated_nums: str = Form(None), 
    top_amt: float = Form(0), bot_amt: float = Form(0),
    customer_id: int = Form(...)
):
    try:
        conn = connect_db()
        c = conn.cursor()
        
        c.execute("""
            SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total 
            FROM CustomerLottoRates WHERE customer_id = %s AND lotto_name = %s
        """, (customer_id, market))
        rate_res = c.fetchone()

        if not rate_res:
            c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_total, disc_run FROM Customers WHERE id = %s", (customer_id,))
            c_def = c.fetchone()
            if c_def:
                pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot = float(c_def[0] or 500), float(c_def[1] or 100), float(c_def[2] or 70), float(c_def[3] or 3.2), float(c_def[4] or 4.2)
                disc_total, disc_run, disc_3d, disc_2d = float(c_def[5] or 0), float(c_def[6] or 0), 0, 0
            else:
                conn.close()
                return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}&error=ยังไม่ได้ตั้งค่าเรตอัตราจ่ายสำหรับหวยนี้", status_code=status.HTTP_303_SEE_OTHER)
        else:
            pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total = rate_res

        target_nums = generated_nums if generated_nums and generated_nums.strip() else num_input
        numbers = [n.strip() for n in target_nums.replace(' ', '').split(',') if n.strip()]

        for n in numbers:
            length = len(n)
            if length == 3:
                if top_amt > 0:
                    d_rate = float(disc_3d if disc_3d > 0 else disc_total)
                    disc_amt = top_amt * (d_rate / 100.0)
                    net_amt = top_amt - disc_amt
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, str(customer_id), 'Customer', n, top_amt, '3ตัวตรง', float(pay_3d), disc_amt, net_amt, 'ปกติ'))
                if bot_amt > 0:
                    d_rate = float(disc_3d if disc_3d > 0 else disc_total)
                    disc_amt = bot_amt * (d_rate / 100.0)
                    net_amt = bot_amt - disc_amt
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, str(customer_id), 'Customer', n, bot_amt, '3ตัวโต๊ด', float(pay_3tod), disc_amt, net_amt, 'ปกติ'))
            elif length == 2:
                if top_amt > 0:
                    d_rate = float(disc_2d if disc_2d > 0 else disc_total)
                    disc_amt = top_amt * (d_rate / 100.0)
                    net_amt = top_amt - disc_amt
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, str(customer_id), 'Customer', n, top_amt, '2ตัวบน', float(pay_2d), disc_amt, net_amt, 'ปกติ'))
                if bot_amt > 0:
                    d_rate = float(disc_2d if disc_2d > 0 else disc_total)
                    disc_amt = bot_amt * (d_rate / 100.0)
                    net_amt = bot_amt - disc_amt
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, str(customer_id), 'Customer', n, bot_amt, '2ตัวล่าง', float(pay_2d), disc_amt, net_amt, 'ปกติ'))
            elif length == 1:
                if top_amt > 0:
                    d_rate = float(disc_run if disc_run > 0 else disc_total)
                    disc_amt = top_amt * (d_rate / 100.0)
                    net_amt = top_amt - disc_amt
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, str(customer_id), 'Customer', n, top_amt, 'วิ่งบน', float(pay_run_top), disc_amt, net_amt, 'ปกติ'))
                if bot_amt > 0:
                    d_rate = float(disc_run if disc_run > 0 else disc_total)
                    disc_amt = bot_amt * (d_rate / 100.0)
                    net_amt = bot_amt - disc_amt
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, str(customer_id), 'Customer', n, bot_amt, 'วิ่งล่าง', float(pay_run_bot), disc_amt, net_amt, 'ปกติ'))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Add Draft Error:", e)
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/portal-delete-draft")
def portal_delete_draft(id: int, user: str, market: str, draw: str, customer_id: int):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("DELETE FROM TempDraft WHERE id = %s", (id,))
        conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/portal-clear-draft")
def portal_clear_draft(user: str, market: str, draw: str, customer_id: int):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("DELETE FROM TempDraft WHERE username = %s AND customer_id = %s", (user, str(customer_id)))
        conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/portal-confirm-bill")
def portal_confirm_bill(user: str = Form(...), market: str = Form(...), draw: str = Form(...), customer_id: int = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT name FROM Customers WHERE id = %s", (customer_id,))
        cust_res = c.fetchone()
        cust_name = cust_res[0] if cust_res else "ลูกค้ารายย่อย"

        c.execute("SELECT num, type, amt_teng, payout_rate, discount, net, status FROM TempDraft WHERE username=%s AND customer_id=%s", (user, str(customer_id)))
        drafts = c.fetchall()
        if drafts:
            bill_prefix = 'TH' if 'รัฐบาล' in market else 'OT'
            bill_no = f"{bill_prefix}-{get_thai_time().strftime('%d%m%y')}-{customer_id}-B{get_thai_time().strftime('%H%M%S')}"
            ts = get_thai_time().strftime("%d/%m/%Y %H:%M:%S")
            
            for n, t_type, amt, rate, disc, net_val, status_val in drafts:
                c.execute("""
                    INSERT INTO Transactions (draw_date, timestamp, username, customer_id, customer_name, customer_type, bill_no, num, type, amount, status, discount, net, payout_rate, lotto_name) 
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (draw, ts, user, customer_id, cust_name, "Customer", bill_no, n, t_type, float(amt), status_val, float(disc), float(net_val), float(rate), market))
            
            c.execute("DELETE FROM TempDraft WHERE username=%s AND customer_id=%s", (user, str(customer_id)))
            conn.commit()
        conn.close()
    except Exception as e:
        print("Confirm Error:", e)
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}", status_code=status.HTTP_303_SEE_OTHER)


# ================= 5. หน้าจอตั้งค่าเรตลูกค้าแยกตามหวย (Customer Rates Page) =================
CUSTOMER_RATES_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>กำหนดเรตอัตราจ่ายและส่วนลดตามหวย</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container my-4" style="max-width: 900px;">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2>⚙️ กำหนดเรตอัตราจ่าย & ส่วนลด (แยกรายลูกค้า / แยกรายหวย)</h2>
            <a href="/select-market?user={{ username }}" class="btn btn-secondary">กลับหน้าหลักตัวแทน</a>
        </div>

        {% if msg %}
        <div class="alert alert-success">{{ msg }}</div>
        {% endif %}

        <div class="card shadow p-4 mb-4">
            <form method="POST" action="/save-customer-lotto-rate">
                <input type="hidden" name="username" value="{{ username }}">
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="form-label fw-bold">1. เลือกลูกค้าในสังกัด:</label>
                        <select name="customer_id" class="form-select" required>
                            <option value="">-- เลือกลูกค้า --</option>
                            {% for cust in customers %}
                            <option value="{{ cust[0] }}">{{ cust[1] }} (เจ้าของสายงาน: {{ cust[2] }})</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label fw-bold">2. เลือกประเภทหวย / ตลาด:</label>
                        <select name="lotto_name" class="form-select" required>
                            <option value="">-- เลือกลอตเตอรี่ / หวย --</option>
                            {% for lotto in lotto_list %}
                            <option value="{{ lotto }}">{{ lotto }}</option>
                            {% endfor %}
                        </select>
                    </div>
                </div>

                <hr class="my-4">

                <h5 class="fw-bold mb-3 text-primary">💰 กำหนดอัตราจ่าย (Pay Rate)</h5>
                <div class="row g-3 mb-3">
                    <div class="col-md-3"><label class="form-label small">3 ตัวตรง:</label><input type="number" step="any" name="pay_3d" class="form-control" value="500"></div>
                    <div class="col-md-3"><label class="form-label small">3 ตัวโต๊ด:</label><input type="number" step="any" name="pay_3tod" class="form-control" value="100"></div>
                    <div class="col-md-3"><label class="form-label small">2 ตัว (บน/ล่าง):</label><input type="number" step="any" name="pay_2d" class="form-control" value="70"></div>
                    <div class="col-md-3"><label class="form-label small">วิ่งบน:</label><input type="number" step="any" name="pay_run_top" class="form-control" value="3.2"></div>
                    <div class="col-md-3"><label class="form-label small text-danger fw-bold">วิ่งล่าง:</label><input type="number" step="any" name="pay_run_bot" class="form-control" value="4.2"></div>
                </div>

                <h5 class="fw-bold mb-3 text-success">📉 กำหนดส่วนลด (%)</h5>
                <div class="row g-3 mb-4">
                    <div class="col-md-4"><label class="form-label small">ส่วนลด 3 ตัว (%):</label><input type="number" step="any" name="disc_3d" class="form-control" value="0"></div>
                    <div class="col-md-4"><label class="form-label small">ส่วนลด 2 ตัว (%):</label><input type="number" step="any" name="disc_2d" class="form-control" value="0"></div>
                    <div class="col-md-4"><label class="form-label small">ส่วนลดรวมทุกประเภท (%):</label><input type="number" step="any" name="disc_total" class="form-control" value="0"></div>
                </div>

                <button type="submit" class="btn btn-primary w-100 fw-bold py-2">💾 บันทึก / อัปเดตเรตอัตราจ่าย</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

@app.get("/customer-rates-page", response_class=HTMLResponse)
def customer_rates_page(user: str, msg: str = None):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        role_res = c.fetchone()
        role = role_res[0] if role_res else "Agent"

        if role == 'Admin':
            c.execute("SELECT id, name, owner_username FROM Customers ORDER BY id DESC")
        else:
            c.execute("SELECT id, name, owner_username FROM Customers WHERE owner_username = %s ORDER BY id DESC", (user,))
        customers = c.fetchall()

        c.execute("SELECT DISTINCT lotto_name FROM LotteryCampaigns WHERE lotto_name IS NOT NULL")
        lotto_list = [row[0] for row in c.fetchall()]
        conn.close()
    except Exception as e:
        print("Load Customer Rates Error:", e)
        customers = []
        lotto_list = []
    
    return Template(CUSTOMER_RATES_TEMPLATE).render(
        username=user, customers=customers, lotto_list=lotto_list, msg=msg
    )

@app.post("/save-customer-lotto-rate")
def save_customer_lotto_rate(
    username: str = Form(...), 
    customer_id: int = Form(...), 
    lotto_name: str = Form(...),
    pay_3d: float = Form(500), 
    pay_3tod: float = Form(100), 
    pay_2d: float = Form(70), 
    pay_run_top: float = Form(3.2),
    pay_run_bot: float = Form(4.2), 
    disc_3d: float = Form(0), 
    disc_2d: float = Form(0), 
    disc_total: float = Form(0)
):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO CustomerLottoRates (
                customer_id, lotto_name, pay_3d, pay_3tod, pay_2d, 
                pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_total
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (customer_id, lotto_name) 
            DO UPDATE SET 
                pay_3d = EXCLUDED.pay_3d, 
                pay_3tod = EXCLUDED.pay_3tod, 
                pay_2d = EXCLUDED.pay_2d, 
                pay_run_top = EXCLUDED.pay_run_top, 
                pay_run_bot = EXCLUDED.pay_run_bot, 
                disc_3d = EXCLUDED.disc_3d, 
                disc_2d = EXCLUDED.disc_2d, 
                disc_total = EXCLUDED.disc_total
        """, (customer_id, lotto_name, pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_total))
        
        conn.commit()
        conn.close()
        msg = "บันทึกเรตอัตราจ่ายและส่วนลดสำเร็จ!"
    except Exception as e:
        msg = f"Error: {str(e)}"
        
    return RedirectResponse(url=f"/customer-rates-page?user={username}&msg={msg}", status_code=303)


# ================= 6. ระบบบัญชีรับ-จ่ายเคลียร์ยอดระหว่างกัน (Agent Settlement) =================
AGENT_SETTLEMENT_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>บัญชีรับ-จ่าย เคลียร์ยอดคงค้างระหว่างกัน</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container my-4" style="max-width: 900px;">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2>💰 บัญชีรับ-จ่าย / เคลียร์ยอดคงค้าง (Settlement Account)</h2>
            <a href="/select-market?user={{ username }}" class="btn btn-secondary">กลับหน้าหลักตัวแทน</a>
        </div>

        {% if msg %}
        <div class="alert alert-success">{{ msg }}</div>
        {% endif %}

        <div class="card shadow p-4 mb-4">
            <h5 class="fw-bold mb-3 text-primary">📝 บันทึกรับชำระ / จ่ายชำระยอด</h5>
            <form method="POST" action="/save-agent-settlement">
                <input type="hidden" name="username" value="{{ username }}">
                <div class="row g-3">
                    <div class="col-md-4">
                        <label class="form-label small fw-bold">ชื่อคู่ค้า / ลูกค้า / สายงาน:</label>
                        <input type="text" name="target_name" class="form-control" placeholder="ระบุชื่อ..." required>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label small fw-bold">ประเภทรายการ:</label>
                        <select name="settle_type" class="form-select" required>
                            <option value="รับชำระ">รับชำระเงิน (ยอดเข้า)</option>
                            <option value="จ่ายชำระ">จ่ายชำระเงิน (ยอดออก)</option>
                        </select>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label small fw-bold">จำนวนเงิน (บาท):</label>
                        <input type="number" step="any" name="amount" class="form-control" placeholder="0.00" required>
                    </div>
                    <div class="col-md-2 d-flex align-items-end">
                        <button type="submit" class="btn btn-success w-100 fw-bold">บันทึก</button>
                    </div>
                    <div class="col-12">
                        <label class="form-label small fw-bold">หมายเหตุ / งวด:</label>
                        <input type="text" name="note" class="form-control" placeholder="เช่น เคลียร์ยอดประจำงวด...">
                    </div>
                </div>
            </form>
        </div>

        <div class="card shadow p-4">
            <h5 class="fw-bold mb-3">📋 ประวัติการทำรายการรับ-จ่ายชำระยอด</h5>
            <div class="table-responsive">
                <table class="table table-striped table-bordered text-center align-middle" style="font-size: 0.9rem;">
                    <thead class="table-dark">
                        <tr><th>เวลา</th><th>ผู้บันทึก</th><th>คู่ค้า / ลูกค้า</th><th>ประเภท</th><th>จำนวนเงิน</th><th>หมายเหตุ</th></tr>
                    </thead>
                    <tbody>
                        {% for s in settlements %}
                        <tr>
                            <td><small>{{ s[6] }}</small></td>
                            <td>{{ s[1] }}</td>
                            <td><b>{{ s[2] }}</b></td>
                            <td><span class="badge {% if s[4] == 'รับชำระ' %}bg-success{% else %}bg-danger{% endif %}">{{ s[4] }}</span></td>
                            <td class="fw-bold">฿{{ "{:,.2f}".format(s[3] | float) }}</td>
                            <td>{{ s[5] }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="6" class="text-muted">ยังไม่มีประวัติการทำรายการ</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get("/agent-settlement", response_class=HTMLResponse)
def agent_settlement_page(user: str, msg: str = None):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        role_res = c.fetchone()
        role = role_res[0] if role_res else "Agent"

        if role == 'Admin':
            c.execute("SELECT id, agent_username, target_name, amount, settle_type, note, timestamp FROM AgentSettlements ORDER BY id DESC")
        else:
            c.execute("SELECT id, agent_username, target_name, amount, settle_type, note, timestamp FROM AgentSettlements WHERE agent_username = %s ORDER BY id DESC", (user,))
        settlements = c.fetchall()
        conn.close()
    except:
        settlements = []

    return Template(AGENT_SETTLEMENT_TEMPLATE).render(username=user, settlements=settlements, msg=msg)

@app.post("/save-agent-settlement")
def save_agent_settlement(
    username: str = Form(...),
    target_name: str = Form(...),
    settle_type: str = Form(...),
    amount: float = Form(...),
    note: str = Form("")
):
    try:
        conn = connect_db()
        c = conn.cursor()
        ts = get_thai_time().strftime("%d/%m/%Y %H:%M:%S")
        c.execute("""
            INSERT INTO AgentSettlements (agent_username, target_name, amount, settle_type, note, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (username, target_name, amount, settle_type, note, ts))
        conn.commit()
        conn.close()
        msg = "บันทึกรายการรับ-จ่ายสำเร็จ!"
    except Exception as e:
        msg = f"Error: {str(e)}"
    return RedirectResponse(url=f"/agent-settlement?user={username}&msg={msg}", status_code=303)


# ================= 7. รายงานสรุปยอดขาย & สรุปผลรางวัล (Agent Reports) =================
AGENT_REPORTS_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>รายงานสรุปยอดขายและผลรางวัล</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container my-4" style="max-width: 1000px;">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2>📊 รายงานสรุปยอดขาย & สรุปผลรางวัล (สายงานของคุณ)</h2>
            <a href="/select-market?user={{ username }}" class="btn btn-secondary">กลับหน้าหลักตัวแทน</a>
        </div>

        <div class="row text-center mb-4">
            <div class="col-md-6 mb-3">
                <div class="card shadow p-3 border-primary">
                    <h5 class="text-muted">ยอดขายรวม</h5>
                    <h2 class="text-primary fw-bold">฿{{ "{:,.2f}".format(total_sales) }}</h2>
                </div>
            </div>
            <div class="col-md-6 mb-3">
                <div class="card shadow p-3 border-success">
                    <h5 class="text-muted">ยอดสุทธิหลังหักส่วนลด</h5>
                    <h2 class="text-success fw-bold">฿{{ "{:,.2f}".format(total_net) }}</h2>
                </div>
            </div>
        </div>

        <div class="card shadow p-4 mb-4">
            <h4 class="text-dark fw-bold mb-3">📋 รายการบิลซื้อล่าสุดในสายงาน</h4>
            <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                <table class="table table-striped table-bordered text-center align-middle" style="font-size: 0.85rem;">
                    <thead class="table-dark">
                        <tr><th>เวลา</th><th>บิล</th><th>ลูกค้า</th><th>หวย</th><th>เลข</th><th>ประเภท</th><th>ยอดซื้อ</th><th>ส่วนลด</th><th>ยอดสุทธิ</th></tr>
                    </thead>
                    <tbody>
                        {% for tx in transactions %}
                        <tr>
                            <td><small>{{ tx[2] }}</small></td>
                            <td><code>{{ tx[7] }}</code></td>
                            <td><b>{{ tx[5] }}</b></td>
                            <td>{{ tx[14] }}</td>
                            <td><span class="text-primary fw-bold">{{ tx[8] }}</span></td>
                            <td>{{ tx[9] }}</td>
                            <td>{{ "{:,.2f}".format(tx[10] | float) }}</td>
                            <td class="text-danger">{{ "{:,.2f}".format(tx[12] | float) }}</td>
                            <td class="text-success fw-bold">{{ "{:,.2f}".format(tx[13] | float) }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="9" class="text-muted">ยังไม่มีรายการขาย</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get("/agent-reports", response_class=HTMLResponse)
def agent_reports_page(user: str):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        role_res = c.fetchone()
        role = role_res[0] if role_res else "Agent"

        if role == 'Admin':
            c.execute("SELECT * FROM Transactions ORDER BY id DESC LIMIT 100")
        else:
            c.execute("SELECT * FROM Transactions WHERE username = %s ORDER BY id DESC LIMIT 100", (user,))
        transactions = c.fetchall()

        if role == 'Admin':
            c.execute("SELECT SUM(amount), SUM(net) FROM Transactions")
        else:
            c.execute("SELECT SUM(amount), SUM(net) FROM Transactions WHERE username = %s", (user,))
        sum_res = c.fetchone()
        total_sales = float(sum_res[0] or 0) if sum_res and sum_res[0] else 0.0
        total_net = float(sum_res[1] or 0) if sum_res and sum_res[1] else 0.0
        conn.close()
    except:
        transactions = []
        total_sales, total_net = 0.0, 0.0

    return Template(AGENT_REPORTS_TEMPLATE).render(
        username=user, transactions=transactions, total_sales=total_sales, total_net=total_net
    )

@app.get("/logout")
def logout():
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
