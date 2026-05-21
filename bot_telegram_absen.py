import os
import threading
import psycopg2
import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

REASON = 1

@app_flask.route('/')
def home():
    try:
        tanggal = request.args.get('tanggal')
        conn = get_db()
        cur = conn.cursor()

        if tanggal:
            cur.execute("""
                SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan,
                CASE
                    WHEN jam_pulang IS NOT NULL AND jam_datang IS NOT NULL
                    THEN ROUND(EXTRACT(EPOCH FROM (jam_pulang - jam_datang))/3600, 2)
                    ELSE NULL
                END as total_jam,
                CASE
                    WHEN jam_datang > TIME '09:00:00' THEN true
                    ELSE false
                END as telat
                FROM absensi
                WHERE tanggal=%s
                ORDER BY jam_datang DESC
            """, (tanggal,))
        else:
            cur.execute("""
                SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan,
                CASE
                    WHEN jam_pulang IS NOT NULL AND jam_datang IS NOT NULL
                    THEN ROUND(EXTRACT(EPOCH FROM (jam_pulang - jam_datang))/3600, 2)
                    ELSE NULL
                END as total_jam,
                CASE
                    WHEN jam_datang > TIME '09:00:00' THEN true
                    ELSE false
                END as telat
                FROM absensi
                ORDER BY tanggal DESC, jam_datang DESC
                LIMIT 100
            """)

        data = cur.fetchall()
        conn.close()
    except Exception as e:
        return f"<h2>Error Koneksi DB</h2><pre>{e}</pre>", 500

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Data Absensi</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
            h2 {{ text-align: center; }}
            table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #4CAF50; color: white; }}
            tr:hover {{ background: #f1f1f1; }}
           .telat {{ background: #ffebee; color: #c62828; font-weight: bold; }}
           .status-izin {{ color: orange; }}
           .status-sakit {{ color: red; }}
           .status-cuti {{ color: blue; }}
           .filter {{ text-align: center; margin-bottom: 20px; }}
            input, button {{ padding: 8px; font-size: 16px; }}
            @media (max-width: 600px) {{
                table, thead, tbody, th, td, tr {{ display: block; }}
                th {{ display: none; }}
                td {{ border: none; position: relative; padding-left: 50%; }}
                td:before {{
                    content: attr(data-label);
                    position: absolute;
                    left: 10px;
                    font-weight: bold;
                }}
            }}
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
        nama, tanggal, datang, pulang, status, alasan, total_jam, telat = row
        row_class = "telat" if telat else ""
        status_class = f"status-{status}" if status else ""
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
    </body>
    </html>
    """
    return html
    
def get_db():
    return psycopg2.connect(os.getenv("SUPABASE_URL"))

def is_libur(tanggal):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM libur_nasional WHERE tanggal=%s", (tanggal,))
    result = cur.fetchone()
    conn.close()
    return result is not None

def get_keyboard(status):
    buttons = []

    if status == 'belum':
        # Baris 1
        buttons.append([
            InlineKeyboardButton("✅ Datang", callback_data='datang'),
            InlineKeyboardButton("🚪 Pulang", callback_data='pulang'),
            InlineKeyboardButton("📝 Izin", callback_data='izin')
        ])
        # Baris 2
        buttons.append([
            InlineKeyboardButton("🤒 Sakit", callback_data='sakit'),
            InlineKeyboardButton("🏖️ Cuti", callback_data='cuti'),
            InlineKeyboardButton("📊 Rekap", callback_data='rekap')
        ])
        # Baris 3
        buttons.append([
            InlineKeyboardButton("📋 Saya", callback_data='saya'),
            InlineKeyboardButton("👥 Tim", callback_data='tim'),
            InlineKeyboardButton("👑 Admin", callback_data='admin')
        ])

    elif status == 'datang':
        buttons.append([
            InlineKeyboardButton("🚪 Pulang", callback_data='pulang'),
            InlineKeyboardButton("📝 Izin", callback_data='izin'),
            InlineKeyboardButton("📊 Rekap", callback_data='rekap')
        ])
        buttons.append([
            InlineKeyboardButton("📋 Saya", callback_data='saya'),
            InlineKeyboardButton("👥 Tim", callback_data='tim'),
            InlineKeyboardButton("👑 Admin", callback_data='admin')
        ])

    else:
        buttons.append([
            InlineKeyboardButton("📊 Rekap", callback_data='rekap'),
            InlineKeyboardButton("📋 Saya", callback_data='saya'),
            InlineKeyboardButton("👥 Tim", callback_data='tim')
        ])

    return InlineKeyboardMarkup(buttons)

def cek_absen(user_id):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("SELECT jam_datang, jam_pulang, status FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
    data = cur.fetchone()
    conn.close()
    if not data:
        return 'belum'
    if data[2] in ['izin', 'sakit', 'cuti']:
        return data[2]
    if data[0] and not data[1]:
        return 'datang'
    if data[0] and data[1]:
        return 'selesai'
    return 'belum'

def simpan_datang(user_id, nama):
    conn = get_db()
    cur = conn.cursor()
    wib = datetime.now(WIB)
    hari_ini = wib.date()
    jam_sekarang = wib.time()
    telat = jam_sekarang > datetime.strptime('09:00:00', '%H:%M:%S').time()

    try:
        cur.execute("""
            INSERT INTO absensi (user_id, nama, tanggal, jam_datang, status, telat)
            VALUES (%s, %s, %s, %s, 'hadir', %s)
            ON CONFLICT (user_id, tanggal) DO NOTHING
        """, (user_id, nama, hari_ini, jam_sekarang, telat))
        conn.commit()
        return True, telat
    except Exception as e:
        print("Error simpan_datang:", e)
        return False, False
    finally:
        conn.close()

def simpan_pulang(user_id):
    conn = get_db()
    cur = conn.cursor()
    wib = datetime.now(WIB)
    hari_ini = wib.date()
    jam_sekarang = wib.time()
    cur.execute("""
        UPDATE absensi SET jam_pulang=%s
        WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL
    """, (jam_sekarang, user_id, hari_ini))
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated

def simpan_izin(user_id, nama, status, alasan):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("""
        INSERT INTO absensi (user_id, nama, tanggal, status, alasan)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id, tanggal)
        DO UPDATE SET status=%s, alasan=%s
    """, (user_id, nama, hari_ini, status, alasan, status, alasan))
    conn.commit()
    conn.close()

def get_rekap_bulanan(user_id, bulan_str=None):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(WIB)

    if bulan_str:
        tahun, bulan = map(int, bulan_str.split('-'))
    else:
        tahun, bulan = now.year, now.month

    cur.execute("""
        SELECT COUNT(*) as hari_hadir,
               SUM(EXTRACT(EPOCH FROM (jam_pulang - jam_datang))/3600) as total_jam,
               SUM(CASE WHEN telat THEN 1 ELSE 0 END) as total_telat
        FROM absensi
        WHERE user_id=%s
        AND EXTRACT(MONTH FROM tanggal) = %s
        AND EXTRACT(YEAR FROM tanggal) = %s
        AND jam_pulang IS NOT NULL
        AND status = 'hadir'
    """, (user_id, bulan, tahun))

    data = cur.fetchone()
    conn.close()

    hari_hadir = data[0] if data[0] else 0
    total_jam = round(float(data[1]), 2) if data[1] else 0
    total_telat = data[2] if data[2] else 0
    return hari_hadir, total_jam, total_telat

def get_data_saya(user_id):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    tujuh_hari_lalu = hari_ini - timedelta(days=7)

    cur.execute("""
        SELECT tanggal, jam_datang, jam_pulang, status, alasan,
        CASE
            WHEN jam_pulang IS NOT NULL AND jam_datang IS NOT NULL
            THEN ROUND(EXTRACT(EPOCH FROM (jam_pulang - jam_datang))/3600, 2)
            ELSE NULL
        END as total_jam
        FROM absensi
        WHERE user_id=%s AND tanggal >= %s
        ORDER BY tanggal DESC
    """, (user_id, tujuh_hari_lalu))

    data = cur.fetchall()
    conn.close()
    return data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status = cek_absen(user_id)
    hari_ini = datetime.now(WIB).strftime('%d/%m/%Y')
    keyboard = get_keyboard(status)

    teks = f"🤖 *Absen*\n📅 {hari_ini}\n\n"
    if status == 'belum':
        teks += "Waktunya absen datang"
    elif status == 'datang':
        teks += "✅ Sudah absen datang\nSilakan absen pulang"
    elif status in ['izin', 'sakit', 'cuti']:
        teks += f"📝 Status hari ini: {status}"
    else:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT jam_datang, jam_pulang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, datetime.now(WIB).date()))
        data = cur.fetchone()
        conn.close()
        teks += f"✅ Datang: {data[0].strftime('%H:%M:%S')}\n"
        teks += f"🚪 Pulang: {data[1].strftime('%H:%M:%S')}\n\n"
        teks += "Absensi hari ini sudah selesai"

    await update.message.reply_text(teks, reply_markup=keyboard, parse_mode='Markdown')

async def rekap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bulan_str = context.args[0] if context.args else None

    try:
        hari_hadir, total_jam, total_telat = get_rekap_bulanan(user_id, bulan_str)
        bulan_nama = datetime.strptime(bulan_str, '%Y-%m').strftime('%B %Y') if bulan_str else datetime.now(WIB).strftime('%B %Y')
    except:
        await update.message.reply_text("Format salah. Contoh: `/rekap 2025-10`", parse_mode='Markdown')
        return

    teks = f"📊 *Rekap {bulan_nama}*\n\n"
    teks += f"📅 Hari Hadir: {hari_hadir} hari\n"
    teks += f"⏱️ Total Jam Kerja: {total_jam} jam\n"
    teks += f"⚠️ Telat: {total_telat} kali\n"
    teks += f"Rata-rata: {round(total_jam/hari_hadir, 2) if hari_hadir > 0 else 0} jam/hari"

    await update.message.reply_text(teks, parse_mode='Markdown')

async def saya_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_data_saya(user_id)

    if not data:
        await update.message.reply_text("Belum ada data absen 7 hari terakhir.")
        return

    teks = "*📋 Absen 7 Hari Terakhir*\n\n"
    for row in data:
        tanggal, datang, pulang, status, alasan, total_jam = row
        status_text = status or 'hadir'
        teks += f"*{tanggal}*\n"
        teks += f"Datang: {datang.strftime('%H:%M') if datang else '-'}\n"
        teks += f"Pulang: {pulang.strftime('%H:%M') if pulang else '-'}\n"
        teks += f"Status: {status_text}\n"
        if alasan:
            teks += f"Alasan: {alasan}\n"
        if total_jam:
            teks += f"Total: {total_jam} jam\n"
        teks += "\n"

    await update.message.reply_text(teks, parse_mode='Markdown')

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args)!= 1:
        await update.message.reply_text("Format: `/export 2025-10`", parse_mode='Markdown')
        return

    try:
        tahun, bulan = map(int, context.args[0].split('-'))
    except:
        await update.message.reply_text("Format salah. Contoh: `/export 2025-10`")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT tanggal, jam_datang, jam_pulang, status, alasan,
        CASE
            WHEN jam_pulang IS NOT NULL AND jam_datang IS NOT NULL
            THEN ROUND(EXTRACT(EPOCH FROM (jam_pulang - jam_datang))/3600, 2)
            ELSE NULL
        END as total_jam
        FROM absensi
        WHERE user_id=%s
        AND EXTRACT(MONTH FROM tanggal) = %s
        AND EXTRACT(YEAR FROM tanggal) = %s
        ORDER BY tanggal
    """, (user_id, bulan, tahun))

    data = cur.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Tanggal', 'Jam Datang', 'Jam Pulang', 'Status', 'Alasan', 'Total Jam'])
    for row in data:
        writer.writerow(row)

    output.seek(0)
    await update.message.reply_document(
        document=InputFile(io.BytesIO(output.getvalue().encode()), filename=f"absen_{context.args[0]}.csv"),
        caption="📄 Data absen bulan ini"
    )

async def tim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()

    cur.execute("""
        SELECT nama, jam_datang, telat FROM absensi
        WHERE tanggal=%s AND jam_datang IS NOT NULL
        ORDER BY jam_datang
    """, (hari_ini,))

    hadir = cur.fetchall()

    cur.execute("""
        SELECT nama FROM absensi
        WHERE tanggal=%s AND jam_datang IS NULL AND status NOT IN ('izin', 'sakit', 'cuti')
    """, (hari_ini,))

    belum = cur.fetchall()
    conn.close()

    teks = f"*👥 Kehadiran Tim - {hari_ini}*\n\n"
    teks += f"✅ *Sudah Hadir ({len(hadir)} orang):*\n"
    for nama, jam, telat in hadir:
        telat_text = " [TELAT]" if telat else ""
        teks += f"- {nama}: {jam.strftime('%H:%M')}{telat_text}\n"

    teks += f"\n❌ *Belum Absen ({len(belum)} orang):*\n"
    for nama, in belum:
        teks += f"- {nama}\n"

    await update.message.reply_text(teks, parse_mode='Markdown')

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!= ADMIN_ID:
        await update.message.reply_text("❌ Kamu bukan admin.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Belum Absen Hari Ini", callback_data='admin_belum')],
        [InlineKeyboardButton("📅 Tambah Libur", callback_data='admin_libur')]
    ])
    await update.message.reply_text("👑 *Admin Panel*", reply_markup=keyboard, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nama = query.from_user.first_name
    button_id = query.data
    status = cek_absen(user_id)
    wib = datetime.now(WIB)
    jam = wib.strftime('%H:%M:%S')
    hari_ini = wib.strftime('%d/%m/%Y')

    if button_id == 'datang':
        if status!= 'belum':
            await query.answer("Kamu sudah absen datang", show_alert=True)
            return
        success, telat = simpan_datang(user_id, nama)
        if success:
            telat_text = "\n⚠️ *Kamu telat!*" if telat else ""
            await query.edit_message_text(
                text=f"✅ Absen datang berhasil!\nWaktu: {jam}{telat_text}\n\nSilakan absen pulang",
                reply_markup=get_keyboard('datang'),
                parse_mode='Markdown'
            )
        else:
            await query.answer("Gagal absen datang", show_alert=True)

    elif button_id == 'pulang':
        if status!= 'datang':
            await query.answer("Kamu belum absen datang", show_alert=True)
            return
        if simpan_pulang(user_id):
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                SELECT jam_datang, jam_pulang,
                ROUND(EXTRACT(EPOCH FROM (jam_pulang - jam_datang))/3600, 2) as total_jam
                FROM absensi
                WHERE user_id=%s AND tanggal=%s
            """, (user_id, wib.date()))
            data = cur.fetchone()
            conn.close()

            jam_datang_str = data[0].strftime('%H:%M:%S')
            jam_pulang_str = data[1].strftime('%H:%M:%S')
            total_jam = data[2]

            await query.edit_message_text(
                text=f"🤖 *Absen Selesai*\n📅 {hari_ini}\n"
                     f"━━━━━━━━━━━━━━\n"
                     f"✅ Datang: {jam_datang_str}\n"
                     f"🚪 Pulang: {jam_pulang_str}\n"
                     f"⏱️ Total Jam Kerja: {total_jam} jam\n"
                     f"Absen hari ini sudah selesai terimakasih\n"
                     f"**Tetap semangat**",
                parse_mode='Markdown',
                reply_markup=None
            )

    elif button_id in ['izin', 'sakit', 'cuti']:
        context.user_data['status_izin'] = button_id
        await query.edit_message_text(f"Kirim alasan {button_id}:")
        return REASON

    elif button_id == 'rekap':
        hari_hadir, total_jam, total_telat = get_rekap_bulanan(user_id)
        bulan_nama = datetime.now(WIB).strftime('%B %Y')
        teks = f"📊 *Rekap {bulan_nama}*\n\n"
        teks += f"📅 Hari Hadir: {hari_hadir} hari\n"
        teks += f"⏱️ Total Jam Kerja: {total_jam} jam\n"
        teks += f"⚠️ Telat: {total_telat} kali\n"
        teks += f"Rata-rata: {round(total_jam/hari_hadir, 2) if hari_hadir > 0 else 0} jam/hari"
        await query.edit_message_text(teks, parse_mode='Markdown')

    elif button_id == 'saya':
        data = get_data_saya(user_id)
        if not data:
            await query.edit_message_text("Belum ada data absen 7 hari terakhir.")
            return
        teks = "*📋 Absen 7 Hari Terakhir*\n\n"
        for row in data:
            tanggal, datang, pulang, status, alasan, total_jam = row
            status_text = status or 'hadir'
            teks += f"*{tanggal}*\n"
            teks += f"Datang: {datang.strftime('%H:%M') if datang else '-'}\n"
            teks += f"Pulang: {pulang.strftime('%H:%M') if pulang else '-'}\n"
            teks += f"Status: {status_text}\n"
