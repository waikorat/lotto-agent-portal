from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template
import psycopg2
from datetime import datetime, timedelta

app = FastAPI(title="LuckyNumber Agent Portal - Full Enterprise Unified")

DB_URI = "postgresql://postgres.mpyswshlrxwpirzdexrn:Clublifekorat3888@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"

def connect_db():
    return psycopg2.connect(DB_URI)

def get_thai_time():
    return datetime.utcnow() + timedelta(hours=7)

# --- Startup Migration ตารางและคอลัมน์พื้นฐานทั้งหมด ---
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
                settle_type VARCHAR(20),
                note TEXT,
                timestamp TEXT
            );
        """)
        # ตรวจสอบและเพิ่มคอลัมน์ close_time ใน LotteryCampaigns
        c.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='lotterycampaigns' and column_name='close_time') THEN
                    ALTER TABLE LotteryCampaigns ADD COLUMN close_time VARCHAR(100);
                END IF;
            END $$;
        """)
        # ตรวจสอบคอลัมน์ใน Users
        columns_to_add = [
            ("pay_3d", "NUMERIC(10,2) DEFAULT 500"),
            ("pay_3tod", "NUMERIC(10,2) DEFAULT 100"),
            ("pay_2d", "NUMERIC(10,2) DEFAULT 70"),
            ("pay_run_top", "NUMERIC(10,2) DEFAULT 3.2"),
            ("pay_run_bot", "NUMERIC(10,2) DEFAULT 4.2"),
            ("disc_3d", "NUMERIC(5,2) DEFAULT 0"),
            ("disc_2d", "NUMERIC(5,2) DEFAULT 0"),
            ("disc_run", "NUMERIC(5,2) DEFAULT 0"),
            ("disc_total", "NUMERIC(5,2) DEFAULT 0")
        ]
        for col_name, col_type in columns_to_add:
            c.execute(f"""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' and column_name='{col_name}') THEN
                        ALTER TABLE Users ADD COLUMN {col_name} {col_type};
                    END IF;
                END $$;
            """)
        conn.commit()
        conn.close()
    except Exception as e:
        print("Startup Error:", e)

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
        {% if error %}<div class="alert alert-danger py-2 small text-center">{{ error }}</div>{% endif %}
        <form method="POST" action="/login">
            <div class="mb-3"><label class="form-label small fw-bold">Username</label><input type="text" name="username" class="form-control" required autofocus></div>
            <div class="mb-3"><label class="form-label small fw-bold">Password</label><input type="password" name="password" class="form-control" required></div>
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
            return RedirectResponse(url=f"/dashboard?user={username}", status_code=status.HTTP_303_SEE_OTHER)
        else:
            return RedirectResponse(url="/login?error=Username%20or%20Password%20ไม่ถูกต้อง", status_code=status.HTTP_303_SEE_OTHER)
    except:
        return RedirectResponse(url="/login?error=DB%20Error", status_code=status.HTTP_303_SEE_OTHER)

# ================= Layout หลัก (รวมเมนูด้านบนครอบคลุมทุกฟังก์ชัน) =================
UNIFIED_LAYOUT = """
<style>
    body { background-color: #f7e6d0; font-family: 'Segoe UI', sans-serif; margin: 0; }
    .top-navbar { background-color: #000; border-bottom: 2px solid #d4af37; padding: 5px 15px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; justify-content: space-between; }
    .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 1.4rem; color: #f3e5ab; margin-right: 10px; }
    .top-nav-menu { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
    .top-nav-menu a { color: #fff; text-decoration: none; font-size: 0.8rem; padding: 4px 8px; border-radius: 4px; background: #1a1a1a; border: 1px solid #333; }
    .top-nav-menu a:hover, .top-nav-menu a.active { background: #d4af37; color: #000; font-weight: bold; }
    .sticky-timer { position: sticky; top: 10px; z-index: 1000; float: right; background: #dc3545; color: white; padding: 8px 15px; border-radius: 8px; font-weight: bold; box-shadow: 0 4px 10px rgba(0,0,0,0.3); border: 2px solid #fff; }
</style>
<div class="top-navbar">
    <div class="d-flex align-items-center">
        <span class="logo-text">LuckyNumber ERP</span>
        <div class="top-nav-menu">
            <a href="/dashboard?user={{ username }}">แดชบอร์ด</a>
            <a href="/select-market?user={{ username }}">บันทึกโพย</a>
            <a href="/admin-campaigns?user={{ username }}">จัดการงวดหวย</a>
            <a href="/admin-blocked?user={{ username }}">เลขอั้น</a>
            <a href="/admin-users?user={{ username }}">จัดการผู้ใช้</a>
            <a href="/customer-rates-page?user={{ username }}">เรตลูกค้า</a>
            <a href="/agent-settlement?user={{ username }}">บัญชีรับ-จ่าย</a>
            <a href="/agent-reports?user={{ username }}">รายงานยอดขาย</a>
            <a href="/change-password?user={{ username }}" class="text-warning">เปลี่ยนรหัสผ่าน</a>
            <a href="/system-reset?user={{ username }}" class="text-danger">รีเซ็ตระบบ</a>
        </div>
    </div>
    <div>
        <span class="text-warning small me-2">ผู้ใช้งาน: <b>{{ username }} ({{ role }})</b></span>
        <a href="/login" class="btn btn-danger btn-sm fw-bold px-3">ออกจากระบบ</a>
    </div>
</div>
"""

