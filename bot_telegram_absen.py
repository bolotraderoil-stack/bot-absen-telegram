# -*- coding: utf-8 -*-
import os
import threading
import psycopg2
import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, Response, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters

WIB = ZoneInfo("Asia/Jakarta")
TOKEN = os.getenv("TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")

app_flask = Flask(__name__)
app_telegram = ApplicationBuilder().token(TOKEN).build()

REASON, GEN_MULAI, GEN_AWAL, GEN_AKHIR = range(4)

def get_db():
    return psycopg2.connect(SUPABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS absensi (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        nama TEXT,
        tanggal DATE,
        jam_datang TIME,
        jam_pulang TIME,
        status TEXT DEFAULT 'hadir',
        alasan TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS genset (
        id SERIAL PRIMARY KEY,
        tanggal DATE,
        jam_mulai TIME,
        bbm_awal INT,
        bbm_akhir INT,
        pemakaian INT,
        user_id BIGINT,
        nama TEXT
    )""")
    conn.commit()
    cur.close()
    conn.close()

# ===== BOT TELEGRAM =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Datang", callback_data='datang'),
         InlineKeyboardButton("Pulang", callback_data='pulang')],
        [InlineKeyboardButton("Izin/Sakit", callback_data='izin')],
        [InlineKeyboardButton("Rekap Bulan Ini", callback_data='rekap')],
        [InlineKeyboardButton("Input Genset", callback_data='genset')],
        [InlineKeyboardButton("Lihat Genset", callback_data='lihat_genset')]
    ]
    await update.message.reply_text(
        "Halo! Pilih menu di bawah:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nama = query.from_user.first_name
    hari_ini = datetime.now(WIB).date()

    if query.data == 'datang':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
        if cur.fetchone():
            await query.edit_message_text("Kamu sudah absen datang hari ini.")
        else:
            jam = datetime.now(WIB).time()
            cur.execute("INSERT INTO absensi(user_id,nama,tanggal,jam_datang) VALUES(%s,%s,%s,%s)",
                        (user_id, nama, hari_ini, jam))
            conn.commit()
            await query.edit_message_text(f"Absen datang dicatat jam {jam.strftime('%H:%M')}")
        cur.close()
        conn.close()

    elif query.data == 'pulang':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE absensi SET jam_pulang=%s WHERE user_id=%s AND tanggal=%s AND jam_pulang IS NULL",
                    (datetime.now(WIB).time(), user_id, hari_ini))
        if cur.rowcount > 0:
            conn.commit()
            await query.edit_message_text("Absen pulang dicatat. Makasih!")
        else:
            await query.edit_message_text("Kamu belum absen datang atau sudah pulang.")
        cur.close()
        conn.close()

    elif query.data == 'izin':
        await query.edit_message_text("Ketik alasan izin/sakit:")
        return REASON

    elif query.data == 'rekap':
        conn = get_db()
        cur = conn.cursor()
        bulan_ini = hari_ini.replace(day=1)
        cur.execute("SELECT tanggal,jam_datang,jam_pulang,status FROM absensi WHERE user_id=%s AND tanggal>=%s ORDER BY tanggal",
                    (user_id, bulan_ini))
        rows = cur.fetchall()
        text = f"Rekap {nama} bulan ini:\n\n"
        for r in rows:
            text += f"{r[0]} | Datang:{r[1]} Pulang:{r[2]} {r[3]}\n"
        await query.edit_message_text(text or "Belum ada data bulan ini")
        cur.close()
        conn.close()

    elif query.data == 'genset':
        await query.edit_message_text("Jam mulai genset? Format: 08:30")
        return GEN_MULAI

    elif query.data == 'lihat_genset':
        return

async def reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nama = update.effective_user.first_name
    hari_ini = datetime.now(WIB).date()
    alasan = update.message.text
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO absensi(user_id,nama,tanggal,status,alasan) VALUES(%s,%s,%s,'izin',%s)",
                (user_id, nama, hari_ini, alasan))
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text("Izin dicatat. Jaga kesehatan!")
    return ConversationHandler.END

async def gen_mulai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        jam = datetime.strptime(update.message.text, "%H:%M").time()
        context.user_data['jam_mulai'] = jam
        await update.message.reply_text("BBM awal dalam %? Contoh: 90")
        return GEN_AWAL
    except:
        await update.message.reply_text("Format salah. Ketik 08:30")
        return GEN_MULAI

async def gen_awal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bbm = int(update.message.text)
        context.user_data['bbm_awal'] = bbm
        await update.message.reply_text("BBM akhir dalam %? Contoh: 60")
        return GEN_AKHIR
    except:
        await update.message.reply_text("Isi angka 0-100")
        return GEN_AWAL

async def gen_akhir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bbm_akhir = int(update.message.text)
        bbm_awal = context.user_data['bbm_awal']
        pemakaian = bbm_awal - bbm_akhir
        user_id = update.effective_user.id
        nama = update.effective_user.first_name
        hari_ini = datetime.now(WIB).date()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO genset(tanggal,jam_mulai,bbm_awal,bbm_akhir,pemakaian,user_id,nama) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (hari_ini, context.user_data['jam_mulai'], bbm_awal, bbm_akhir, pemakaian, user_id, nama))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text(f"Data genset tersimpan. Pemakaian: {pemakaian}%")
        return ConversationHandler.END
    except:
        await update.message.reply_text("Isi angka 0-100")
        return GEN_AKHIR

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Dibatalkan.")
    return ConversationHandler.END

conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(button)],
    states={
        REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, reason)],
        GEN_MULAI: [MessageHandler(filters.TEXT & ~filters.COMMAND, gen_mulai)],
        GEN_AWAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, gen_awal)],
        GEN_AKHIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, gen_akhir)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

app_telegram.add_handler(CommandHandler("start", start))
app_telegram.add_handler(conv_handler)

# ===== WEB FLASK RESPONSIVE =====
TEMPLATE_GENSET = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Log Genset</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
*{box-sizing:border-box}
body{font-family:Arial,sans-serif;margin:0;padding:15px;background:#f5f5f5}
h2{text-align:center;color:#333}
.container{max-width:1000px;margin:auto}
.filter{margin:20px 0;text-align:center}
input,button{padding:8px 12px;margin:5px;border:1px solid #ddd;border-radius:5px}
button{background:#FF9800;color:white;border:none;cursor:pointer}
.chart-box{background:white;padding:20px;border-radius:10px;margin:20px 0;height:400px}
table{width:100%;border-collapse:collapse;background:white;border-radius:10px;overflow:hidden}
th{background:#FF9800;color:white;padding:12px}
td{padding:12px;text-align:center;border-bottom:1px solid #eee}
tr.low{background:#ffebee;color:#c62828;font-weight:bold}
@media(max-width:768px){
   .chart-box{height:300px;padding:10px}
    table{font-size:12px}
    th,td{padding:6px}
</style>
</head>
<body>
<div class="container">
<h2>Log Genset + Grafik BBM</h2>
<div class="filter">
<form method="get">
<input type="date" name="tanggal" value="{{tanggal}}">
<button type="submit">Filter</button>
<a href="/export_genset?tanggal={{tanggal}}"><button type="button">Export CSV</button></a>
</form>
</div>
<div class="chart-box">
<canvas id="grafik"></canvas>
</div>
<table>
<tr><th>Tanggal</th><th>Jam Mulai</th><th>BBM Awal</th><th>BBM Akhir</th><th>Pakai</th><th>Nama</th></tr>
{% for r in data %}
<tr class="{{'low' if r[5] < 30 else ''}}">
<td>{{r[1]}}</td>
<td>{{r[2].strftime('%H:%M') if r[2] else '-'}}</td>
<td>{{r[3]}}%</td>
<td>{{r[4]}}%</td>
<td>{{r[5]}}%</td>
<td>{{r[7]}}</td>
</tr>
{% endfor %}
</table>
</div>
<script>
const ctx = document.getElementById('grafik').getContext('2d');
new Chart(ctx, {
    type: 'line',
    data: {
        labels: {{labels|tojson}},
        datasets: [{
            label: 'Sisa BBM %',
            data: {{sisa|tojson}},
            borderColor: '#f44336',
            backgroundColor: 'rgba(244,67,54,0.2)',
            tension: 0.4,
            fill: true
        },{
            label: 'Pemakaian %',
            data: {{pakai|tojson}},
            borderColor: '#2196F3',
            backgroundColor: 'rgba(33,150,243,0.2)',
            tension: 0.4,
            fill: true
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {y: {beginAtZero: true, max: 100}}
    }
});
</script>
</body>
</html>
"""

@app_flask.route('/genset')
def genset_web():
    tanggal = request.args.get('tanggal', '')
    conn = get_db()
    cur = conn.cursor()
    if tanggal:
        cur.execute("SELECT * FROM genset WHERE tanggal=%s ORDER BY jam_mulai", (tanggal,))
    else:
        cur.execute("SELECT * FROM genset ORDER BY tanggal DESC, jam_mulai DESC LIMIT 100")
    data = cur.fetchall()
    cur.close()
    conn.close()

    labels = [f"{r[1]} {r[2].strftime('%H:%M') if r[2] else ''}" for r in data]
    sisa = [r[4] for r in data]
    pakai = [r[5] for r in data]

    return render_template_string(TEMPLATE_GENSET, data=data, labels=labels, sisa=sisa, pakai=pakai, tanggal=tanggal)

@app_flask.route('/export_genset')
def export_genset():
    tanggal = request.args.get('tanggal', '')
    conn = get_db()
    cur = conn.cursor()
    if tanggal:
        cur.execute("SELECT * FROM genset WHERE tanggal=%s ORDER BY jam_mulai", (tanggal,))
    else:
        cur.execute("SELECT * FROM genset ORDER BY tanggal DESC")
    data = cur.fetchall()
    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID','Tanggal','Jam Mulai','BBM Awal','BBM Akhir','Pemakaian','User ID','Nama'])
    writer.writerows(data)
    output.seek(0)
    return Response(output, mimetype="text/csv",
                    headers={"Content-Disposition":f"attachment;filename=genset_{tanggal or 'all'}.csv"})

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app_flask.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot + Web jalan...")
    app_telegram.run_polling()
