import os
import threading
from flask import Flask
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client

TOKEN = os.environ['TOKEN']
SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_KEY']

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app_flask = Flask(__name__)

def get_db():
    return supabase

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("Masuk"), KeyboardButton("Pulang")],
        [KeyboardButton("Izin"), KeyboardButton("Sakit"), KeyboardButton("Cuti")]
    ]
    await update.message.reply_text(
        "Pilih menu absensi:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    now = datetime.now()
    
    data = {
        "user_id": user.id,
        "nama": user.full_name,
        "tanggal": now.date().isoformat(),
        "bulan": now.month,
        "tahun": now.year
    }
    
    if text == "Masuk":
        data["jam_datang"] = now.time().strftime('%H:%M:%S')
        data["status"] = "hadir"
        get_db().table('absensi').upsert(data).execute()
        await update.message.reply_text(f"✅ Absen masuk jam {data['jam_datang']}")
    
    elif text == "Pulang":
        data["jam_pulang"] = now.time().strftime('%H:%M:%S')
        get_db().table('absensi').update({"jam_pulang": data["jam_pulang"]}).eq("user_id", user.id).eq("tanggal", data["tanggal"]).execute()
        await update.message.reply_text(f"✅ Absen pulang jam {data['jam_pulang']}")
    
    elif text in ["Izin", "Sakit", "Cuti"]:
        data["status"] = text.lower()
        get_db().table('absensi').upsert(data).execute()
        await update.message.reply_text(f"✅ Status diubah jadi {text}")

@app_flask.route('/')
def home():
    bulan_sekarang = datetime.now().month
    tahun = datetime.now().year
    
    bulan_id = {
        1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
        5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
        9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
    }
    nama_bulan = bulan_id[bulan_sekarang]

    try:
        data = get_db().table('absensi').select('*').eq('bulan', bulan_sekarang).eq('tahun', tahun).order('tanggal').execute().data
    except:
        data = []

    rows = ""
    for d in data:
        status = d.get('status', 'hadir')
        status_class = f"status-{status}"
        rows += f"<tr><td>{d.get('nama','')}</td><td>{d.get('tanggal','')}</td><td>{d.get('jam_datang','-')}</td><td>{d.get('jam_pulang','-')}</td><td class='{status_class}'>{status}</td><td>-</td></tr>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Absensi {nama_bulan}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ 
                font-family: Arial, sans-serif; 
                padding: 20px; 
                background: #f5f5f5; 
            }}
            h1 {{ 
                color: #333; 
            }}
            table {{ 
                width: 100%; 
                border-collapse: collapse; 
                background: white; 
                box-shadow: 0 2px 5px rgba(0,0,0,0.1); 
            }}
            th, td {{ 
                padding: 12px; 
                text-align: left; 
                border-bottom: 1px solid #ddd; 
            }}
            th {{ 
                background: #4CAF50; 
                color: white; 
            }}
            .status-hadir {{ color: green; font-weight: bold; }}
            .status-izin {{ color: orange; font-weight: bold; }}
            .status-sakit {{ color: red; font-weight: bold; }}
            .status-cuti {{ color: blue; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>Absensi Bulan {nama_bulan} {tahun}</h1>
        <table>
            <tr>
                <th>Nama</th><th>Tanggal</th><th>Datang</th><th>Pulang</th><th>Status</th><th>Total Jam</th>
            </tr>
            {rows}
        </table>
    </body>
    </html>
    """
    return html

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app_flask.run(host='0.0.0.0', port=port)

def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