# ================= 2. แดชบอร์ดหลัก =================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(user: str):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT role FROM Users WHERE username=%s", (user,))
    res = c.fetchone()
    role = res[0] if res else "Agent"
    conn.close()
    
    html = """
    <!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><title>Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"></head>
    <body class="bg-light">
    """ + UNIFIED_LAYOUT.replace("{{ username }}", user).replace("{{ role }}", role) + """
    <div class="container my-5 text-center">
        <h1 class="text-primary fw-bold mb-3">ยินดีต้อนรับสู่ระบบจัดการลอตเตอรี่ออนไลน์ (Enterprise Unified)</h1>
        <p class="text-muted">เลือกเมนูด้านบนเพื่อเริ่มต้นใช้งานระบบบันทึกโพย จัดการสมาชิก หรือตรวจสอบรายงาน</p>
        <a href="/select-market?user=""" + user + """" class="btn btn-warning btn-lg fw-bold px-5 mt-3">🎟️ เริ่มต้นบันทึกโพยหวย</a>
    </div></body></html>
    """
    return html

# ================= 3. หน้าเลือกตลาด / งวดหวย =================
SELECT_MARKET_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8"><title>เลือกลอตเตอรี่ / ตลาด</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    """ + UNIFIED_LAYOUT + """
</head>
<body>
    <div class="container my-4" style="max-width: 900px;">
        <h3 class="fw-bold mb-3">📌 เลือกลอตเตอรี่ / ตลาดหวยที่เปิดให้แทง</h3>
        <div class="list-group">
            {% for m in markets %}
            <a href="/portal?user={{ username }}&market={{ m[1] }}&draw={{ m[2] }}" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center py-3 mb-2 border rounded shadow-sm bg-white">
                <div>
                    <h5 class="mb-1 text-primary fw-bold">🎟️ {{ m[1] }}</h5>
                    <small class="text-muted">งวดวันที่: <b>{{ m[2] }}</b> | ปิดรับ: <span class="text-danger fw-bold">{{ m[4] if m[4] else '-' }}</span> | สถานะ: <span class="badge bg-success">{{ m[3] }}</span></small>
                </div>
                <span class="btn btn-outline-primary btn-sm fw-bold">เข้าคีย์โพย ➡️</span>
            </a>
            {% else %}
            <div class="alert alert-warning text-center">ยังไม่มีตลาดหวยที่เปิดอยู่ในขณะนี้ (สามารถไปเพิ่มงวดได้ที่เมนู "จัดการงวดหวย")</div>
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
        c.execute("SELECT id, lotto_name, draw_date, status, close_time FROM LotteryCampaigns WHERE status='Active' ORDER BY id DESC")
        markets = c.fetchall()
        conn.close()
    except:
        role, markets = "Agent", []
    return Template(SELECT_MARKET_TEMPLATE).render(username=user, role=role, markets=markets)


# ================= Helper ดึงเลขอั้น =================
def get_blocked_display_data(draw_date):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT raw_num, status, type FROM BlockedNumbers WHERE (draw_date = %s OR draw_date ILIKE %s)", (draw_date, f"%{draw_date}%"))
        rows = c.fetchall()
        conn.close()
        l_c, l_3, l_2 = [], [], []
        seen_c, seen_3, seen_2 = set(), set(), set()
        for r_num, status_val, type_val in rows:
            if not r_num: continue
            num_str = str(r_num).strip()
            if status_val == "ปิดรับ":
                if num_str not in seen_c: seen_c.add(num_str); l_c.append(num_str)
            else:
                if len(num_str) == 3 or type_val == "3ตัว":
                    if num_str not in seen_3: seen_3.add(num_str); l_3.append(num_str)
                elif len(num_str) == 2 or type_val == "2ตัว":
                    if num_str not in seen_2: seen_2.add(num_str); l_2.append(num_str)
        return ", ".join(l_c), ", ".join(l_3), ", ".join(l_2)
    except:
        return "", "", ""


# ================= 4. หน้าจอหลัก POS (บันทึกโพย + Sticky Timer + เรตเปลี่ยนตามลูกค้า) =================
PORTAL_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8"><title>บันทึกโพยหวย</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    """ + UNIFIED_LAYOUT + """
    <style>
        .market-banner { background-color: #dc3545; color: white; padding: 8px 15px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; font-weight: bold; margin-bottom: 15px; }
        .quick-btn { background-color: #0d6efd; color: white; font-weight: bold; border: none; padding: 8px 15px; border-radius: 6px; flex-grow: 1; font-size: 0.9rem; }
        .rate-table th, .rate-table td { font-size: 0.75rem; padding: 3px !important; color: white; background-color: #1a1a1a !important; border-color: #444 !important; }
        .main-container { display: flex; height: calc(100vh - 50px); }
        .sidebar-left { width: 280px; background-color: #000; color: white; border-right: 2px solid #d4af37; padding: 15px; flex-shrink: 0; overflow-y: auto; }
        .content-center { flex-grow: 1; padding: 15px; overflow-y: auto; }
        .sidebar-right { width: 320px; background-color: rgba(255,255,255,0.6); border-left: 2px solid #d4af37; padding: 15px; flex-shrink: 0; overflow-y: auto; }
    </style>
    <script>
        function startCountdown(closeTimeString) {
            let el = document.getElementById('sticky-timer');
            if(!closeTimeString) { el.innerText = "⏰ ไม่ระบุเวลาปิดรับ"; return; }
            let countDownDate = new Date(closeTimeString).getTime();
            if(isNaN(countDownDate)) {
                // ถ้า parse วันที่ตรงๆ ไม่ได้ ให้จำลองเวลาเหลือ 2 ชม.
                countDownDate = new Date().getTime() + (2 * 60 * 60 * 1000);
            }
            let x = setInterval(function() {
                let now = new Date().getTime();
                let distance = countDownDate - now;
                if (distance < 0) {
                    clearInterval(x);
                    el.innerText = "⏰ ปิดรับแทงแล้ว";
                    el.style.background = "#6c757d";
                } else {
                    let hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                    let minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                    let seconds = Math.floor((distance % (1000 * 60)) / 1000);
                    el.innerText = `⏳ ปิดรับใน: ${hours}ชม. ${minutes}น. ${seconds}ว.`;
                }
            }, 1000);
        }
    </script>
</head>
<body onload="startCountdown('{{ close_time }}')">
    <div class="main-container" style="width: 100%;">
        <!-- Sidebar ซ้าย: เลือกชื่อลูกค้า/ผู้ใช้ และแสดงเรตตามที่เลือก -->
        <div class="sidebar-left">
            <div class="user-box p-2 bg-dark border border-secondary mb-3 rounded">
                <div class="fw-bold text-warning small mb-1">ข้อมูลผู้ใช้งาน</div>
                <div class="small text-white">ล็อกอิน: <b>{{ username }}</b></div>
            </div>

            <form method="GET" action="/portal" id="customerForm">
                <input type="hidden" name="user" value="{{ username }}">
                <input type="hidden" name="market" value="{{ market }}">
                <input type="hidden" name="draw" value="{{ draw_date }}">
                <div class="mb-3">
                    <label class="form-label small fw-bold text-warning">เลือกชื่อลูกค้า / ผู้ใช้ใต้สายงาน:</label>
                    <select name="customer_id" class="form-select form-select-sm" onchange="document.getElementById('customerForm').submit()">
                        {% for cust in customers %}
                        <option value="{{ cust[0] }}" {% if cust[0]|string == customer_id|string %}selected{% endif %}>{{ cust[1] }}</option>
                        {% endfor %}
                    </select>
                </div>
            </form>

            <div class="mb-3">
                <div class="small fw-bold text-info mb-1">อัตราจ่าย: {{ market }} ({{ current_customer_name }})</div>
                <table class="table table-bordered rate-table text-center">
                    <thead><tr><th>ประเภท</th><th>รางวัล</th><th>ส่วนลด</th></tr></thead>
                    <tbody>
                        <tr><td>3ตัวตรง</td><td>{{ rates.pay_3d }}</td><td>{{ rates.disc_3d if rates.disc_3d > 0 else rates.disc_total }}%</td></tr>
                        <tr><td>3ตัวโต๊ด</td><td>{{ rates.pay_3tod }}</td><td>{{ rates.disc_3d if rates.disc_3d > 0 else rates.disc_total }}%</td></tr>
                        <tr><td>2ตัวบน/ล่าง</td><td>{{ rates.pay_2d }}</td><td>{{ rates.disc_2d if rates.disc_2d > 0 else rates.disc_total }}%</td></tr>
                        <tr><td>วิ่งบน/ล่าง</td><td>{{ rates.pay_run_top }}/{{ rates.pay_run_bot }}</td><td>{{ rates.disc_run if rates.disc_run > 0 else rates.disc_total }}%</td></tr>
                    </tbody>
                </table>
            </div>

            <div class="menu-title">เมนูด่วน</div>
            <a href="/select-market?user={{ username }}" class="menu-item">▶ เปลี่ยนตลาด/งวด</a>
            <a href="/admin-users?user={{ username }}" class="menu-item text-warning">👥 จัดการสมาชิก/ผู้ใช้</a>
            <a href="/agent-reports?user={{ username }}" class="menu-item text-success">📊 รายงานยอดขาย</a>
        </div>

        <!-- Content ตรงกลาง: คีย์โพย -->
        <div class="content-center">
            <!-- Sticky Timer ลอยตัวมุมขวาบนในตำแหน่งนี้ตลอดเวลา -->
            <div id="sticky-timer" class="sticky-timer">⏳ กำลังคำนวณเวลา...</div>

            <div class="market-banner">
                <div>🎟️ {{ market }} งวดวันที่ {{ draw_date }} | เลือก: <span class="text-warning">{{ current_customer_name }}</span></div>
            </div>

            <div class="quick-btn-group d-flex gap-2 mb-3">
                <button type="button" class="quick-btn" onclick="alert('ฟังก์ชัน 6กลับ')">6กลับ</button>
                <button type="button" class="quick-btn" onclick="alert('ฟังก์ชัน 19ประตู')">รูด19ประตู</button>
                <button type="button" class="quick-btn" onclick="alert('รูดหน้า')">รูดหน้า</button>
                <button type="button" class="quick-btn" onclick="alert('รูดหลัง')">รูดหลัง</button>
            </div>

            <form method="POST" action="/portal-add-draft" class="p-3 bg-white rounded shadow-sm border mb-3">
                <input type="hidden" name="user" value="{{ username }}">
                <input type="hidden" name="market" value="{{ market }}">
                <input type="hidden" name="draw" value="{{ draw_date }}">
                <input type="hidden" name="customer_id" value="{{ customer_id }}">
                <div class="row g-2 align-items-center">
                    <div class="col-md-4"><label class="small fw-bold">ตัวเลข</label><input type="text" name="num_input" class="form-control" placeholder="พิมพ์เลข..." required></div>
                    <div class="col-md-4"><label class="small fw-bold">บน / 3ตัวตรง</label><input type="number" step="any" name="top_amt" class="form-control" placeholder="จำนวนเงิน"></div>
                    <div class="col-md-4"><label class="small fw-bold">ล่าง / 3ตัวโต๊ด</label><input type="number" step="any" name="bot_amt" class="form-control" placeholder="จำนวนเงิน"></div>
                </div>
                <button type="submit" class="btn btn-primary btn-sm fw-bold mt-2 px-4">เพิ่มรายการ</button>
            </form>

            <div class="card shadow-sm p-3 bg-white">
                <h5 class="fw-bold mb-2 text-center">รายการร่าง (รอออกบิล)</h5>
                <table class="table table-sm table-bordered text-center" style="font-size:0.85rem;">
                    <thead class="table-dark"><tr><th>เลข</th><th>ประเภท</th><th>เดิมพัน</th><th>เรตจ่าย</th><th>ส่วนลด</th></tr></thead>
                    <tbody>
                        {% for d in drafts %}
                        <tr><td><b>{{ d[1] }}</b></td><td>{{ d[4] }}</td><td>{{ d[2] }}</td><td>{{ d[5] }}</td><td>{{ d[6] }}</td></tr>
                        {% else %}
                        <tr><td colspan="5" class="text-muted">ยังไม่มีรายการ</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Sidebar ขวา: เลขอั้น -->
        <div class="sidebar-right">
            <h6 class="text-center fw-bold text-danger mb-3">🚫 เลขอั้นประจำงวด</h6>
            <label class="small fw-bold">เลขอั้นปิดรับ:</label>
            <textarea class="form-control form-control-sm mb-2 text-danger fw-bold bg-light" rows="2" readonly>{{ block_closed }}</textarea>
            <label class="small fw-bold">เลขอั้นจ่ายครึ่ง:</label>
            <textarea class="form-control form-control-sm bg-light" rows="3" readonly>{{ block_half }}</textarea>
        </div>
    </div>
</body>
</html>
"""

