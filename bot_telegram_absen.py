import os
import threading
import psycopg2
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")

REASON = 1
GEN_MULAI, GEN_BBM_AWAL, GEN_BBM_AKHIR = range(3)

# ===== DB SUPABASE =====
def get_db():
    return psycopg2.connect(os.getenv("SUPABASE_URL"))

def query_db(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(query, params)
            if commit:
                conn.commit()
                return cur.rowcount
            if fetchone: return cur.fetchone()
            if fetchall: return cur.fetchall()
    except Exception as e:
        logger.error(f"[DB ERROR] {e}")
        return None
    finally:
        if conn: conn.close()

def create_tables():
    # Tabel absen standar tanpa foto, tanpa latlon
    query_db("CREATE TABLE IF NOT EXISTS absensi (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, nama TEXT, tanggal DATE NOT NULL, jam_datang TIME, jam_pulang TIME, status TEXT DEFAULT 'hadir', alasan TEXT, telat BOOLEAN DEFAULT false, UNIQUE(user_id, tanggal))", commit=True)
    query_db("CREATE TABLE IF NOT EXISTS libur_nasional (tanggal DATE PRIMARY KEY)", commit=True)
    # Tabel genset
    query_db("CREATE TABLE IF NOT EXISTS genset_log (id SERIAL PRIMARY KEY, tanggal DATE NOT NULL, jam_mulai TIME NOT NULL, jam_selesai TIME, bbm_awal INTEGER NOT NULL, bbm_akhir INTEGER, pemakaian INTEGER, sisa INTEGER, petugas TEXT, user_id BIGINT)", commit=True)

# ===== WEB 2 PAGE =====
NAVBAR = """<nav style="background:#4CAF50;padding:15px;text-align:center">
<a href="/" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">📋 Absensi</a>
<a href="/genset" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">⛽ Genset BBM</a></nav>"""

ABSEN_HTML = NAVBAR + """
<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Data Absensi</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:Arial;padding:20px;background:#f5f5f5}h2{text-align:center}
table{width:100%;border-collapse:collapse;background:white}th,td{padding:12px;border-bottom:1px solid #ddd}
th{background:#4CAF50;color:white}tr:hover{background:#f1f1f1}.telat{background:#ffebee;color:#c62828;font-weight:bold}
.status-lembur{color:purple;font-weight:bold}.filter{text-align:center;margin:20px}
@media(max-width:600px){table,thead,tbody,th,td,tr{display:block}th{display:none}
td{border:none;position:relative;padding-left:40%}td:before{content:attr(data-label);position:absolute;left:10px;font-weight:bold}}
</style></head><body><h2>📋 Data Absensi Karyawan</h2>
<div class="filter"><form method="get"><input type="date" name="tanggal" value="{tgl}">
<button>Filter</button><a href="/"><button type="button">Reset</button></a></form></div>
<table><thead><tr><th>Nama</th><th>Tanggal</th><th>Datang</th><th>Pulang</th><th>Status</th><th>Alasan</th><th>Total Jam</th></tr></thead><tbody>{rows}</tbody></table></body></html>
"""

GENSET_HTML = NAVBAR + """
<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Log Genset</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:Arial;padding:20px;background:#f5f5f5}h2{text-align:center}
table{width:100%;border-collapse:collapse;background:white}th,td{padding:12px;border-bottom:1px solid #ddd}
th{background:#FF9800;color:white}tr:hover{background:#fff3e0}.sisa-rendah{background:#ffebee;color:#c62828;font-weight:bold}
.filter{text-align:center;margin:20px}</style></head>
<body><h2>⛽ Log Penggunaan Genset & BBM</h2><div class="filter"><form method="get">
<input type="date" name="tanggal" value="{tgl}"><button>Filter</button><a href="/genset"><button type="button">Reset</button></a></form></div>
<table><tr><th>Tanggal</th><th>Mulai</th><th>Selesai</th><th>BBM Awal</th><th>BBM Akhir</th><th>Pakai</th><th>Sisa</th><th>Petugas</th></tr>{rows}</table></body></html>
"""

@app_flask.route('/')
def home_absen():
    tanggal = request.args.get('tanggal')
    sql = "SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan, telat, EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik, CASE WHEN jam_datang > TIME '09:00:00' THEN true ELSE false END as telat_flag FROM absensi"
    if tanggal: sql += f" WHERE tanggal='{tanggal}'"
    sql += " ORDER BY tanggal DESC, jam_datang DESC LIMIT 200"
    data = query_db(sql, fetchall=True)

    rows = ""
    for r in data or []:
        nama, tanggal, datang, pulang, status, alasan, telat_db, total_detik, telat_flag = r
        row_class = "telat" if telat_flag else ""
        status_class = "status-lembur" if status == 'lembur' else ""
        total_detik = int(total_detik) if total_detik else 0
        h, m = divmod(total_detik, 3600)
        total_jam = f"{h:02d}j {m//60:02d}m" if total_detik > 0 else "-"
        rows += f'<tr class="{row_class}"><td data-label="Nama">{nama}</td><td data-label="Tanggal">{tanggal}</td><td data-label="Datang">{datang.strftime("%H:%M:%S") if datang else "-"}</td><td data-label="Pulang">{pulang.strftime("%H:%M:%S") if pulang else "-"}</td><td data-label="Status" class="{status_class}">{status or "hadir"}</td><td data-label="Alasan">{alasan or "-"}</td><td data-label="Total Jam">{total_jam}</td></tr>'

    return ABSEN_HTML.format(tgl=tanggal if tanggal else "", rows=rows)

@app_flask.route('/genset')
def home_genset():
    tanggal = request.args.get('tanggal')
    sql = "SELECT tanggal, jam_mulai, jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, petugas FROM genset_log"
    if tanggal: sql += f" WHERE tanggal='{tanggal}'"
    sql += " ORDER BY tanggal DESC, jam_mulai DESC LIMIT 200"
    data = query_db(sql, fetchall=True)

    rows = ""
    for r in data or []:
        tanggal, mulai, selesai, awal, akhir, pakai, sisa, petugas = r
        row_class = "sisa-rendah" if sisa and sisa < 20 else ""
        rows += f'<tr class="{row_class}"><td>{tanggal}</td><td>{mulai.strftime("%H:%M") if mulai else "-"}</td><td>{selesai.strftime("%H:%M") if selesai else "-"}</td><td>{awal}%</td><td>{akhir}%</td><td>{pakai}%</td><td>{sisa}%</td><td>{petugas}</td></tr>'

    return GENSET_HTML.format(tgl=tanggal if tanggal else "", rows=rows)

# ===== BOT LOGIC ABSEN STANDAR =====
def is_libur(tanggal):
    if tanggal.weekday() == 6: return True, "Minggu"
    result = query_db("SELECT 1 FROM libur_nasional WHERE tanggal=%s", (tanggal,), fetchone=True)
    return (True, "Libur Nasional") if result else (False, None)

def get_keyboard(status):
    main_btn = []
    if status == 'belum':
        main_btn = [InlineKeyboardButton("✅ Datang", callback_data='datang'), InlineKeyboardButton("🚪 Pulang", callback_data='pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin')]
    elif status in ['datang', 'lembur']:
        main_btn = [InlineKeyboardButton("🚪 Pulang", callback_data='pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin'), InlineKeyboardButton("🤒 Sakit", callback_data='sakit')]
    buttons = [main_btn] if main_btn else []
    buttons += [[InlineKeyboardButton("📊 Rekap", callback_data='rekap'), InlineKeyboardButton("📋 Saya", callback_data='saya'), InlineKeyboardButton("⛽ Genset", callback_data='genset')], [InlineKeyboardButton("⬇️ Download", callback_data='download'), InlineKeyboardButton("👑 Admin", callback_data='admin'), InlineKeyboardButton("❌", callback_data='noop')]]
    return InlineKeyboardMarkup(buttons)

def cek_absen(user_id):
    hari_ini = datetime.now(WIB).date()
    data = query_db("SELECT jam_datang, jam_pulang, status FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini), fetchone=True)
    if not data: return 'belum'
    jam_datang, jam_pulang, status = data
    if status in ['izin', 'sakit', 'cuti', 'lembur']: return status
    return 'datang' if jam_datang and not jam_pulang else 'selesai' if jam_datang and jam_pulang else 'belum'

def simpan_datang(user_id, nama):
    wib_now = datetime.now(WIB)
    hari_ini = wib_now.date()
    jam_sekarang = wib_now.time()
    telat = jam_sekarang > datetime.strptime('09:00:00', '%H:%M:%S').time()
    libur, jenis_libur = is_libur(hari_ini)
    status = 'lembur' if libur else 'hadir'

    query_db("INSERT INTO absensi (user_id, nama, tanggal, jam_datang, status, telat, alasan) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id, tanggal) DO UPDATE SET jam_datang=%s", (user_id, nama, hari_ini, jam_sekarang, status, telat, jenis_libur, jam_sekarang), commit=True)
    return True, telat, libur, jenis_libur

def simpan_pulang(user_id):
    wib_now = datetime.now(WIB)
    hari_ini = wib_now.date()
    jam_sekarang = wib_now.time()
    updated = query_db("UPDATE absensi SET jam_pulang=%s WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL", (jam_sekarang, user_id, hari_ini), commit=True)
    return updated > 0

def simpan_izin(user_id, nama, status, alasan):
    hari_ini = datetime.now(WIB).date()
    query_db("INSERT INTO absensi (user_id, nama, tanggal, status, alasan) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id, tanggal) DO UPDATE SET status=%s, alasan=%s", (user_id, nama, hari_ini, status, alasan, status, alasan), commit=True)

# ===== GENSET CONVERSATION =====
async def genset_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("⛽ *Catat Penggunaan Genset*\n\n1/3 Jam mulai? Ketik 08:30", parse_mode='Markdown')
    return GEN_MULAI

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
        await update.message.reply_text("3/3 BBM akhir %? Contoh: 60")
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

        query_db("INSERT INTO genset_log (tanggal, jam_mulai, jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, petugas, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (tanggal, context.user_data['jam_mulai'], jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, nama, user_id), commit=True)

        await update.message.reply_text(f"✅ *Genset Dicatat*\n📅 {tanggal}\n⏰ {context.user_data['jam_mulai']} - {jam_selesai}\n⛽ BBM Awal: {bbm_awal}%\n⛽ BBM Akhir: {bbm_akhir}%\n🔥 Pemakaian: {pemakaian}%\n💧 Sisa: {sisa}%\n👤 Petugas: {nama}", parse_mode='Markdown')
        context.user_data.clear()
        return ConversationHandler.END
    except:
        await update.message.reply_text("Isi angka 0-100")
        return GEN_BBM_AKHIR

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status = cek_absen(user_id)
    hari_ini = datetime.now(WIB).strftime('%d/%m/%Y')
    keyboard = get_keyboard(status)
    teks = f"🤖 *Absen & Genset*\n📅 {hari_ini}\n\n"
    teks += "Waktunya absen datang" if status == 'belum' else "✅ Sudah absen datang\nSilakan absen pulang" if status in ['datang', 'lembur'] else f"📝 Status: {status}" if status in ['izin', 'sakit', 'cuti'] else "Absensi hari ini sudah selesai"
    await update.message.reply_text(teks, reply_markup=keyboard, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nama = query.from_user.first_name
    button_id = query.data
    status = cek_absen(user_id)

    if button_id == 'datang':
        if status!= 'belum': await query.answer("Sudah absen datang", show_alert=True); return
        success, telat, libur, jenis_libur = simpan_datang(user_id, nama)
        if success:
            teks = f"✅ Absen datang berhasil!\nWaktu: {datetime.now(WIB).strftime('%H:%M:%S')}"
            if libur: teks += f"\n💜 *LEMBUR* - {jenis_libur}"
            if telat: teks += "\n⚠️ *Kamu telat!*"
            teks += "\n\nSilakan absen pulang"
            await query.edit_message_text(text=teks, reply_markup=get_keyboard('datang'), parse_mode='Markdown')
    elif button_id == 'pulang':
        if status not in ['datang', 'lembur']: await query.answer("Belum absen datang", show_alert=True); return
        if simpan_pulang(user_id):
            data = query_db("SELECT jam_datang, jam_pulang, status, EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, datetime.now(WIB).date()), fetchone=True)
            jam_datang_str = data[0].strftime('%H:%M:%S')
            jam_pulang_str = data[1].strftime('%H:%M:%S')
            status_akhir = data[2]
            total_detik = int(data[3]) if data[3] else 0
            h, m = divmod(total_detik, 3600)
            total_jam = f"{h:02d}j {m//60:02d}m"
            teks = f"🤖 *Absen Selesai*\n📅 {datetime.now(WIB).strftime('%d/%m/%Y')}\n━━━━━━━━━━━━━━\n✅ Datang: {jam_datang_str}\n🚪 Pulang: {jam_pulang_str}\n⏱️ Total Jam Kerja: {total_jam}\n"
            if status_akhir == 'lembur': teks += f"💜 Status: LEMBUR\n"
            teks += f"Absen hari ini sudah selesai"
            await query.edit_message_text(text=teks, parse_mode='Markdown', reply_markup=get_keyboard('selesai'))
    elif button_id == 'genset':
        await query.delete_message()
        return await genset_start(update, context)
    elif button_id in ['izin', 'sakit', 'cuti']:
        context.user_data['step'] = 'tunggu_alasan'
        context.user_data['status_izin'] = button_id
        await query.delete_message()
        await context.bot.send_message(user_id, f"Kirim alasan {button_id}:")
        return REASON
    elif button_id == 'noop':
        await query.edit_message_text("Menu ditutup. Ketik /start", reply_markup=None)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and context.user_data.get('step') == 'tunggu_alasan':
        teks = update.message.text.strip()
        status = context.user_data.get('status_izin')
        simpan_izin(update.effective_user.id, update.effective_user.first_name, status, teks)
        context.user_data.clear()
        await update.message.reply_text(f"✅ Status {status} tersimpan", reply_markup=get_keyboard(cek_absen(update.effective_user.id)))
        return

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.getenv("TOKEN")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    if not TOKEN or not SUPABASE_URL:
        logger.error("TOKEN/SUPABASE_URL kosong")
        return

    create_tables()
    logger.info("Database siap - versi standar")
    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    genset_conv = ConversationHandler(
        entry_points=[CommandHandler('genset', genset_start)],
        states={GEN_MULAI: [MessageHandler(filters.TEXT, genset_mulai)], GEN_BBM_AWAL: [MessageHandler(filters.TEXT, genset_bbm_awal)], GEN_BBM_AKHIR: [MessageHandler(filters.TEXT, genset_bbm_akhir)]},
        fallbacks=[CommandHandler('cancel', lambda u,c: ConversationHandler.END)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(genset_conv)

    logger.info("Bot jalan. Versi standar: Absen + Genset. Tanpa foto, tanpa sheet")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
