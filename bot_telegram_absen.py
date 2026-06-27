import os
import threading
import psycopg2
import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, Response, send_file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

REASON = 1
GEN_MULAI, GEN_BBM_AWAL, GEN_BBM_AKHIR = range(3)

def get_db():
    return psycopg2.connect(os.getenv("SUPABASE_URL"))

# ===== ROUTE UNTUK MENAMPILKAN LOGO / FAVICON =====
@app_flask.route('/logo.png')
def get_logo():
    if os.path.exists('logo.png'):
        return send_file('logo.png', mimetype='image/png')
    elif os.path.exists('1000430229.png'):
        return send_file('1000430229.png', mimetype='image/png')
    else:
        return "Logo tidak ditemukan. Pastikan file gambar ada di folder script.", 404
# ===== WEB GENSET (HALAMAN DEFAULT /) =====
@app_flask.route('/')
def home_genset():
    try:
        bulan = request.args.get('bulan', '')
        nama = request.args.get('nama', '')
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT DISTINCT petugas FROM genset_log ORDER BY petugas")
        list_petugas = [r[0] for r in cur.fetchall()]

        sql = "SELECT tanggal, jam_mulai, jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, petugas FROM genset_log WHERE 1=1"
        params = []
        if bulan:
            sql += " AND TO_CHAR(tanggal, 'YYYY-MM') = %s"
            params.append(bulan)
        if nama:
            sql += " AND petugas ILIKE %s"
            params.append(f"%{nama}%")
        sql += " ORDER BY tanggal ASC, jam_mulai ASC LIMIT 100"
        cur.execute(sql, params)
        data = cur.fetchall()
        conn.close()

        labels = []
        data_sisa = []
        data_pakai = []
        data_colors = [] # List untuk menyimpan warna batang
        info_detail = []
        data_durasi = []
        rows = ""
        
        for r in data:
            tanggal, mulai, selesai, awal, akhir, pakai, sisa, petugas = r

            # Hitung durasi
            if mulai and selesai:
                dt_mulai = datetime.combine(tanggal, mulai)
                dt_selesai = datetime.combine(tanggal, selesai)
                durasi_detik = (dt_selesai - dt_mulai).total_seconds()
                if durasi_detik < 0: durasi_detik += 86400
                h = int(durasi_detik // 3600)
                m = int((durasi_detik % 3600) // 60)
                durasi_str = f"{h}j {m}m"
            else:
                durasi_str = "-"

            labels.append(f"{tanggal}")
            sisa_val = sisa if sisa else 0
            data_sisa.append(sisa_val)
            data_pakai.append(pakai if pakai else 0)
            data_durasi.append(durasi_str)
            info_detail.append(f"Tgl:{tanggal} | {mulai.strftime('%H:%M') if mulai else '-'}-{selesai.strftime('%H:%M') if selesai else '-'} | Durasi:{durasi_str} | Awal:{awal}% | Akhir:{akhir}% | Pakai:{pakai}% | Petugas:{petugas}")

            # Logika Warna: Merah jika < 30, Biru jika >= 30
            warna = 'rgba(220, 53, 69, 0.8)' if sisa_val < 30 else 'rgba(54, 162, 235, 0.8)'
            data_colors.append(warna)

            row_class = "style='background:#ffebee;color:#c62828;font-weight:bold'" if sisa_val < 30 else ""
            rows += f"<tr {row_class}><td>{tanggal}</td><td>{mulai.strftime('%H:%M') if mulai else '-'}</td><td>{selesai.strftime('%H:%M') if selesai else '-'}</td><td>{durasi_str}</td><td>{awal}%</td><td>{akhir}%</td><td>{pakai}%</td><td>{sisa_val}%</td><td>{petugas}</td></tr>"

        # Logika Alert: Hanya muncul jika DATA TERBARU < 30%
        alert_html = ""
        if data_sisa and data_sisa[-1] < 30:
            alert_html = '<div class="alert-low">⚠️ PERHATIAN: Sisa BBM saat ini rendah (< 30%). Segera isi BBM!</div>'

        option_petugas = '<option value="">Semua Petugas</option>'
        for p in list_petugas:
            selected = 'selected' if p == nama else ''
            option_petugas += f'<option value="{p}" {selected}>{p}</option>'

        navbar = """<nav style="background:#FF9800;padding:15px;text-align:center;position:relative;z-index:10">
        <a href="/" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">⛽ Genset BBM</a>
        <a href="/maintenance" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">🔧 Maintenance</a></nav>"""
        html = navbar + f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Log Genset</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" type="image/png" href="/logo.png">
        <!-- Tambahan Font Poppins untuk UI yang lebih modern -->
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.0.0"></script>
        <style>
        body{{font-family:'Poppins', sans-serif;margin:0;padding:0;background:#f8f9fa;position:relative;min-height:100vh}}
        body::before {{content:"";position:fixed;top:0;left:0;right:0;bottom:0;background:url('/logo.png') no-repeat center center;background-size:350px;opacity:0.04;z-index:-1;pointer-events:none;}}
        .container{{max-width:1100px;margin:0 auto;padding:20px;box-sizing:border-box}}
        h2{{text-align:center;margin-top:10px;color:#2c3e50;font-weight:700}}
        table{{width:100%;border-collapse:collapse;background:white;margin-top:20px;position:relative;z-index:1;box-shadow:0 4px 15px rgba(0,0,0,0.03);border-radius:10px;overflow:hidden}}
        th,td{{padding:14px;border-bottom:1px solid #eee;text-align:center;font-size:14px}}
        th{{background:#FF9800;color:white;font-weight:600}}
        tr:hover{{background:#fffaf3}}
        .filter{{text-align:center;margin:20px auto;padding:20px;background:white;border-radius:12px;box-shadow:0 4px 15px rgba(0,0,0,0.03);position:relative;z-index:1;max-width:650px;}}
        .filter form {{display:flex; justify-content:center; align-items:center; gap:10px; flex-wrap:wrap;}}
        input,select,button{{padding:10px 14px;font-size:14px;font-family:'Poppins', sans-serif;border-radius:8px;border:1px solid #ddd;outline:none}}
        input:focus, select:focus{{border-color:#FF9800}}
        button, .export-btn{{transition: all 0.3s ease;}}
        button:hover, .export-btn:hover{{transform: translateY(-2px);box-shadow:0 4px 10px rgba(0,0,0,0.15)}}
        /* Mempercantik Kontainer Chart */
        .chart-container{{background:white;padding:25px;border-radius:16px;box-shadow:0 8px 30px rgba(0,0,0,0.06);margin:20px auto;position:relative;z-index:1;height:480px;}}
        .alert-low{{background:#fff0f0;color:#d32f2f;padding:12px;border-radius:8px;text-align:center;font-weight:600;margin:15px 0;border-left:4px solid #d32f2f;box-shadow:0 2px 8px rgba(211,47,47,0.1)}}
        </style></head><body>
        
        <div class="container">
            <h2>⛽ Log Penggunaan Genset & BBM</h2>

            <div class="chart-container"><canvas id="grafikBBM"></canvas></div>
            {alert_html}

            <div class="filter">
                <form method="get">
                    <label style="color:#555;font-weight:600">Filter Bulan:</label>
                    <input type="month" name="bulan" value="{bulan if bulan else ''}">
                    <select name="nama">{option_petugas}</select>
                    <button type="submit" style="background:#FF9800;color:white;font-weight:600;border:none;cursor:pointer;">🔍 Filter</button>
                    <a href="/"><button type="button" style="background:#757575;color:white;border:none;cursor:pointer;">🔄 Reset</button></a>
                    <a href="/export_genset?bulan={bulan if bulan else ''}" class="export-btn" style="padding:10px 14px;background:#10b981;color:white;text-decoration:none;border-radius:8px;font-weight:600;display:inline-block;border:none;">⬇️ Export CSV</a>
                </form>
            </div>

            <div style="overflow-x:auto;">
                <table><tr><th>Tanggal</th><th>Mulai</th><th>Selesai</th><th>Durasi</th><th>BBM Awal</th><th>BBM Akhir</th><th>Pakai</th><th>Sisa</th><th>Petugas</th></tr>{rows}</table>
            </div>
            
        </div>

        <script>
        Chart.register(ChartDataLabels);
        Chart.defaults.font.family = "'Poppins', sans-serif";
        Chart.defaults.color = '#718096';

        const canvas = document.getElementById('grafikBBM');
        const ctx = canvas.getContext('2d');
        const infoDetail = {info_detail};
        const durasiArr = {data_durasi};

        // Custom Gradients
        let gradientPakai = ctx.createLinearGradient(0, 0, 0, 400);
        gradientPakai.addColorStop(0, 'rgba(255, 152, 0, 1)');
        gradientPakai.addColorStop(1, 'rgba(255, 193, 7, 0.4)');

        const rawColors = {data_colors};
        const bgColorsSisa = rawColors.map(color => {{
            let grad = ctx.createLinearGradient(0, 0, 0, 400);
            if(color.includes('220, 53, 69')) {{ // Jika warna merah (Sisa Rendah)
                grad.addColorStop(0, 'rgba(244, 63, 94, 1)');
                grad.addColorStop(1, 'rgba(225, 29, 72, 0.4)');
            }} else {{ // Jika warna biru (Sisa Aman)
                grad.addColorStop(0, 'rgba(56, 189, 248, 1)');
                grad.addColorStop(1, 'rgba(2, 132, 199, 0.4)');
            }}
            return grad;
        }});

        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: {labels},
                datasets: [{{
                    label: 'Sisa BBM %',
                    data: {data_sisa},
                    backgroundColor: bgColorsSisa,
                    borderRadius: 8,          // Batang melengkung
                    borderSkipped: false,
                    barPercentage: 0.6,
                    categoryPercentage: 0.8,
                    datalabels: {{
                        display: true,
                        color: 'white',
                        anchor: 'center',
                        align: 'center',
                        font: {{ weight: '700', size: 12 }},
                        formatter: function(value, context) {{
                            let durasi = durasiArr[context.dataIndex];
                            if (durasi !== "-" && durasi !== "0j 0m" && value > 15) {{
                                return ['Sisa: ' + value + '%', '⏳ ' + durasi];
                            }}
                            return 'Sisa: ' + value + '%';
                        }}
                    }}
                }}, {{
                    label: 'Pemakaian BBM %',
                    data: {data_pakai},
                    backgroundColor: gradientPakai,
                    borderRadius: 8,          // Batang melengkung
                    borderSkipped: false,
                    barPercentage: 0.6,
                    categoryPercentage: 0.8,
                    datalabels: {{
                        display: true,
                        color: '#d97706',
                        anchor: 'end',
                        align: 'top',
                        font: {{ weight: '700', size: 11 }},
                        formatter: function(value, context) {{
                            return value > 0 ? '-' + value + '%' : '';
                        }}
                    }}
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                layout: {{ padding: {{ top: 20 }} }},
                animation: {{
                    y: {{ duration: 1500, easing: 'easeOutQuart' }} // Animasi modern
                }},
                plugins: {{
                    title: {{
                        display: true, 
                        text: '📊 Grafik Batang Penggunaan & Sisa BBM', 
                        font: {{ size: 18, weight: '700' }},
                        color: '#1e293b',
                        padding: {{ bottom: 25 }}
                    }},
                    legend: {{
                        position: 'top',
                        labels: {{
                            usePointStyle: true, // Ubah icon legend kotak jadi lingkaran
                            boxWidth: 10,
                            padding: 20,
                            font: {{ size: 13, weight: '600' }}
                        }}
                    }},
                    tooltip: {{
                        backgroundColor: 'rgba(15, 23, 42, 0.95)', // Warna Tooltip lebih gelap/elegan
                        titleFont: {{ size: 14, weight: '600' }},
                        bodyFont: {{ size: 13 }},
                        padding: 15,
                        cornerRadius: 10,
                        displayColors: true,
                        callbacks: {{
                            // Format tooltip agar tulisan tidak memanjang tapi ke bawah
                            afterLabel: function(context) {{
                                return infoDetail[context.dataIndex].split(' | ');
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true, 
                        max: 110, 
                        title: {{ display: true, text: 'Persentase BBM (%)', font: {{ weight: '600' }} }},
                        grid: {{
                            color: 'rgba(200, 200, 200, 0.3)',
                            borderDash: [5, 5] // Garis putus-putus
                        }},
                        border: {{ display: false }}
                    }},
                    x: {{
                        title: {{ display: false }},
                        grid: {{ display: false }}, // Sumbu X bersih tanpa garis grid vertikal
                        border: {{ display: false }}
                    }}
                }}
            }}
        }});
        </script></body></html>""" 
        return html
    except Exception as e:
        return f"<h2>Error Koneksi DB</h2><pre>{e}</pre>", 500

# ===== WEB TAB: CEK MAINTENANCE RUTIN GENSET =====
@app_flask.route('/maintenance', methods=['GET', 'POST'])
def maintenance_routine():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        if request.method == 'POST':
            tanggal = request.form.get('tanggal') or datetime.now(WIB).strftime('%Y-%m-%d')
            jam_penggunaan = request.form.get('jam_penggunaan', '')
            voltase_1p_v1 = request.form.get('voltase_1p_v1', '')
            voltase_1p_v2 = request.form.get('voltase_1p_v2', '')
            voltase_1p_v3 = request.form.get('voltase_1p_v3', '')
            voltase_3p_v1v2 = request.form.get('voltase_3p_v1v2', '')
            voltase_3p_v2v3 = request.form.get('voltase_3p_v2v3', '')
            voltase_3p_v3v1 = request.form.get('voltase_3p_v3v1', '')
            voltase_accu_mati = request.form.get('voltase_accu_mati', '')
            voltase_accu_hidup = request.form.get('voltase_accu_hidup', '')
            bbm_persen = request.form.get('bbm_persen', '')
            air_radiator = request.form.get('air_radiator', '')
            oli_mesin = request.form.get('oli_mesin', '')
            petugas = request.form.get('petugas', '')
            
            cur.execute("""
                INSERT INTO genset_maintenance 
                (tanggal, jam_penggunaan, voltase_1p_v1, voltase_1p_v2, voltase_1p_v3, voltase_3p_v1v2, voltase_3p_v2v3, voltase_3p_v3v1, voltase_accu_mati, voltase_accu_hidup, bbm_persen, air_radiator, oli_mesin, petugas)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (tanggal, jam_penggunaan, voltase_1p_v1, voltase_1p_v2, voltase_1p_v3, voltase_3p_v1v2, voltase_3p_v2v3, voltase_3p_v3v1, voltase_accu_mati, voltase_accu_hidup, bbm_persen, air_radiator, oli_mesin, petugas))
            conn.commit()
        
        # Ambil filter bulan dari parameter GET (format: YYYY-MM)
        bulan = request.args.get('bulan', '')
        
        sql = """
            SELECT tanggal, jam_penggunaan, voltase_1p_v1, voltase_1p_v2, voltase_1p_v3, 
                   voltase_3p_v1v2, voltase_3p_v2v3, voltase_3p_v3v1, voltase_accu_mati, voltase_accu_hidup, 
                   bbm_persen, air_radiator, oli_mesin, petugas 
            FROM genset_maintenance WHERE 1=1
        """
        params = []
        if bulan:
            sql += " AND TO_CHAR(tanggal, 'YYYY-MM') = %s"
            params.append(bulan)
            
        sql += " ORDER BY tanggal DESC, id DESC LIMIT 100"
        
        cur.execute(sql, params)
        data = cur.fetchall()
        conn.close()
        
        navbar = """<nav style="background:#009688;padding:15px;text-align:center;position:relative;z-index:10">
        <a href="/" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">⛽ Genset BBM</a>
        <a href="/maintenance" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">🔧 Maintenance</a></nav>"""
        
        rows = ""
        for r in data:
            tgl, jp, v1, v2, v3, v1v2, v2v3, v3v1, vaccu_mati, vaccu_hidup, bbm, rad, oli, ptg = r
            rows += f"<tr><td>{tgl}</td><td>{jp}</td><td>{v1}</td><td>{v2}</td><td>{v3}</td><td>{v1v2}</td><td>{v2v3}</td><td>{v3v1}</td><td>{vaccu_mati or '-'}</td><td>{vaccu_hidup or '-'}</td><td>{bbm}%</td><td>{rad}</td><td>{oli}</td><td>{ptg}</td></tr>"
            
        hari_ini = datetime.now(WIB).strftime('%Y-%m-%d')
        
        html = navbar + f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Maintenance Rutin Genset</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" type="image/png" href="/logo.png">
        <style>
        body{{font-family:Arial;margin:0;padding:0;background:#f5f5f5;position:relative;min-height:100vh}}h2,h3{{text-align:center}}h4{{margin:10px 0 5px 0;color:#009688;border-bottom:1px solid #ddd;padding-bottom:5px}}
        body::before {{content:"";position:fixed;top:0;left:0;right:0;bottom:0;background:url('/logo.png') no-repeat center center;background-size:350px;opacity:0.06;z-index:-1;pointer-events:none;}}
        .container{{max-width:1100px;margin:0 auto;padding:20px;box-sizing:border-box}}
        table{{width:100%;border-collapse:collapse;background:white;margin-top:20px;position:relative;z-index:1;box-shadow:0 2px 5px rgba(0,0,0,0.05);border-radius:8px;overflow:hidden}}th,td{{padding:12px;border-bottom:1px solid #ddd;text-align:center;font-size:14px}}
        th{{background:#009688;color:white}}tr:hover{{background:#e0f2f1}}
        .form-container{{background:white;padding:20px;border-radius:10px;max-width:550px;margin:0 auto 20px auto;box-shadow:0 2px 5px rgba(0,0,0,0.1);position:relative;z-index:1}}
        .form-group{{margin-bottom:15px}}label{{display:block;margin-bottom:5px;font-weight:bold;font-size:14px}}
        .grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:15px}}
        .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:15px}}
        input,select,button{{width:100%;padding:10px;font-size:16px;border-radius:5px;border:1px solid #ddd;box-sizing:border-box}}
        button{{background:#009688;color:white;border:none;cursor:pointer;font-weight:bold;margin-top:10px}}
        button:hover{{background:#00796b}}
        .filter-container{{background:white;padding:15px;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.05);margin:20px auto 10px auto;position:relative;z-index:1;text-align:center}}
        .filter-form{{display:flex;justify-content:center;align-items:center;gap:10px;flex-wrap:wrap}}
        .filter-form input, .filter-form button, .filter-form a{{width:auto;margin:0;padding:8px 15px;font-size:15px}}
        .export-btn{{display:inline-block;padding:8px 15px;background:#009688;color:white;text-decoration:none;border-radius:5px;font-weight:bold;width:auto;box-sizing:border-box;font-size:15px}}
        .export-btn:hover{{background:#00796b}}
        @media (max-width:768px){{table,thead,tbody,th,td,tr{{display:block}}th{{display:none}}
        td{{border:none;position:relative;padding-left:50%;text-align:left}}td:before{{content:attr(data-label);position:absolute;left:10px;font-weight:bold}}}}
        </style></head><body>
        
        <div class="container">
            <h2>🔧 Cek Maintenance Rutin Genset</h2>

            <div class="form-container">
                <h3>📝 Input Log Maintenance</h3>
                <form method="post">
                    <div class="form-group"><label>Tanggal</label><input type="date" name="tanggal" value="{hari_ini}" required></div>
                    <div class="form-group"><label>Jam Penggunaan (Hour Meter)</label><input type="text" name="jam_penggunaan" placeholder="Contoh: 1250 Jam" required></div>
                    
                    <h4>Voltase 1 Phase (L - N)</h4>
                    <div class="grid-3">
                        <div><label>V1 (R-N)</label><input type="text" name="voltase_1p_v1" placeholder="220V" required></div>
                        <div><label>V2 (S-N)</label><input type="text" name="voltase_1p_v2" placeholder="220V" required></div>
                        <div><label>V3 (T-N)</label><input type="text" name="voltase_1p_v3" placeholder="220V" required></div>
                    </div>

                    <h4>Voltase 3 Phase (L - L)</h4>
                    <div class="grid-3">
                        <div><label>V1 - V2</label><input type="text" name="voltase_3p_v1v2" placeholder="380V" required></div>
                        <div><label>V2 - V3</label><input type="text" name="voltase_3p_v2v3" placeholder="380V" required></div>
                        <div><label>V3 - V1</label><input type="text" name="voltase_3p_v3v1" placeholder="380V" required></div>
                    </div>

                    <h4>Kondisi Voltase Accu</h4>
                    <div class="grid-2">
                        <div><label>Accu (Mesin Mati)</label><input type="text" name="voltase_accu_mati" placeholder="Contoh: 12.4V" required></div>
                        <div><label>Accu (Mesin Menyala)</label><input type="text" name="voltase_accu_hidup" placeholder="Contoh: 14.2V" required></div>
                    </div>

                    <div class="form-group"><label>% BBM</label><input type="number" name="bbm_persen" placeholder="Contoh: 85" min="0" max="100" required></div>
                    <div class="form-group"><label>Air Radiator</label>
                        <select name="air_radiator">
                            <option value="Bagus/Penuh">Bagus / Penuh</option>
                            <option value="Kurang/Isi">Kurang / Perlu Tambah</option>
                        </select>
                    </div>
                    <div class="form-group"><label>Oli Mesin</label>
                        <select name="oli_mesin">
                            <option value="Bagus/Cukup">Bagus / Cukup</option>
                            <option value="Kurang/Tambah">Kurang / Perlu Tambah</option>
                            <option value="Kotor/Wajib Ganti">Kotor / Wajib Ganti</option>
                        </select>
                    </div>
                    <div class="form-group"><label>Nama Petugas</label><input type="text" name="petugas" placeholder="Nama Anda" required></div>
                    <button type="submit">Simpan Log Maintenance</button>
                </form>
            </div>
            
            <div class="filter-container">
                <form method="get" class="filter-form">
                    <label><b>Filter Bulan:</b></label>
                    <input type="month" name="bulan" value="{bulan}">
                    <button type="submit" style="background:#009688;color:white;">Filter</button>
                    <a href="/maintenance"><button type="button" style="background:#757575;color:white;">Reset (All)</button></a>
                    <a href="/export_maintenance?bulan={bulan}" class="export-btn">⬇️ Export CSV</a>
                </form>
            </div>
            
            <div style="overflow-x:auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Tanggal</th><th>Jam Kerja</th><th>1P-V1</th><th>1P-V2</th><th>1P-V3</th><th>3P-V1V2</th><th>3P-V2V3</th><th>3P-V3V1</th><th>Accu Mati</th><th>Accu Hidup</th><th>% BBM</th><th>Radiator</th><th>Oli</th><th>Petugas</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>
        </div>

        <script>
            const headers = ["Tanggal", "Jam Kerja", "1P-V1", "1P-V2", "1P-V3", "3P-V1V2", "3P-V2V3", "3P-V3V1", "Accu Mati", "Accu Hidup", "% BBM", "Radiator", "Oli", "Petugas"];
            document.querySelectorAll("tbody tr").forEach(tr => {{
                tr.querySelectorAll("td").forEach((td, i) => {{
                    td.setAttribute("data-label", headers[i]);
                }});
            }});
        </script>
        </body></html>"""
        return html
    except Exception as e:
        return f"<h2>Error Koneksi DB</h2><pre>{e}</pre>", 500

# ===== EXPORT DATA GENSET =====
@app_flask.route('/export_genset')
def export_genset():
    try:
        bulan = request.args.get('bulan', '')
        conn = get_db()
        cur = conn.cursor()
        
        sql = "SELECT tanggal, jam_mulai, jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, petugas FROM genset_log WHERE 1=1"
        params = []
        if bulan:
            sql += " AND TO_CHAR(tanggal, 'YYYY-MM') = %s"
            params.append(bulan)
            
        sql += " ORDER BY tanggal DESC, jam_mulai DESC"
        
        cur.execute(sql, params)
        data = cur.fetchall()
        conn.close()
        
        if not data: return "Belum ada data genset", 404
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Tanggal', 'Jam Mulai', 'Jam Selesai', 'Durasi', 'BBM Awal %', 'BBM Akhir %', 'Pemakaian %', 'Sisa %', 'Petugas'])
        
        for row in data:
            tanggal, mulai, selesai, awal, akhir, pakai, sisa, petugas = row
            if mulai and selesai:
                dt_mulai = datetime.combine(tanggal, mulai)
                dt_selesai = datetime.combine(tanggal, selesai)
                durasi_detik = (dt_selesai - dt_mulai).total_seconds()
                if durasi_detik < 0: durasi_detik += 86400
                h = int(durasi_detik // 3600)
                m = int((durasi_detik % 3600) // 60)
                durasi_str = f"{h}j {m}m"
            else: durasi_str = "-"
            
            writer.writerow([tanggal, mulai.strftime('%H:%M') if mulai else '-', selesai.strftime('%H:%M') if selesai else '-', durasi_str, awal, akhir, pakai, sisa, petugas])
            
        output.seek(0)
        filename = f"genset_log_{bulan if bulan else 'all'}.csv"
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={filename}"})
    except Exception as e:
        return f"Error: {e}", 500

# ===== EXPORT DATA MAINTENANCE =====
@app_flask.route('/export_maintenance')
def export_maintenance():
    try:
        bulan = request.args.get('bulan', '')
        conn = get_db()
        cur = conn.cursor()
        
        sql = """
            SELECT tanggal, jam_penggunaan, voltase_1p_v1, voltase_1p_v2, voltase_1p_v3, 
                   voltase_3p_v1v2, voltase_3p_v2v3, voltase_3p_v3v1, voltase_accu_mati, voltase_accu_hidup, 
                   bbm_persen, air_radiator, oli_mesin, petugas 
            FROM genset_maintenance WHERE 1=1
        """
        params = []
        if bulan:
            sql += " AND TO_CHAR(tanggal, 'YYYY-MM') = %s"
            params.append(bulan)
            
        sql += " ORDER BY tanggal DESC, id DESC"
        
        cur.execute(sql, params)
        data = cur.fetchall()
        conn.close()
        if not data: return "Belum ada data maintenance", 404
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Tanggal', 'Jam Kerja (Hour Meter)', '1P-V1', '1P-V2', '1P-V3', '3P-V1V2', '3P-V2V3', '3P-V3V1', 'Accu Mati', 'Accu Hidup', 'BBM %', 'Radiator', 'Oli', 'Petugas'])
        for row in data:
            writer.writerow(row)
        output.seek(0)
        
        filename = f"genset_maintenance_{bulan if bulan else 'all'}.csv"
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={filename}"})
    except Exception as e:
        return f"Error: {e}", 500

# ===== BOT TELEGRAM FUNCTIONS =====
def is_libur(tanggal):
    if tanggal.weekday() == 6: return True, "Minggu"
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM libur_nasional WHERE tanggal=%s", (tanggal,))
    result = cur.fetchone()
    conn.close()
    return (True, "Libur Nasional") if result else (False, None)

def get_keyboard(status):
    buttons = []
    if status == 'belum':
        buttons.append([InlineKeyboardButton("✅ Datang", callback_data='datang'), InlineKeyboardButton("🚪 Pulang", callback_data='pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin')])
    elif status in ['datang', 'lembur']:
        buttons.append([InlineKeyboardButton("🚪 Pulang", callback_data='pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin'), InlineKeyboardButton("🤒 Sakit", callback_data='sakit')])
    buttons.append([InlineKeyboardButton("📊 Rekap", callback_data='rekap'), InlineKeyboardButton("📋 Saya", callback_data='saya'), InlineKeyboardButton("⛽ Genset", callback_data='genset')])
    buttons.append([InlineKeyboardButton("⬇️ Download", callback_data='download'), InlineKeyboardButton("👑 Admin", callback_data='admin'), InlineKeyboardButton("❌", callback_data='noop')])
    return InlineKeyboardMarkup(buttons)

def cek_absen(user_id):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("SELECT jam_datang, jam_pulang, status FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
    data = cur.fetchone()
    conn.close()
    if not data: return 'belum'
    if data[2] in ['izin', 'sakit', 'cuti', 'lembur']: return data[2]
    return 'datang' if data[0] and not data[1] else 'selesai' if data[0] and data[1] else 'belum'

def simpan_datang(user_id, nama):
    conn = get_db()
    cur = conn.cursor()
    wib = datetime.now(WIB)
    hari_ini = wib.date()
    jam_sekarang = wib.time()
    telat = jam_sekarang > datetime.strptime('09:00:00', '%H:%M:%S').time()
    libur, jenis_libur = is_libur(hari_ini)
    status = 'lembur' if libur else 'hadir'
    try:
        cur.execute("INSERT INTO absensi (user_id, nama, tanggal, jam_datang, status, telat, alasan) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id, tanggal) DO NOTHING", (user_id, nama, hari_ini, jam_sekarang, status, telat, jenis_libur))
        conn.commit()
        return True, telat, libur, jenis_libur
    except: return False, False, False, None
    finally: conn.close()

def simpan_pulang(user_id):
    conn = get_db()
    cur = conn.cursor()
    wib = datetime.now(WIB)
    hari_ini = wib.date()
    jam_sekarang = wib.time()
    cur.execute("UPDATE absensi SET jam_pulang=%s WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL", (jam_sekarang, user_id, hari_ini))
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated

def simpan_izin(user_id, nama, status, alasan):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("INSERT INTO absensi (user_id, nama, tanggal, status, alasan) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id, tanggal) DO UPDATE SET status=%s, alasan=%s", (user_id, nama, hari_ini, status, alasan, status, alasan))
    conn.commit()
    conn.close()

def get_rekap_bulanan(user_id, bulan_str=None):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(WIB)
    tahun, bulan = map(int, bulan_str.split('-')) if bulan_str else (now.year, now.month)
    cur.execute("SELECT COUNT(*), COALESCE(EXTRACT(EPOCH FROM SUM(jam_pulang - jam_datang)), 0), SUM(CASE WHEN telat THEN 1 ELSE 0 END) FROM absensi WHERE user_id=%s AND EXTRACT(MONTH FROM tanggal)=%s AND EXTRACT(YEAR FROM tanggal)=%s AND jam_pulang IS NOT NULL AND status IN ('hadir','lembur')", (user_id, bulan, tahun))
    data = cur.fetchone()
    conn.close()
    hari_hadir, total_detik, total_telat = data[0] or 0, int(data[1] or 0), data[2] or 0
    h, m = divmod(total_detik, 3600)
    total_jam_fmt = f"{h:02d}j {m//60:02d}m"
    rata_fmt = f"{(total_detik//hari_hadir//3600):02d}j {((total_detik//hari_hadir)%3600//60):02d}m" if hari_hadir > 0 else "00j 00m"
    return hari_hadir, total_jam_fmt, total_telat, rata_fmt

async def genset_mulai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jam = update.message.text.strip()
    try:
        datetime.strptime(jam, '%H:%M')
        context.user_data['jam_mulai'] = jam
        await update.message.reply_text("2/3 BBM awal %? Contoh: 90")
        return GEN_BBM_AWAL
    except:
        await update.message.reply_text("Format jam salah. Contoh: 08:30")
        return GEN_MULAI

async def genset_bbm_awal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bbm = int(update.message.text.strip())
        if not 0 <= bbm <= 100: raise ValueError
        context.user_data['bbm_awal'] = bbm
        await update.message.reply_text("3/3 BBM akhir %? Contoh: 60\nKetik /cancel buat batal")
        return GEN_BBM_AKHIR
    except:
        await update.message.reply_text("Isi angka 0-100 aja bang")
        return GEN_BBM_AWAL

async def genset_bbm_akhir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bbm_akhir = int(update.message.text.strip())
        bbm_awal = context.user_data['bbm_awal']
        if bbm_akhir > bbm_awal:
            await update.message.reply_text("BBM akhir gaboleh lebih gede dari awal 😅")
            return GEN_BBM_AKHIR
        pemakaian = bbm_awal - bbm_akhir
        sisa = bbm_akhir
        jam_selesai = datetime.now(WIB).strftime('%H:%M')
        tanggal = datetime.now(WIB).date()
        user_id = update.effective_user.id
        nama = update.effective_user.first_name
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO genset_log (tanggal, jam_mulai, jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, petugas, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (tanggal, context.user_data['jam_mulai'], jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, nama, user_id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ *Genset Dicatat*\n📅 {tanggal}\n⏰ {context.user_data['jam_mulai']} - {jam_selesai}\n⛽ {bbm_awal}% → {bbm_akhir}%\n🔥 Pakai: {pemakaian}%\n💧 Sisa: {sisa}%\n👤 {nama}\n\nKetik /start buat balik ke menu", parse_mode='Markdown')
        context.user_data.clear()
        return ConversationHandler.END
    except:
        await update.message.reply_text("Isi angka 0-100")
        return GEN_BBM_AKHIR

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Dibatalkan. Ketik /start buat buka menu", reply_markup=get_keyboard(cek_absen(update.effective_user.id)))
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status = cek_absen(user_id)
    hari_ini = datetime.now(WIB).strftime('%d/%m/%Y')
    keyboard = get_keyboard(status)
    teks = f"🤖 *Absen & Genset*\n📅 {hari_ini}\n\n"
    teks += "Waktunya absen datang" if status == 'belum' else "✅ Sudah absen datang\nSilakan absen pulang" if status in ['datang', 'lembur'] else f"📝 Status hari ini: {status}" if status in ['izin', 'sakit', 'cuti'] else "Absensi hari ini sudah selesai"
    await update.message.reply_text(teks, reply_markup=keyboard, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nama = query.from_user.first_name
    button_id = query.data
    status = cek_absen(user_id)
    wib = datetime.now(WIB)
    jam = wib.strftime('%H:%M:%S')

    if button_id == 'datang':
        if status!= 'belum': await query.answer("Sudah absen datang", show_alert=True); return
        success, telat, libur, jenis_libur = simpan_datang(user_id, nama)
        if success:
            teks = f"✅ Absen datang berhasil!\nWaktu: {jam}"
            if libur: teks += f"\n💜 *LEMBUR* - {jenis_libur}"
            if telat: teks += "\n⚠️ *Kamu telat!*"
            teks += "\n\nSilakan absen pulang"
            await query.edit_message_text(text=teks, reply_markup=get_keyboard('datang'), parse_mode='Markdown')
    elif button_id == 'pulang':
        if status not in ['datang', 'lembur']: await query.answer("Belum absen datang", show_alert=True); return
        if simpan_pulang(user_id):
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT jam_datang, jam_pulang, status, EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, wib.date()))
            data = cur.fetchone()
            conn.close()
            jam_datang_str, jam_pulang_str, status_akhir = data[0].strftime('%H:%M:%S'), data[1].strftime('%H:%M:%S'), data[2]
            total_detik = int(data[3]) if data[3] else 0
            h, m = divmod(total_detik, 3600)
            total_jam = f"{h:02d}j {m//60:02d}m"
            teks = f"🤖 *Absen Selesai*\n📅 {wib.strftime('%d/%m/%Y')}\n━━━━━━━━━━━━━━\n✅ Datang: {jam_datang_str}\n🚪 Pulang: {jam_pulang_str}\n⏱️ Total: {total_jam}\n"
            if status_akhir == 'lembur': teks += f"💜 Status: LEMBUR\n"
            teks += f"Selesai. Ketik /start buat buka menu"
            await query.edit_message_text(text=teks, parse_mode='Markdown', reply_markup=get_keyboard('selesai'))
    elif button_id == 'genset':
        await query.answer()
        await query.edit_message_text("⛽ *Catat Penggunaan Genset*\n\n1/3 Jam mulai? Ketik 08:30\nKetik /cancel buat batal", parse_mode='Markdown')
        context.user_data.clear()
        return GEN_MULAI
    elif button_id in ['izin', 'sakit', 'cuti']:
        context.user_data['status_izin'] = button_id
        await query.edit_message_text(f"Kirim alasan {button_id}:", reply_markup=get_keyboard(status))
        return REASON
    elif button_id == 'rekap':
        hari_hadir, total_jam, total_telat, rata_rata = get_rekap_bulanan(user_id)
        bulan_nama = datetime.now(WIB).strftime('%B %Y')
        teks = f"📊 *Rekap {bulan_nama}*\n\n📅 Hari Hadir: {hari_hadir} hari\n⏱️ Total Jam: {total_jam}\n⚠️ Telat: {total_telat} kali\nRata-rata: {rata_rata}/hari"
        await query.edit_message_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(status))
    elif button_id == 'noop':
        await query.edit_message_text("Menu ditutup. Ketik /start", reply_markup=None)

async def terima_alasan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    status = context.user_data.get('status_izin')
    if status:
        user_id = update.effective_user.id
        nama = update.effective_user.first_name
        simpan_izin(user_id, nama, status, teks)
        context.user_data.pop('status_izin', None)
        await update.message.reply_text(f"✅ Status {status} tersimpan", reply_markup=get_keyboard(cek_absen(user_id)))
        return ConversationHandler.END
    return ConversationHandler.END

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.getenv("TOKEN")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    if not TOKEN or not SUPABASE_URL:
        print("Error: TOKEN/SUPABASE_URL kosong")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS absensi (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, nama TEXT, tanggal DATE NOT NULL, jam_datang TIME, jam_pulang TIME, status TEXT DEFAULT 'hadir', alasan TEXT, telat BOOLEAN DEFAULT false, UNIQUE(user_id, tanggal))")
    cur.execute("CREATE TABLE IF NOT EXISTS libur_nasional (tanggal DATE PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS genset_log (id SERIAL PRIMARY KEY, tanggal DATE NOT NULL, jam_mulai TIME NOT NULL, jam_selesai TIME, bbm_awal INTEGER NOT NULL, bbm_akhir INTEGER, pemakaian INTEGER, sisa INTEGER, petugas TEXT, user_id BIGINT)")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS genset_maintenance (
            id SERIAL PRIMARY KEY, 
            tanggal DATE NOT NULL, 
            jam_penggunaan TEXT, 
            voltase_1p_v1 TEXT, 
            voltase_1p_v2 TEXT, 
            voltase_1p_v3 TEXT, 
            voltase_3p_v1v2 TEXT, 
            voltase_3p_v2v3 TEXT, 
            voltase_3p_v3v1 TEXT, 
            voltase_accu_mati TEXT, 
            voltase_accu_hidup TEXT, 
            bbm_persen TEXT, 
            air_radiator TEXT, 
            oli_mesin TEXT, 
            petugas TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("Database siap")

    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    genset_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            GEN_MULAI: [CommandHandler('cancel', cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, genset_mulai)],
            GEN_BBM_AWAL: [CommandHandler('cancel', cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, genset_bbm_awal)],
            GEN_BBM_AKHIR: [CommandHandler('cancel', cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, genset_bbm_akhir)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, terima_alasan)]},
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(genset_conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot jalan... Absen + Genset + Grafik + Maintenance (Dual Accu & Centered Page Style)")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