@app.get("/portal", response_class=HTMLResponse)
def portal_page(user: str, market: str, draw: str, customer_id: int = None):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        role_res = c.fetchone()
        role = role_res[0] if role_res else "Agent"

        customers = []
        # ลูกค้ารายย่อย
        c.execute("SELECT id, name FROM Customers ORDER BY id DESC")
        for row in c.fetchall():
            customers.append((row[0], row[1]))

        # ผู้ใช้ระบบ ใช้คำนำหน้าว่า "user: [ชื่อผู้ใช้]" ตามที่ต้องการ
        c.execute("SELECT id, username, pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_total FROM Users ORDER BY id DESC")
        for row in c.fetchall():
            customers.append((f"user_{row[0]}", f"user: {row[1]}"))

        if not customer_id and customers:
            customer_id = customers[0][0]

        current_customer_name = ""
        for cust in customers:
            if str(cust[0]) == str(customer_id):
                current_customer_name = cust[1]
                break

        # ดึงเรตตามรายชื่อที่เลือก ณ ขณะนั้น (ให้ดึงครบทุกคอลัมน์ทั้งอัตราจ่ายและส่วนลด)
        user_rates = {"pay_3d": 500, "pay_3tod": 100, "pay_2d": 70, "pay_run_top": 3.2, "pay_run_bot": 4.2, "disc_total": 0, "disc_3d": 0, "disc_2d": 0, "disc_run": 0}
        
        if str(customer_id).startswith("user_"):
            u_id = str(customer_id).replace("user_", "")
            c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total FROM Users WHERE id=%s", (u_id,))
            ur = c.fetchone()
            if ur:
                user_rates.update({
                    "pay_3d": float(ur[0] or 500), 
                    "pay_3tod": float(ur[1] or 100), 
                    "pay_2d": float(ur[2] or 70), 
                    "pay_run_top": float(ur[3] or 3.2), 
                    "pay_run_bot": float(ur[4] or 4.2),
                    "disc_3d": float(ur[5] or 0),
                    "disc_2d": float(ur[6] or 0),
                    "disc_run": float(ur[7] or 0),
                    "disc_total": float(ur[8] or 0)
                })
        else:
            c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total FROM Customers WHERE id=%s", (customer_id,))
            cr = c.fetchone()
            if cr:
                user_rates.update({
                    "pay_3d": float(cr[0] or 500), 
                    "pay_3tod": float(cr[1] or 100), 
                    "pay_2d": float(cr[2] or 70), 
                    "pay_run_top": float(cr[3] or 3.2), 
                    "pay_run_bot": float(cr[4] or 4.2),
                    "disc_3d": float(cr[5] or 0),
                    "disc_2d": float(cr[6] or 0),
                    "disc_run": float(cr[7] or 0),
                    "disc_total": float(cr[8] or 0)
                })

        c.execute("SELECT close_time FROM LotteryCampaigns WHERE lotto_name=%s AND draw_date=%s", (market, draw))
        cr_res = c.fetchone()
        close_time = cr_res[0] if cr_res and cr_res[0] else ""

        c.execute("SELECT id, num, amt_teng, status, type, payout_rate, discount, net FROM TempDraft WHERE username=%s AND customer_id=%s", (user, str(customer_id)))
        drafts = c.fetchall()

        b_closed, b_3d, b_2d = get_blocked_display_data(draw)
        conn.close()

        return Template(PORTAL_TEMPLATE).render(
            username=user, role=role, market=market, draw_date=draw,
            customers=customers, customer_id=customer_id, current_customer_name=current_customer_name,
            drafts=drafts, block_closed=b_closed, block_half=f"3ตัว: {b_3d} | 2ตัว: {b_2d}",
            rates=user_rates, close_time=close_time
        )
    except Exception as e:
        return f"Error: {str(e)}"

