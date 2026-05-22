import os
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, request, render_template_string
from datetime import datetime, time
import pytz

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
WIB = pytz.timezone("Asia/Jakarta")
JAM_MASUK = time(9, 0, 0)  # Ubah sesuai jam masuk kantor

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def format_interval(interval):
    """Convert Postgres interval ke format 08j 34m"""
    if not interval:
        return None
    
    total_seconds = int(interval.total_seconds())
    if total_seconds < 0:
        return None
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}j {minutes:02d}m"

@app.route("/", methods=["GET"])
def home():
    tanggal = request.args.get("tanggal")
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    
    try:
        if tanggal:
            cur.execute("""
                SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan,
                (jam_pulang - jam_datang) as durasi,
                telat
                FROM absensi
                WHERE tanggal = %s
                ORDER BY nama, tanggal DESC
            """, (tanggal,))
        else:
            cur.execute("""
                SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan,
                (jam_pulang - jam_datang) as durasi,
                telat
                FROM absensi
                ORDER BY tanggal DESC, nama
                LIMIT 100
            """)
        
        data = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    
    html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Data Absensi</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; padding: 10px; background: #f5f5f5; margin: 0; }
        h2 { text-align: center; color: #333; }
        .filter { text-align: center; margin-bottom: 20px; }
        input, button { padding: 10px; font-size: 16px; border: 1px solid #ddd; border-radius: 6px; }
        button { background: #4CAF50; color: white; border: none; cursor: pointer; }
        button:hover { background: #45a049; }
        .table-wrapper { overflow-x: auto; background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; min-width: 600px; }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #4CAF50; color: white; font-weight: 600; position: sticky; top: 0; }
        tr:hover { background: #f9f9f9; }
        .telat { background: #ffebee !important; color: #c62828; font-weight: bold; }
        .status-izin { color: orange; font-weight: 600; }
        .status-sakit { color: red; font-weight: 600; }
        .status-cuti { color: blue; font-weight: 600; }
        @media (max-width: 768px) {
            body { padding: 5px; }
            table, thead, tbody, th, td, tr { display: block; }
            thead { display: none; }
            tr { margin-bottom: 12px; background: white; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); padding: 10px 0; }
            td { border: none; padding: 8px 15px; position: relative; text-align: right; }
            td:before {
                content: attr(data-label);
                position: absolute;
                left: 15px;
                font-weight: 600;
                color: #666;
                text-align: left;
            }
        }
    </style>
</head>
<body>
    <h2>📋 Data Absensi</h2>
    <div class="filter">
        <form method="get">
            <input type="date" name="tanggal" value="{tgl}">
            <button type="submit">Filter</button>
            <a href="/"><button type="button">Reset</button></a>
        </form>
    </div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Nama</th><th>Tanggal</th><th>Datang</th><th>Pulang</th>
                    <th>Status</th><th>Alasan</th><th>Total Jam</th>
                </tr>
            </thead>
            <tbody>
""".format(tgl=tanggal if tanggal else "")

    for row in data:
        nama = row['nama']
        tanggal = row['tanggal']
        datang = row['jam_datang']
        pulang = row['jam_pulang']
        status = row['status']
        alasan = row['alasan']
        durasi = row['durasi']
        telat = row['telat']
        
        row_class = "telat" if telat else ""
        status_class = f"status-{status}" if status else ""
        total_jam = format_interval(durasi)
        
        html += f"""
    <tr class="{row_class}">
        <td data-label="Nama">{nama}</td>
        <td data-label="Tanggal">{tanggal}</td>
        <td data-label="Datang">{datang.strftime('%H:%M:%S') if datang else '-'}</td>
        <td data-label="Pulang">{pulang.strftime('%H:%M:%S') if pulang else '-'}</td>
        <td data-label="Status" class="{status_class}">{status or 'hadir'}</td>
        <td data-label="Alasan">{alasan or '-'}</td>
        <td data-label="Total Jam">{total_jam if total_jam else '-'}</td>
    </tr>
    """

    html += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    return html

@app.route("/api/absensi", methods=["POST"])
def api_absensi():
    data = request.json
    user_id = data.get("user_id")
    nama = data.get("nama")
    tanggal = data.get("tanggal")
    jam_datang = data.get("jam_datang")
    jam_pulang = data.get("jam_pulang")
    status = data.get("status", "hadir")
    alasan = data.get("alasan")
    
    # Cek telat pakai timezone WIB
    telat = False
    if jam_datang:
        try:
            if isinstance(jam_datang, str):
                waktu_datang = datetime.strptime(jam_datang, "%H:%M:%S").time()
            else:
                waktu_datang = jam_datang
            telat = waktu_datang > JAM_MASUK
        except:
            pass
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO absensi (user_id, nama, tanggal, jam_datang, jam_pulang, status, alasan, telat)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, tanggal) 
            DO UPDATE SET 
                jam_datang = EXCLUDED.jam_datang,
                jam_pulang = EXCLUDED.jam_pulang,
                status = EXCLUDED.status,
                alasan = EXCLUDED.alasan,
                telat = EXCLUDED.telat,
                nama = EXCLUDED.nama
        """, (user_id, nama, tanggal, jam_datang, jam_pulang, status, alasan, telat))
        
        conn.commit()
    finally:
        cur.close()
        conn.close()
    
    return {"status": "success"}

@app.route("/api/absensi/saya", methods=["GET"])
def get_data_saya():
    user_id = request.args.get("user_id")
    limit = request.args.get("limit", 10)
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    
    try:
        cur.execute("""
            SELECT tanggal, jam_datang, jam_pulang, status, alasan,
            (jam_pulang - jam_datang) as durasi,
            telat
            FROM absensi
            WHERE user_id = %s
            ORDER BY tanggal DESC
            LIMIT %s
        """, (user_id, limit))
        
        rows = cur.fetchall()
        
        # Convert interval ke string sebelum kirim JSON
        data = []
        for row in rows:
            row = dict(row)
            row['total_jam'] = format_interval(row.pop('durasi'))
            if row['jam_datang']:
                row['jam_datang'] = row['jam_datang'].strftime('%H:%M:%S')
            if row['jam_pulang']:
                row['jam_pulang'] = row['jam_pulang'].strftime('%H:%M:%S')
            data.append(row)
        
    finally:
        cur.close()
        conn.close()
    
    return {"data": data}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
