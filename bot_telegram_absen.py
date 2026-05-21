import os
import threading
import psycopg2
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")

@app_flask.route('/')
def home():
    return "Bot jalan. Buka /absensi untuk lihat data."

@app_flask.route('/absensi')
def absensi_page():
    tanggal = request.args.get('tanggal')

    conn = get_db()
    cur = conn.cursor()

    if tanggal:
        cur.execute("SELECT nama, tanggal, jam_datang, jam_pulang FROM absensi WHERE tanggal=%s ORDER BY jam_datang DESC", (tanggal,))
    else:
        cur.execute("SELECT nama, tanggal, jam_datang, jam_pulang FROM absensi ORDER BY tanggal DESC, jam_datang DESC LIMIT 100")

    data = cur.fetchall()
    conn.close()

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Data Absensi</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }
            h2 { text-align: center; }
            table { width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #4CAF50; color: white; }
            tr:hover { background: #f1f1f1; }
           .filter { text-align: center; margin-bottom: 20px; }
            input, button { padding: 8px; font-size: 16px; }
            @media (max-width: 600px) {
                table, thead, tbody, th, td, tr { display: block; }
                th { display: none; }
                td { border: none; position: relative; padding-left: 50%; }
                td:before {
                    content: attr(data-label);
                    position: absolute;
                    left: 10px;
                    font-weight: bold;
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
                <a href="/absensi"><button type="button">Reset</button></a>
            </form>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Nama</th>
                    <th>Tanggal</th>
                    <th>Jam Datang</th>
                    <th>Jam Pulang</th>
                </tr>
            </thead>
            <tbody>
    """.format(tgl=tanggal if tanggal else "")

    for row in data:
        nama, tanggal, datang, pulang = row
        html += f"""
        <tr>
            <td data-label="Nama">{nama}</td>
            <td data-label="Tanggal">{tanggal}</td>
            <td data-label="Datang">{datang.strftime('%H:%M:%S') if datang else '-'}</td>
            <td data-label="Pulang">{pulang.strftime('%H:%M:%S') if pulang else '-'}</td>
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

def get_keyboard(status):
    if status == 'belum':
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Datang", callback_data='datang'),
             InlineKeyboardButton("🚪 Pulang", callback_data='pulang')]
        ])
    elif status == 'datang':
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🚪 Pulang", callback_data='pulang')]
        ])
    else:
        return None

def cek_absen(user_id):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("SELECT jam_datang, jam_pulang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
    data = cur.fetchone()
    conn.close()
    if not data:
        return 'belum'
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
    try:
        cur.execute("""
            INSERT INTO absensi (user_id, nama, tanggal, jam_datang)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, tanggal) DO NOTHING
        """, (user_id, nama, hari_ini, jam_sekarang))
        conn.commit()
        return True
    except Exception as e:
        print("Error simpan_datang:", e)
        return False
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
        if simpan_datang(user_id, nama):
            await query.edit_message_text(
                text=f"✅ Absen datang berhasil!\nWaktu: {jam}\n\nSilakan absen pulang",
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
            cur.execute("SELECT jam_datang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, wib.date()))
            jam_datang = cur.fetchone()[0]
            conn.close()
            jam_datang_str = jam_datang.strftime('%H:%M:%S')

            await query.edit_message_text(
                text=f"🤖 *Absen Selesai*\n📅 {hari_ini}\n"
                     f"━━━━━━━━━━━━━━\n"
                     f"✅ Datang: {jam_datang_str}\n"
                     f"🚪 Pulang: {jam}\n\n"
                     f"Absensi hari ini sudah selesai\n"
                     f"Tombol akan muncul lagi besok jam 00:00 WIB",
                parse_mode='Markdown',
                reply_markup=None
            )
        else:
            await query.answer("Gagal absen pulang", show_alert=True)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.getenv("TOKEN")
    SUPABASE_URL = os.getenv("SUPABASE_URL")

    if not TOKEN or not SUPABASE_URL:
        print("Error: TOKEN dan SUPABASE_URL harus diset")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS absensi (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            nama TEXT,
            tanggal DATE NOT NULL,
            jam_datang TIME,
            jam_pulang TIME,
            UNIQUE(user_id, tanggal)
        )
    """)
    conn.commit()
    conn.close()
    print("Database siap")

    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot jalan...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()    hari_ini = datetime.now(WIB).date()
    cur.execute("SELECT jam_datang, jam_pulang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
    data = cur.fetchone()
    conn.close()
    if not data:
        return 'belum'
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
    try:
        cur.execute("""
            INSERT INTO absensi (user_id, nama, tanggal, jam_datang)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, tanggal) DO NOTHING
        """, (user_id, nama, hari_ini, jam_sekarang))
        conn.commit()
        return True
    except Exception as e:
        print("Error simpan_datang:", e)
        return False
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
        if simpan_datang(user_id, nama):
            await query.edit_message_text(
                text=f"✅ Absen datang berhasil!\nWaktu: {jam}\n\nSilakan absen pulang",
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
            cur.execute("SELECT jam_datang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, wib.date()))
            jam_datang = cur.fetchone()[0]
            conn.close()
            jam_datang_str = jam_datang.strftime('%H:%M:%S')

            await query.edit_message_text(
                text=f"🤖 *Absen Selesai*\n📅 {hari_ini}\n"
                     f"━━━━━━━━━━━━━━\n"
                     f"✅ Datang: {jam_datang_str}\n"
                     f"🚪 Pulang: {jam}\n\n"
                     f"Absensi hari ini sudah selesai\n"
                     f"Tombol akan muncul lagi besok jam 00:00 WIB",
                parse_mode='Markdown',
                reply_markup=None
            )
        else:
            await query.answer("Gagal absen pulang", show_alert=True)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.getenv("TOKEN")
    SUPABASE_URL = os.getenv("SUPABASE_URL")

    if not TOKEN or not SUPABASE_URL:
        print("Error: TOKEN dan SUPABASE_URL harus diset")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS absensi (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            nama TEXT,
            tanggal DATE NOT NULL,
            jam_datang TIME,
            jam_pulang TIME,
            UNIQUE(user_id, tanggal)
        )
    """)
    conn.commit()
    conn.close()
    print("Database siap")

    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot jalan...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