@app.post("/portal-add-draft")
def portal_add_draft(user: str = Form(...), market: str = Form(...), draw: str = Form(...), num_input: str = Form(...), top_amt: float = Form(0), customer_id: str = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, 'Customer', %s, %s, '3ตัวตรง', 500, 0, %s, 'ปกติ')", (user, customer_id, num_input, top_amt, top_amt))
        conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}", status_code=303)


# ================= 5. หน้าจอจัดการผู้ใช้ / สมาชิก (Admin Users) =================
ADMIN_USERS_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head><meta charset="UTF-8"><title>จัดการผู้ใช้งานระบบ</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
""" + UNIFIED_LAYOUT + """
</head>
<body>
    <div class="container my-4" style="max-width: 1100px;">
        <h3 class="fw-bold mb-4 text-primary">👥 จัดการบัญชีผู้ใช้ / สมาชิก (ลิงก์ตรงกับระบบหลักแบบเรียลไทม์)</h3>
        {% if msg %}<div class="alert alert-success">{{ msg }}</div>{% endif %}
        <div class="row">
            <div class="col-md-5">
                <div class="card shadow p-4 bg-white">
                    <h5 class="fw-bold text-success mb-3">⚙️ สร้างบัญชีผู้ใช้ใหม่</h5>
                    <form method="POST" action="/admin-create-user">
                        <input type="hidden" name="admin_user" value="{{ username }}">
                        <div class="mb-2"><label class="small fw-bold">Username:</label><input type="text" name="new_username" class="form-control form-control-sm" required></div>
                        <div class="mb-2"><label class="small fw-bold">Password:</label><input type="password" name="new_password" class="form-control form-control-sm" required></div>
                        <div class="mb-3"><label class="small fw-bold">สิทธิ์ (Role):</label>
                            <select name="role" class="form-select form-select-sm">
                                <option value="Master Agent">Master Agent</option>
                                <option value="Agent">Agent</option>
                                <option value="Member">Member</option>
                                <option value="Admin">Admin</option>
                            </select>
                        </div>
                        <button type="submit" class="btn btn-success w-100 fw-bold">💾 บันทึกผู้ใช้</button>
                    </form>
                </div>
            </div>
            <div class="col-md-7">
                <div class="card shadow p-4 bg-white">
                    <h5 class="fw-bold text-primary mb-3">🗂️ รายชื่อสมาชิกใต้สายงาน (ตาราง Users)</h5>
                    <table class="table table-striped table-bordered text-center align-middle" style="font-size: 0.85rem;">
                        <thead class="table-dark"><tr><th>ID</th><th>Username</th><th>สิทธิ์</th><th>จัดการ</th></tr></thead>
                        <tbody>
                            {% for u in users %}
                            <tr>
                                <td>{{ u[0] }}</td>
                                <td><b>{{ u[1] }}</b></td>
                                <td><span class="badge bg-secondary">{{ u[3] }}</span></td>
                                <td><a href="/edit-user?id={{ u[0] }}&user={{ username }}" class="btn btn-sm btn-warning">แก้ไข</a></td>
                            </tr>
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

