from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Template
import psycopg2
from datetime import datetime, timedelta
import os

app = FastAPI(title="LuckyNumber Agent Portal - Enterprise Unified")

# ตรวจสอบและสร้างโฟลเดอร์ static อัตโนมัติหากยังไม่มี
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

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
        
        # 1. สร้างตาราง AgentSettlements
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
        
        # 2. สร้างตาราง CustomerLottoRates
        c.execute("""
            CREATE TABLE IF NOT EXISTS CustomerLottoRates (
                id SERIAL PRIMARY KEY,
                target_type VARCHAR(20),
                target_id VARCHAR(100),
                lotto_name VARCHAR(100),
                pay_3d NUMERIC(10,2),
                pay_3tod NUMERIC(10,2),
                pay_2d NUMERIC(10,2),
                pay_run_top NUMERIC(10,2),
                pay_run_bot NUMERIC(10,2),
                disc_3d NUMERIC(5,2),
                disc_2d NUMERIC(5,2),
                disc_run NUMERIC(5,2),
                disc_total NUMERIC(5,2)
            );
        """)

        # 3. แก้ไขประเภทข้อมูล customer_id ในตาราง TempDraft ให้เป็น VARCHAR(100)
        c.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='tempdraft') THEN
                    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tempdraft' AND column_name='customer_id' AND data_type != 'character varying') THEN
                        ALTER TABLE TempDraft ALTER COLUMN customer_id TYPE VARCHAR(100) USING customer_id::varchar;
                    END IF;
                END IF;
            END $$;
        """)
        
        # 4. เพิ่มคอลัมน์ที่ขาดหายในตาราง CustomerLottoRates
        rate_cols_to_add = [
            ("target_type", "VARCHAR(20) DEFAULT 'Customer'"),
            ("target_id", "VARCHAR(100)"),
            ("lotto_name", "VARCHAR(100)"),
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
        for col_name, col_type in rate_cols_to_add:
            c.execute(f"""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='customerlottorates' and column_name='{col_name}') THEN
                        ALTER TABLE CustomerLottoRates ADD COLUMN {col_name} {col_type};
                    END IF;
                END $$;
            """)

        # 5. ตรวจสอบคอลัมน์ close_time ใน LotteryCampaigns
        c.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='lotterycampaigns' and column_name='close_time') THEN
                    ALTER TABLE LotteryCampaigns ADD COLUMN close_time VARCHAR(100);
                END IF;
            END $$;
        """)

        # 6. ตรวจสอบคอลัมน์ใน Users
        user_cols_to_add = [
            ("parent_username", "VARCHAR(100) DEFAULT 'admin'"),
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
        for col_name, col_type in user_cols_to_add:
            c.execute(f"""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' and column_name='{col_name}') THEN
                        ALTER TABLE Users ADD COLUMN {col_name} {col_type};
                    END IF;
                END $$;
            """)

        # 7. ตรวจสอบคอลัมน์ใน Customers
        c.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='customers' and column_name='owner_username') THEN
                    ALTER TABLE Customers ADD COLUMN owner_username VARCHAR(100) DEFAULT 'admin';
                END IF;
            END $$;
        """)
        
        conn.commit()
    except Exception as e:
        print("Startup Migration Error:", e)
    finally:
        if 'conn' in locals(): conn.close()

# ================= Helper ดึงสัญลักษณ์โลโก้ =================
def get_lotto_logo(lotto_name):
    name = lotto_name.lower()
    if "ลาวพัฒนา" in name: return "/static/ลาวพัฒนาโลโก้.png"
    elif "รัฐบาล" in name: return "/static/สำนักงานสลากกินแบ่งรัฐบาล.png"
    elif "ฮานอย" in name: return "/static/สัญลักษณ์หวยฮานอย.png"
    elif "nasdaq" in name: return "/static/image_4326b7.png"
    elif "s&p" in name: return "/static/image_10cf86.png"
    elif "dow" in name or "ดาวโจนส์" in name: return "/static/dow jones logo.png"
    elif "nikkei" in name or "นิเคอิ" in name: return "/static/image_0ff5ed.png"
    elif "dax" in name or "เยอรมัน" in name: return "/static/image_0ff24b.png"
    elif "nifty" in name or "อินเดีย" in name: return "/static/image_0feba1.jpg"
    elif "kse" in name or "ปากีสถาน" in name: return "/static/image_0f892c.png"
    elif "ลาว" in name: return "https://upload.wikimedia.org/wikipedia/commons/5/56/Flag_of_Laos.svg"
    else: return "https://cdn-icons-png.flaticon.com/512/10383/10383210.png"

# ================= Helper ดึงข้อมูลดิบเลขอั้น =================
def get_blocked_display_data(draw_date):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT raw_num, status, type FROM BlockedNumbers WHERE (draw_date = %s OR draw_date ILIKE %s) AND is_raw = TRUE", (draw_date, f"%{draw_date}%"))
        rows = c.fetchall()
        if not rows:
            c.execute("SELECT raw_num, status, type FROM BlockedNumbers WHERE (draw_date = %s OR draw_date ILIKE %s)", (draw_date, f"%{draw_date}%"))
            rows = c.fetchall()
        
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
    finally:
        if 'conn' in locals(): conn.close()

# ================= UNIFIED LAYOUT CSS & NAVBAR =================
UNIFIED_LAYOUT = """
<style>
    * { box-sizing: border-box; }
    body { background-color: #f7e6d0; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 0; overflow-x: hidden; }
    .top-navbar { background-color: #000; border-bottom: 2px solid #d4af37; padding: 8px 15px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; width: 100%; }
    .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 1.3rem; color: #f3e5ab; margin-right: 10px; white-space: nowrap; }
    .top-nav-menu { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
    .top-nav-menu a { color: #fff; text-decoration: none; font-size: 0.8rem; padding: 4px 8px; border-radius: 4px; background: #1a1a1a; border: 1px solid #333; white-space: nowrap; }
    .top-nav-menu a:hover, .top-nav-menu a.active { background: #d4af37; color: #000; font-weight: bold; }
    
    .main-container { display: flex; width: 100vw; height: calc(100vh - 48px); overflow: hidden; }
    .sidebar-left { width: 260px; background-color: #000; color: white; border-right: 2px solid #d4af37; padding: 12px; flex-shrink: 0; overflow-y: auto; }
    .content-center { flex-grow: 1; padding: 15px; overflow-y: auto; background-color: #f7e6d0; height: 100%; }
    .sidebar-right { width: 280px; background-color: rgba(255,255,255,0.7); border-left: 2px solid #d4af37; padding: 12px; flex-shrink: 0; overflow-y: auto; }
    
    .table-responsive { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .card { width: 100%; max-width: 100%; word-break: break-word; }
    .sticky-timer { position: sticky; top: 10px; z-index: 1000; float: right; background: #dc3545; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 0.85rem; box-shadow: 0 2px 8px rgba(0,0,0,0.3); border: 2px solid #fff; }

    @media (max-width: 992px) {
        .main-container { flex-direction: column; height: auto; overflow: auto; }
        .sidebar-left, .sidebar-right { width: 100%; max-height: 250px; }
        .content-center { height: auto; }
    }
</style>
<div class="top-navbar">
    <div class="d-flex align-items-center flex-wrap">
        <span class="logo-text">LuckyNumber ERP</span>
        <div class="top-nav-menu">
            <a href="/select-market?user={{ username }}">บันทึกโพย</a>
            <a href="/agent-reports?user={{ username }}">รายงานผล</a>
            
            {% if role == 'Admin' or role == 'Master Agent' %}
            <a href="/admin-campaigns?user={{ username }}">จัดการงวดหวย</a>
            <a href="/admin-blocked?user={{ username }}">เลขอั้น</a>
            <a href="/admin-users?user={{ username }}">จัดการผู้ใช้</a>
            <a href="/manage-customers?user={{ username }}">จัดการลูกค้า</a>
            <a href="/customer-rates-page?user={{ username }}">เรตลูกค้าแยกหวย</a>
            <a href="/system-reset?user={{ username }}" class="text-danger">รีเซ็ตระบบ</a>
            {% endif %}
            
            <a href="/change-password?user={{ username }}" class="text-warning">เปลี่ยนรหัสผ่าน</a>
        </div>
    </div>
    <div class="d-flex align-items-center gap-2">
        <span class="text-warning small">สถานะ: <b>{{ role }} ({{ username }})</b></span>
        <a href="/login" class="btn btn-danger btn-sm fw-bold px-2 py-1" style="font-size: 0.75rem;">ออกจากระบบ</a>
    </div>
</div>
"""

# ================= 1. LOGIN =================
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8"><title>LuckyNumber - Login</title>
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

@app.get("/", response_class=HTMLResponse)
def index():
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

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
        
        if user:
            return RedirectResponse(url=f"/select-market?user={username}", status_code=status.HTTP_303_SEE_OTHER)
        else:
            return RedirectResponse(url="/login?error=Username%20or%20Password%20ไม่ถูกต้อง", status_code=status.HTTP_303_SEE_OTHER)
    except:
        return RedirectResponse(url="/login?error=DB%20Error", status_code=status.HTTP_303_SEE_OTHER)
    finally:
        if 'conn' in locals(): conn.close()

# ================= 2. หน้าเลือกงวดหวย (/select-market) =================
SELECT_MARKET_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8"><title>เลือกลอตเตอรี่ / ตลาด</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    """ + UNIFIED_LAYOUT + """
    <style>
        .market-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 15px; }
        .market-card { display: flex; align-items: center; padding: 15px; border-radius: 12px; background: #fff; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-left: 6px solid #d4af37; text-decoration: none; color: inherit; transition: transform 0.2s, box-shadow 0.2s; }
        .market-card:hover { transform: translateY(-5px); box-shadow: 0 8px 15px rgba(0,0,0,0.2); }
        .market-logo { width: 55px; height: 55px; object-fit: contain; border-radius: 50%; margin-right: 15px; background: #f8f9fa; padding: 3px; border: 1px solid #ccc; }
        .market-info { flex-grow: 1; overflow: hidden; }
        .market-title { font-size: 1.05rem; font-weight: bold; color: #000; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .market-meta { font-size: 0.8rem; color: #666; }
        .category-header { font-weight: bold; color: #dc3545; border-bottom: 2px solid #dc3545; padding-bottom: 5px; margin-top: 25px; margin-bottom: 15px; font-size: 1.2rem; }
    </style>
</head>
<body>
    <div class="container-fluid my-4 px-4">
        <h3 class="fw-bold mb-1 text-primary">📌 ตลาดหวยที่เปิดรับแทง</h3>
        <p class="text-muted small">เลือกงวดหวยที่ต้องการเข้าซื้อหวยหรือคีย์โพย</p>

        {% for cat_name, markets in categories.items() %}
        <h5 class="category-header">🎯 หมวดหมู่: {{ cat_name }}</h5>
        <div class="market-grid">
            {% for m in markets %}
            <a href="/portal?user={{ username }}&market={{ m.name }}&draw={{ m.draw }}" class="market-card">
                <img src="{{ m.logo }}" alt="logo" class="market-logo" onerror="this.src='https://cdn-icons-png.flaticon.com/512/10383/10383210.png'">
                <div class="market-info">
                    <div class="market-title">{{ m.name }}</div>
                    <div class="market-meta">งวด: <b>{{ m.draw }}</b></div>
                    <div class="market-meta">ปิดรับ: <span class="text-danger fw-bold">{{ m.close if m.close else '-' }}</span></div>
                </div>
                <div class="ms-2 text-end">
                    <span class="badge bg-success shadow-sm">{{ m.status }}</span>
                    <div class="text-primary fw-bold mt-1" style="font-size:0.75rem;">คีย์โพย ➡️</div>
                </div>
            </a>
            {% endfor %}
        </div>
        {% else %}
        <div class="alert alert-warning text-center mt-4 shadow-sm fw-bold">ยังไม่มีตลาดหวยที่เปิดอยู่ในขณะนี้</div>
        {% endfor %}
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
        role = res[0].strip() if res else "Member"
        c.execute("SELECT id, lotto_name, draw_date, status, close_time FROM LotteryCampaigns WHERE status='Active' ORDER BY id DESC")
        raw_markets = c.fetchall()

        categories = {"รัฐบาลไทย": [], "ฮานอย": [], "ลาว": [], "หุ้นต่างประเทศ": [], "อื่นๆ": []}
        for m in raw_markets:
            m_data = {"id": m[0], "name": m[1], "draw": m[2], "status": m[3], "close": m[4], "logo": get_lotto_logo(m[1])}
            if "รัฐบาล" in m[1]: categories["รัฐบาลไทย"].append(m_data)
            elif "ฮานอย" in m[1]: categories["ฮานอย"].append(m_data)
            elif "ลาว" in m[1]: categories["ลาว"].append(m_data)
            elif any(k in m[1].lower() for k in ["หุ้น", "nasdaq", "dow", "s&p", "nikkei", "dax", "nifty", "kse"]): categories["หุ้นต่างประเทศ"].append(m_data)
            else: categories["อื่นๆ"].append(m_data)

        categories = {k: v for k, v in categories.items() if len(v) > 0}
    except Exception as e:
        print("Market Load Error:", e)
        role, categories = "Member", {}
    finally:
        if 'conn' in locals(): conn.close()
        
    return Template(SELECT_MARKET_TEMPLATE).render(username=user, role=role, categories=categories)

# ================= 3. หน้าบันทึกโพย POS (/portal) =================
PORTAL_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8"><title>บันทึกโพยหวย</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    """ + UNIFIED_LAYOUT + """
    <style>
        .market-banner { background-color: #dc3545; color: white; padding: 10px 15px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; font-weight: bold; margin-bottom: 15px; }
        .quick-btn-group { display: flex; gap: 10px; margin-bottom: 10px; }
        .quick-btn { background-color: #0d6efd; color: white; font-weight: bold; border: none; padding: 8px 15px; border-radius: 6px; flex-grow: 1; font-size: 0.9rem; }
        .preview-box { background-color: #ccfeff; border: 2px solid #0dcaf0; padding: 10px; border-radius: 6px; font-family: monospace; font-weight: bold; font-size: 1.05rem; color: #000; margin-bottom: 12px; min-height: 45px; display: flex; align-items: center; flex-wrap: wrap; gap: 5px; }
        .entry-form-box { background-color: rgba(255,255,255,0.8); padding: 10px; border-radius: 6px; margin-bottom: 15px; border: 1px solid #ccc; }
        .sidebar-right { width: 320px; background-color: rgba(255,255,255,0.4); border-left: 2px solid #d4af37; padding: 15px; flex-shrink: 0; overflow-y: auto; }
        .recent-table th, .recent-table td { font-size: 0.75rem; padding: 4px !important; text-align: center; }
        .rate-table th, .rate-table td { font-size: 0.78rem; padding: 4px !important; color: white; background-color: #1a1a1a !important; border-color: #444 !important; }
        .menu-title { color: #fff; font-weight: bold; font-size: 0.88rem; margin-top: 15px; margin-bottom: 6px; border-bottom: 1px solid #444; padding-bottom: 3px; }
        .menu-item { display: block; color: #ccc; text-decoration: none; padding: 5px 8px; font-size: 0.83rem; margin-bottom: 3px; border-radius: 4px; }
        .menu-item:hover { color: #d4af37; background-color: #222; }
    </style>
    <script>
        function startCountdown(closeTimeString) {
            let el = document.getElementById('sticky-timer');
            if(!closeTimeString) { el.innerText = "⏰ ไม่ระบุเวลาปิดรับ"; return; }
            let countDownDate = new Date(closeTimeString).getTime();
            if(isNaN(countDownDate)) { countDownDate = new Date().getTime() + (2 * 60 * 60 * 1000); }
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
                    el.innerText = `⏳ เหลือเวลา: ${hours}ช. ${minutes}น. ${seconds}ว.`;
                }
            }, 1000);
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
<body onload="startCountdown('{{ close_time }}')">
    <div class="main-container" style="width: 100%;">
        <!-- Sidebar ซ้าย: เลือกรายชื่อลูกค้า/สายงาน + อัตราจ่าย + เมนูด่วน 5 รายการ -->
        <div class="sidebar-left">
            <div class="p-2 bg-dark border border-secondary mb-3 rounded">
                <div class="fw-bold text-warning small mb-1">ข้อมูลผู้ใช้งาน</div>
                <div class="small text-white">ล็อกอิน: <b>{{ username }}</b></div>
            </div>

            <form method="GET" action="/portal" id="customerForm">
                <input type="hidden" name="user" value="{{ username }}">
                <input type="hidden" name="market" value="{{ market }}">
                <input type="hidden" name="draw" value="{{ draw_date }}">
                <div class="mb-3">
                    <label class="form-label small fw-bold text-warning">เลือกลูกค้า / สายงาน:</label>
                    <select name="customer_id" class="form-select form-select-sm" onchange="document.getElementById('customerForm').submit()">
                        {% for cust in customers %}
                        <option value="{{ cust[0] }}" {% if cust[0]|string == customer_id|string %}selected{% endif %}>{{ cust[1] }}</option>
                        {% endfor %}
                    </select>
                </div>
            </form>

            <div class="mb-3">
                <div class="small fw-bold text-info mb-1">อัตราจ่าย: {{ market }}</div>
                <div class="extra-small text-warning mb-1" style="font-size:0.75rem;">({{ current_customer_name }})</div>
                
                <!-- [✅ ส่วนที่ได้รับการแก้ไข: เพิ่ม if has_rate ป้องกันบั๊ก 'else' ใน Jinja2] -->
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
            <a href="/admin-users?user={{ username }}" class="menu-item text-warning">1. 👥 จัดการผู้ใช้ (สร้างสายงาน)</a>
            <a href="/manage-customers?user={{ username }}" class="menu-item text-info">2. 👤 จัดการลูกค้า</a>
            <a href="/customer-rates-page?user={{ username }}" class="menu-item text-warning">3. ⚙️ ตั้งค่าเรตลูกค้าแยกตามหวย</a>
            <a href="/select-market?user={{ username }}" class="menu-item text-primary">4. 🏠 กลับหน้าหลัก (เลือกหวย)</a>
            <a href="/agent-reports?user={{ username }}" class="menu-item text-success">5. 📊 รายงานผล & สรุปยอด</a>
        </div>

        <!-- Content ตรงกลาง: คีย์โพย -->
        <div class="content-center">
            <div id="sticky-timer" class="sticky-timer">⏳ กำลังคำนวณเวลา...</div>

            <div class="market-banner">
                <div>🎟️ {{ market }} (งวด {{ draw_date }})</div>
                <div class="text-warning small">ผู้ซื้อ: {{ current_customer_name }}</div>
            </div>
            
             {% if error_msg %}
            <div class="alert alert-danger fw-bold text-center">❌ {{ error_msg }}</div>
            {% endif %}

            {% if not has_rate %}
            <div class="alert alert-danger shadow p-4 text-center bg-white border border-danger border-2">
                <h4 class="text-danger fw-bold mb-3"><i class="fa-solid fa-triangle-exclamation"></i> ยังไม่ได้ตั้งค่าเรตอัตราจ่ายของลูกค้ารายนี้</h4>
                <p class="text-dark mb-4">ลูกค้ารายนี้ยังไม่มีการกำหนดอัตราจ่ายและส่วนลดสำหรับหวย <b>{{ market }}</b></p>
                <a href="/customer-rates-page?user={{ username }}" class="btn btn-danger btn-lg fw-bold px-5">⚙️ ไปหน้ากำหนดเรตลูกค้าแยกตามหวย ➡️</a>
            </div>
            {% else %}

            <div class="quick-btn-group d-flex gap-2 mb-3">
                <button type="button" class="quick-btn" onclick="alert('ฟังก์ชันนี้กำลังอัปเดต')">6กลับ</button>
                <button type="button" class="quick-btn" onclick="alert('ฟังก์ชันนี้กำลังอัปเดต')">รูด19ประตู</button>
                <button type="button" class="quick-btn" onclick="alert('ฟังก์ชันนี้กำลังอัปเดต')">รูดหน้า</button>
                <button type="button" class="quick-btn" onclick="alert('ฟังก์ชันนี้กำลังอัปเดต')">รูดหลัง</button>
            </div>

            <div class="preview-box" id="previewContent">
                <span class="text-muted small">preview:- (เลือกฟังก์ชันคีย์ด่วน หรือพิมพ์เลขในฟอร์มด้านล่าง)</span>
            </div>

            <form method="POST" action="/portal-add-draft" class="p-3 bg-white rounded shadow-sm border mb-3">
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
                        <label class="form-label small fw-bold mb-1">บน / 3ตัวตรง / 2ตัวบน</label>
                        <input type="number" step="any" id="topAmtInput" name="top_amt" class="form-control" placeholder="จำนวนเงิน" oninput="refreshPreviewOnInput()">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label small fw-bold mb-1">ล่าง / 3ตัวโต๊ด / 2ตัวล่าง</label>
                        <input type="number" step="any" id="botAmtInput" name="bot_amt" class="form-control" placeholder="จำนวนเงิน" oninput="refreshPreviewOnInput()">
                    </div>
                </div>
                <div class="d-flex gap-2 mt-2">
                    <button type="reset" class="btn btn-danger btn-sm fw-bold px-4">ยกเลิก</button>
                    <button type="submit" class="btn btn-primary btn-sm fw-bold px-4">เพิ่มรายการ</button>
                </div>
            </form>

            <div class="card shadow-sm p-3 bg-white">
                <h5 class="fw-bold mb-2 text-center text-primary">📋 ตารางพรีวิวโพยร่าง (รอออกบิล)</h5>
                <div class="table-responsive">
                    <table class="table table-sm table-bordered text-center align-middle" style="font-size:0.85rem;">
                        <thead class="table-dark">
                            <tr><th>ลำดับ</th><th>ตัวเลข</th><th>ประเภท</th><th>เดิมพัน</th><th>อัตราจ่าย</th><th>ส่วนลด</th><th>ยอดสุทธิ</th></tr>
                        </thead>
                        <tbody>
                            {% for d in drafts %}
                            <tr>
                                <td>{{ loop.index }}</td>
                                <td><b>{{ d[1] }}</b></td>
                                <td>{{ d[4] }}</td>
                                <td>{{ d[2] }}</td>
                                <td>{{ d[5] }}</td>
                                <td>{{ d[6] }}%</td>
                                <td><b>{{ d[7] }}</b></td>
                            </tr>
                            {% else %}
                            <tr><td colspan="7" class="text-muted py-3">ยังไม่มีรายการโพยร่าง</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="d-flex gap-2 mt-3">
                <form method="POST" action="/portal-confirm-bill" class="flex-grow-1">
                    <input type="hidden" name="user" value="{{ username }}">
                    <input type="hidden" name="market" value="{{ market }}">
                    <input type="hidden" name="draw" value="{{ draw_date }}">
                    <input type="hidden" name="customer_id" value="{{ customer_id }}">
                    <button type="submit" class="btn btn-primary w-100 fw-bold" {% if not has_rate or not drafts %}disabled{% endif %}>ยืนยันโพย & ออกบิล</button>
                </form>
                <a href="/portal-clear-draft?user={{ username }}&market={{ market }}&draw={{ draw_date }}&customer_id={{ customer_id }}" class="btn btn-danger fw-bold px-4" onclick="return confirm('ยืนยันล้างรายการทั้งหมด?')">ล้างรายการ</a>
            </div>
            
            {% endif %}
        </div>
        
        <!-- Sidebar ขวา: เลขอั้นข้อมูลดิบ 3 กรอบ -->
        <div class="sidebar-right">
            <h6 class="text-center fw-bold text-danger mb-3">🚫 รายการเลขอั้นประจำงวด</h6>
            
            <label class="fw-bold text-dark mb-1 small">1. เลขอั้นปิดรับ:</label>
            <textarea class="form-control form-control-sm mb-2 bg-light text-danger fw-bold" rows="3" readonly>{{ block_closed }}</textarea>
            
            <label class="fw-bold text-dark mb-1 small">2. เลขอั้น 3 ตัวจ่ายครึ่ง:</label>
            <textarea class="form-control form-control-sm mb-2 bg-light text-dark" rows="3" readonly>{{ block_3d }}</textarea>
            
            <label class="fw-bold text-dark mb-1 small">3. เลขอั้น 2 ตัวจ่ายครึ่ง:</label>
            <textarea class="form-control form-control-sm bg-light text-dark" rows="3" readonly>{{ block_2d }}</textarea>
        </div>
    </div>
</body>
</html>
"""

@app.get("/portal", response_class=HTMLResponse)
def portal_page(user: str, market: str, draw: str, customer_id: str = None, error_msg: str = None):
    try:
        conn = connect_db()
        c = conn.cursor()
        
        c.execute("SELECT id, role FROM Users WHERE LOWER(username)=LOWER(%s)", (user,))
        role_res = c.fetchone()
        role = role_res[1].strip() if role_res else "Member"
        logged_in_uid = role_res[0] if role_res else 0

        customers = []
        if role.lower() == 'admin':
            c.execute("SELECT id, name FROM Customers ORDER BY id DESC")
            for row in c.fetchall(): customers.append((str(row[0]), row[1]))
            c.execute("SELECT id, username FROM Users ORDER BY id DESC")
            for row in c.fetchall(): customers.append((f"user_{row[0]}", f"user: {row[1]}"))
        else:
            customers.append((f"user_{logged_in_uid}", f"user: {user} (บัญชีตัวเอง)"))
            c.execute("SELECT id, name FROM Customers WHERE LOWER(owner_username)=LOWER(%s) ORDER BY id DESC", (user,))
            for row in c.fetchall(): customers.append((str(row[0]), row[1]))
            c.execute("SELECT id, username FROM Users WHERE LOWER(parent_username)=LOWER(%s) ORDER BY id DESC", (user,))
            for row in c.fetchall(): customers.append((f"user_{row[0]}", f"user: {row[1]}"))

        if not customer_id and customers: customer_id = customers[0][0]

        current_customer_name = ""
        for cust in customers:
            if str(cust[0]) == str(customer_id):
                current_customer_name = cust[1]
                break

        # ตรวจสอบเรต
        has_rate = False
        user_rates = {"pay_3d": 500.0, "pay_3tod": 100.0, "pay_2d": 70.0, "pay_run_top": 3.2, "pay_run_bot": 4.2, "disc_total": 0.0, "disc_3d": 0.0, "disc_2d": 0.0, "disc_run": 0.0}
        
        c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total FROM CustomerLottoRates WHERE target_id=%s AND lotto_name=%s", (str(customer_id), market))
        specific_rate = c.fetchone()
        
        if specific_rate:
            has_rate = True
            user_rates.update({
                "pay_3d": float(specific_rate[0] or 500), "pay_3tod": float(specific_rate[1] or 100), "pay_2d": float(specific_rate[2] or 70),
                "pay_run_top": float(specific_rate[3] or 3.2), "pay_run_bot": float(specific_rate[4] or 4.2),
                "disc_3d": float(specific_rate[5] or 0), "disc_2d": float(specific_rate[6] or 0), "disc_run": float(specific_rate[7] or 0), "disc_total": float(specific_rate[8] or 0)
            })
        else:
            if str(customer_id).startswith("user_"):
                u_id = str(customer_id).replace("user_", "")
                c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total FROM Users WHERE id=%s", (u_id,))
                ur = c.fetchone()
                if ur:
                    has_rate = True
                    user_rates.update({"pay_3d": float(ur[0] or 500), "pay_3tod": float(ur[1] or 100), "pay_2d": float(ur[2] or 70), "pay_run_top": float(ur[3] or 3.2), "pay_run_bot": float(ur[4] or 4.2), "disc_3d": float(ur[5] or 0), "disc_2d": float(ur[6] or 0), "disc_run": float(ur[7] or 0), "disc_total": float(ur[8] or 0)})
            else:
                c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total FROM Customers WHERE id=%s", (customer_id,))
                cr = c.fetchone()
                if cr:
                    has_rate = True
                    user_rates.update({"pay_3d": float(cr[0] or 500), "pay_3tod": float(cr[1] or 100), "pay_2d": float(cr[2] or 70), "pay_run_top": float(cr[3] or 3.2), "pay_run_bot": float(cr[4] or 4.2), "disc_3d": float(cr[5] or 0), "disc_2d": float(cr[6] or 0), "disc_run": float(cr[7] or 0), "disc_total": float(cr[8] or 0)})

        c.execute("SELECT close_time FROM LotteryCampaigns WHERE lotto_name=%s AND draw_date=%s", (market, draw))
        cr_res = c.fetchone()
        close_time = cr_res[0] if cr_res and cr_res[0] else ""

        c.execute("SELECT id, num, amt_teng, status, type, payout_rate, discount, net FROM TempDraft WHERE username=%s AND customer_id=%s", (user, str(customer_id)))
        drafts = c.fetchall()

        b_closed, b_3d, b_2d = get_blocked_display_data(draw)
        
        return Template(PORTAL_TEMPLATE).render(
            username=user, role=role, market=market, draw_date=draw,
            customers=customers, customer_id=customer_id, current_customer_name=current_customer_name,
            drafts=drafts, block_closed=b_closed, block_3d=b_3d, block_2d=b_2d,
            rates=user_rates, close_time=close_time, has_rate=has_rate, error_msg=error_msg
        )
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        if 'conn' in locals(): conn.close()

# ================= [✅ ปรับปรุง] API รับคีย์โพย (รองรับ บน/ล่าง และคำนวณเรตออโต้) =================
@app.post("/portal-add-draft")
def portal_add_draft(
    user: str = Form(...), market: str = Form(...), draw: str = Form(...), 
    num_input: str = Form(...), top_amt: float = Form(0), bot_amt: float = Form(0), 
    customer_id: str = Form(...)
):
    try:
        conn = connect_db()
        c = conn.cursor()
        
        num = num_input.strip()
        num_len = len(num)
        
        if num_len not in [1, 2, 3]:
            return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}&error_msg=ตัวเลขต้องเป็น 1, 2 หรือ 3 หลัก", status_code=303)

        # 1. ดึงเรตลูกค้า เพื่อมาคำนวณส่วนลด/ยอดสุทธิ
        c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total FROM CustomerLottoRates WHERE target_id=%s AND lotto_name=%s", (customer_id, market))
        rate = c.fetchone()
        if not rate: # ดึงเรต Default ถ้าไม่มีเรตเฉพาะหวย
            if customer_id.startswith("user_"):
                c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total FROM Users WHERE id=%s", (customer_id.replace("user_",""),))
            else:
                c.execute("SELECT pay_3d, pay_3tod, pay_2d, pay_run_top, pay_run_bot, disc_3d, disc_2d, disc_run, disc_total FROM Customers WHERE id=%s", (customer_id,))
            rate = c.fetchone()

        if not rate: rate = (500, 100, 70, 3.2, 4.2, 0, 0, 0, 0)
        
        # 2. ฟังก์ชันช่วยบันทึกลง DB
        def insert_draft(play_type, amt, payout, discount_percent):
            net = amt - (amt * (discount_percent / 100))
            c.execute("""
                INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) 
                VALUES (%s, %s, 'Customer', %s, %s, %s, %s, %s, %s, 'ปกติ')
            """, (user, customer_id, num, amt, play_type, payout, discount_percent, net))

        # 3. บันทึกยอด 'บน' (Top)
        if top_amt > 0:
            if num_len == 3: insert_draft("3ตัวตรง", top_amt, rate[0], rate[5] if rate[5] > 0 else rate[8])
            elif num_len == 2: insert_draft("2ตัวบน", top_amt, rate[2], rate[6] if rate[6] > 0 else rate[8])
            elif num_len == 1: insert_draft("วิ่งบน", top_amt, rate[3], rate[7] if rate[7] > 0 else rate[8])

        # 4. บันทึกยอด 'ล่าง' (Bot)
        if bot_amt > 0:
            if num_len == 3: insert_draft("3ตัวโต๊ด", bot_amt, rate[1], rate[5] if rate[5] > 0 else rate[8])
            elif num_len == 2: insert_draft("2ตัวล่าง", bot_amt, rate[2], rate[6] if rate[6] > 0 else rate[8])
            elif num_len == 1: insert_draft("วิ่งล่าง", bot_amt, rate[4], rate[7] if rate[7] > 0 else rate[8])

        conn.commit()
    except Exception as e:
        print("Insert Draft Error:", e)
    finally:
        if 'conn' in locals(): conn.close()
        
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}", status_code=303)

# ================= [✅ สร้างใหม่] API ล้างรายการ (Clear Draft) =================
@app.get("/portal-clear-draft")
def portal_clear_draft(user: str, market: str, draw: str, customer_id: str):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("DELETE FROM TempDraft WHERE username=%s AND customer_id=%s", (user, customer_id))
        conn.commit()
    except Exception as e:
        print("Clear Draft Error:", e)
    finally:
        if 'conn' in locals(): conn.close()
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}", status_code=303)

# ================= [✅ สร้างใหม่] API ยืนยันโพยออกบิล =================
@app.post("/portal-confirm-bill")
def portal_confirm_bill(user: str = Form(...), market: str = Form(...), draw: str = Form(...), customer_id: str = Form(...)):
    try:
        # ระบบจริงจะต้องย้ายข้อมูลจาก TempDraft ไปยังตารางบิลถาวร (เช่น Bills, Tickets)
        # ในที่นี้ ทำการลบออกจาก TempDraft ถือว่าบิลสำเร็จ
        conn = connect_db()
        c = conn.cursor()
        c.execute("DELETE FROM TempDraft WHERE username=%s AND customer_id=%s", (user, customer_id))
        conn.commit()
    except Exception as e:
        print("Confirm Bill Error:", e)
    finally:
        if 'conn' in locals(): conn.close()
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}&customer_id={customer_id}&error_msg=ออกบิลสำเร็จเรียบร้อย!", status_code=303)


# --- เมนูด่วนอื่นๆ (โค้ดเดิมของคุณที่ทำงานได้ปกติ) ---
# ...
# [หมายเหตุ: นำโค้ดหน้าจัดการผู้ใช้ (admin-users), จัดการลูกค้า, หน้าเรต และรายงานผลต่อท้ายได้เลย โค้ดส่วนนั้นไม่มีปัญหาและทำงานได้ดีครับ]
# ...

@app.get("/admin-campaigns", response_class=HTMLResponse)
def admin_campaigns(user: str):
    return RedirectResponse(url=f"/select-market?user={user}", status_code=303)

@app.get("/admin-blocked", response_class=HTMLResponse)
def admin_blocked(user: str):
    return RedirectResponse(url=f"/select-market?user={user}", status_code=303)

@app.get("/system-reset", response_class=HTMLResponse)
def system_reset(user: str):
    return RedirectResponse(url=f"/select-market?user={user}", status_code=303)

@app.get("/logout")
def logout():
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