@app.get("/admin-users", response_class=HTMLResponse)
def admin_users_page(user: str, msg: str = None):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        role = c.fetchone()[0]
        c.execute("SELECT id, username, password, role FROM Users ORDER BY id DESC")
        users = c.fetchall()
        conn.close()
    except: role, users = "Agent", []
    return Template(ADMIN_USERS_TEMPLATE).render(username=user, role=role, users=users, msg=msg)

@app.post("/admin-create-user")
def admin_create_user(admin_user: str = Form(...), new_username: str = Form(...), new_password: str = Form(...), role: str = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("INSERT INTO Users (username, password, role) VALUES (%s, %s, %s)", (new_username, new_password, role))
        conn.commit()
        conn.close()
        msg = f"สร้างผู้ใช้ '{new_username}' สำเร็จ!"
    except Exception as e:
        msg = f"Error: {e}"
    return RedirectResponse(url=f"/admin-users?user={admin_user}&msg={msg}", status_code=303)


# ================= 6. หน้าจอแก้ไขข้อมูลผู้ใช้ (Edit User) =================
EDIT_USER_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head><meta charset="UTF-8"><title>แก้ไขข้อมูลผู้ใช้</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
""" + UNIFIED_LAYOUT + """
</head>
<body>
    <div class="container my-4" style="max-width: 600px;">
        <h3 class="fw-bold mb-4 text-warning">✏️ แก้ไขข้อมูลผู้ใช้ / ลูกค้า</h3>
        <div class="card shadow p-4 bg-white">
            <form method="POST" action="/update-user">
                <input type="hidden" name="user" value="{{ username }}">
                <input type="hidden" name="user_id" value="{{ u[0] }}">
                <div class="mb-3"><label class="fw-bold">Username:</label><input type="text" name="username_val" class="form-control" value="{{ u[1] }}" required></div>
                <div class="mb-3"><label class="fw-bold">Role / สิทธิ์:</label><input type="text" name="role_val" class="form-control" value="{{ u[2] }}" required></div>
                <button type="submit" class="btn btn-warning w-100 fw-bold">💾 บันทึกการแก้ไข</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

@app.get("/edit-user", response_class=HTMLResponse)
def edit_user_page(id: int, user: str):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT role FROM Users WHERE username=%s", (user,))
    role = c.fetchone()[0]
    c.execute("SELECT id, username, role FROM Users WHERE id=%s", (id,))
    u = c.fetchone()
    conn.close()
    return Template(EDIT_USER_TEMPLATE).render(username=user, role=role, u=u)

@app.post("/update-user")
def update_user(user: str = Form(...), user_id: int = Form(...), username_val: str = Form(...), role_val: str = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("UPDATE Users SET username=%s, role=%s WHERE id=%s", (username_val, role_val, user_id))
        conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url=f"/admin-users?user={user}&msg=แก้ไขสำเร็จ", status_code=303)


# ================= 7. เมนูเปลี่ยนรหัสผ่านสำหรับผู้ใช้งาน (Change Password) =================
CHANGE_PASSWORD_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head><meta charset="UTF-8"><title>เปลี่ยนรหัสผ่าน</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
""" + UNIFIED_LAYOUT + """
</head>
<body>
    <div class="container my-5" style="max-width: 500px;">
        <h3 class="fw-bold mb-4 text-primary">🔑 เปลี่ยนรหัสผ่านผู้ใช้งาน</h3>
        {% if msg %}<div class="alert alert-success">{{ msg }}</div>{% endif %}
        {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
        <div class="card shadow p-4 bg-white">
            <form method="POST" action="/update-password">
                <input type="hidden" name="user" value="{{ username }}">
                <div class="mb-3">
                    <label class="form-label fw-bold">รหัสผ่านปัจจุบัน:</label>
                    <input type="password" name="old_password" class="form-control" required>
                </div>
                <div class="mb-3">
                    <label class="form-label fw-bold">รหัสผ่านใหม่:</label>
                    <input type="password" name="new_password" class="form-control" required>
                </div>
                <div class="mb-3">
                    <label class="form-label fw-bold">ยืนยันรหัสผ่านใหม่:</label>
                    <input type="password" name="confirm_password" class="form-control" required>
                </div>
                <button type="submit" class="btn btn-primary w-100 fw-bold py-2">💾 บันทึกรหัสผ่านใหม่</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

@app.get("/change-password", response_class=HTMLResponse)
def change_password_page(user: str, msg: str = None, error: str = None):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT role FROM Users WHERE username=%s", (user,))
    res = c.fetchone()
    role = res[0] if res else "Agent"
    conn.close()
    return Template(CHANGE_PASSWORD_TEMPLATE).render(username=user, role=role, msg=msg, error=error)

@app.post("/update-password")
def update_password(user: str = Form(...), old_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if new_password != confirm_password:
        return RedirectResponse(url=f"/change-password?user={user}&error=รหัสผ่านใหม่ไม่ตรงกัน", status_code=303)
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT id FROM Users WHERE username=%s AND password=%s", (user, old_password))
        user_check = c.fetchone()
        if not user_check:
            conn.close()
            return RedirectResponse(url=f"/change-password?user={user}&error=รหัสผ่านปัจจุบันไม่ถูกต้อง", status_code=303)
        c.execute("UPDATE Users SET password=%s WHERE username=%s", (new_password, user))
        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/change-password?user={user}&msg=เปลี่ยนรหัสผ่านสำเร็จเรียบร้อยแล้ว", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/change-password?user={user}&error=Error: {str(e)}", status_code=303)


# ================= หน้าจอเสริมอื่นๆ (Campaigns, Blocked, Rates, Settlement, Reports, Reset) =================
@app.get("/admin-campaigns", response_class=HTMLResponse)
def admin_campaigns(user: str):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT role FROM Users WHERE username=%s", (user,))
    role = c.fetchone()[0]
    c.execute("SELECT id, lotto_name, draw_date, status, close_time FROM LotteryCampaigns ORDER BY id DESC")
    campaigns = c.fetchall()
    conn.close()
    return Template("""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">""" + UNIFIED_LAYOUT + """</head><body><div class="container my-4"><h3>จัดการงวดหวยและตลาด</h3><table class="table table-bordered mt-3"><thead class="table-dark"><tr><th>หวย</th><th>งวด</th><th>เวลาปิดรับ</th><th>สถานะ</th></tr></thead><tbody>{% for cp in campaigns %}<tr><td>{{cp[1]}}</td><td>{{cp[2]}}</td><td>{{cp[4]}}</td><td>{{cp[3]}}</td></tr>{% endfor %}</tbody></table></div></body></html>""").render(username=user, role=role, campaigns=campaigns)

@app.get("/admin-blocked", response_class=HTMLResponse)
def admin_blocked(user: str):
    return RedirectResponse(url=f"/select-market?user={user}", status_code=303)

@app.get("/customer-rates-page", response_class=HTMLResponse)
def customer_rates(user: str):
    return RedirectResponse(url=f"/select-market?user={user}", status_code=303)

@app.get("/agent-settlement", response_class=HTMLResponse)
def agent_settlement(user: str):
    return RedirectResponse(url=f"/select-market?user={user}", status_code=303)

@app.get("/agent-reports", response_class=HTMLResponse)
def agent_reports(user: str):
    return RedirectResponse(url=f"/select-market?user={user}", status_code=303)

@app.get("/system-reset", response_class=HTMLResponse)
def system_reset_page(user: str, error: str = None):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT role FROM Users WHERE username=%s", (user,))
    role = c.fetchone()[0]
    conn.close()
    return Template("""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">""" + UNIFIED_LAYOUT + """</head><body><div class="container my-5 text-center" style="max-width:500px;"><div class="card shadow p-4 border-danger"><h3 class="text-danger fw-bold">⚠️ รีเซ็ตระบบ</h3>{% if error %}<div class="alert alert-danger">{{error}}</div>{% endif %}<form method="POST" action="/execute-system-reset"><input type="hidden" name="username" value="{{username}}"><div class="mb-3 text-start"><label class="fw-bold">รหัสผ่าน Admin:</label><input type="password" name="admin_password" class="form-control" required></div><button type="submit" class="btn btn-danger w-100 fw-bold" onclick="return confirm('ยืนยันล้างข้อมูลทั้งหมด?')">ล้างข้อมูลและรีเซ็ตระบบ</button></form></div></div></body></html>""").render(username=user, role=role, error=error)

@app.post("/execute-system-reset")
def execute_system_reset(username: str = Form(...), admin_password: str = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT id FROM Users WHERE username=%s AND password=%s AND role='Admin'", (username, admin_password))
        if not c.fetchone():
            conn.close()
            return RedirectResponse(url=f"/system-reset?user={username}&error=รหัสผ่านไม่ถูกต้อง", status_code=303)
        c.execute("DELETE FROM Transactions; DELETE FROM TempDraft; DELETE FROM BlockedNumbers; DELETE FROM CustomerLottoRates; DELETE FROM AgentSettlements; DELETE FROM DrawResults; DELETE FROM Customers; DELETE FROM LotteryCampaigns; DELETE FROM Users WHERE username != %s;", (username,))
        conn.commit()
        conn.close()
        return RedirectResponse(url="/login?error=รีเซ็ตระบบสำเร็จ", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/system-reset?user={username}&error={str(e)}", status_code=303)

@app.get("/logout")
def logout():
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
