import webview
import threading
import queue
import pygame
import asyncio
import json
import os
import base64
import edge_tts
import webbrowser
from twitchio.ext import commands
from TikTokLive import TikTokLiveClient

try:
    from TikTokLive.types.events import CommentEvent, ConnectEvent
except ImportError:
    # Soporte para versiones mixtas/anteriores
    from TikTokLive.events import CommentEvent, ConnectEvent

# --- VARIABLES GLOBALES ---
configuracion = {
    "platform": "twitch", "channel": "", "token": "", "tiktok_user": "",
    "read_bots": True, "read_streamer": True
}
cola_tts = queue.Queue()
window = None
VOCES_DISPONIBLES = {}
VOZ_ACTUAL_ID = "es-AR-TomasNeural" 
bot_instancia = None 
tiktok_client = None

# Lista de bots comunes (para filtrar)
BOTS_COMUNES = ["nightbot", "streamelements", "streamlabs", "moobot", "wizebot"]

# ==========================================
#    1. GESTIÓN DE AUDIO Y CONFIG
# ==========================================
def cargar_config():
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                return json.load(f)
    except: pass
    return configuracion

def guardar_config(datos):
    with open("config.json", "w") as f:
        json.dump(datos, f)

async def obtener_voces_edge():
    global VOCES_DISPONIBLES, VOZ_ACTUAL_ID
    try:
        voces = await edge_tts.list_voices()
        for v in voces:
            if "es-" in v["ShortName"]: 
                nombre_amigable = f"{v['Locale'].split('-')[1]} - {v['ShortName'].split('-')[2].replace('Neural','')}"
                nombre_amigable += f" ({v['Gender']})"
                VOCES_DISPONIBLES[nombre_amigable] = v["ShortName"]
        if VOCES_DISPONIBLES and not VOZ_ACTUAL_ID:
            VOZ_ACTUAL_ID = list(VOCES_DISPONIBLES.values())[0]
    except Exception as e:
        print(f"Error voces: {e}")

async def generar_audio_edge(texto, voz, archivo_salida="temp_tts.mp3"):
    communicate = edge_tts.Communicate(texto, voz)
    await communicate.save(archivo_salida)

def proceso_audio():
    pygame.mixer.init()
    asyncio.run(obtener_voces_edge())
    while True:
        try:
            texto = cola_tts.get()
            voz = VOZ_ACTUAL_ID if VOZ_ACTUAL_ID else "es-MX-DaliaNeural"
            asyncio.run(generar_audio_edge(texto, voz))
            pygame.mixer.music.load("temp_tts.mp3")
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            pygame.mixer.music.unload()
            cola_tts.task_done()
        except Exception as e:
            print(f"Error audio: {e}")

def enviar_a_web_seguro(tipo, datos):
    if window:
        try:
            j = json.dumps(datos)
            b64 = base64.b64encode(j.encode('utf-8')).decode('utf-8')
            window.evaluate_js(f"recibirEventoBase64('{tipo}', '{b64}')")
        except: pass

def procesar_mensaje_tts(usuario, mensaje, es_streamer):
    # --- FILTROS DE CONFIGURACIÓN ---
    cfg = cargar_config()
    
    # 1. Filtro Streamer
    if es_streamer and not cfg.get('read_streamer', True):
        return # No leer
    
    # 2. Filtro Bots
    if cfg.get('read_bots', False) is False:
        if usuario.lower() in BOTS_COMUNES:
            return # No leer

    # Si pasa los filtros, enviar a audio
    cola_tts.put(f"{usuario} dice: {mensaje}")

# ==========================================
#    2. BOT TWITCH
# ==========================================
class BotTwitch(commands.Bot):
    def __init__(self, token, canal):
        super().__init__(token=token, prefix='!', initial_channels=[canal])
        self.canal_nombre = canal

    async def event_ready(self):
        print(f'Twitch Conectado: {self.nick}')
        enviar_a_web_seguro("CONEXION_EXITOSA", {'platform': 'Twitch', 'canal': self.canal_nombre})
        cola_tts.put("Conectado a Twitch")

    async def event_message(self, message):
        if message.echo or not message.author: return
        
        # Enviar a Web (Visual)
        badges = []
        if 'broadcaster' in message.author.badges: badges.append('broadcaster')
        if message.author.is_mod: badges.append('mod')
        if message.author.is_subscriber: badges.append('sub')
        
        datos = {
            'username': message.author.name,
            'message': message.content,
            'color': message.author.color,
            'badges': badges
        }
        enviar_a_web_seguro("NUEVO_MENSAJE", datos)

        # Enviar a Audio (con filtros)
        es_streamer = (message.author.name.lower() == self.canal_nombre.lower())
        procesar_mensaje_tts(message.author.name, message.content, es_streamer)

# ==========================================
#    3. BOT TIKTOK
# ==========================================
def arrancar_tiktok(username):
    global tiktok_client
    # TikTok usa el @usuario para conectar
    tiktok_client = TikTokLiveClient(unique_id=f"@{username}")

    @tiktok_client.on(ConnectEvent)
    async def on_connect(event: ConnectEvent):
        print(f"TikTok Conectado: {event.unique_id}")
        enviar_a_web_seguro("CONEXION_EXITOSA", {'platform': 'TikTok', 'canal': username})
        cola_tts.put("Conectado a TikTok")

    # IMPORTANTE: Solo escuchamos 'CommentEvent'. 
    # Al NO escuchar 'JoinEvent', ignoramos automáticamente a la gente que entra.
    @tiktok_client.on(CommentEvent)
    async def on_comment(event: CommentEvent):
        # Enviar a Web
        badges = []
        if event.user.is_moderator: badges.append('mod')
        # TikTok no tiene "subs" igual que Twitch, pero tiene "Friends" o "Top Gifter"
        # Usaremos iconos genéricos si queremos
        
        datos = {
            'username': event.user.nickname, # Nickname es el nombre visible
            'message': event.comment,
            'color': '#ff0050', # Color rojo TikTok por defecto
            'badges': badges
        }
        enviar_a_web_seguro("NUEVO_MENSAJE", datos)

        # Enviar a Audio
        es_streamer = (event.user.unique_id == username) # unique_id es el @usuario real
        procesar_mensaje_tts(event.user.nickname, event.comment, es_streamer)

    try:
        tiktok_client.run()
    except Exception as e:
        enviar_a_web_seguro("ERROR_SISTEMA", {'msg': f"Error TikTok: {e}"})

# ==========================================
#    4. API Y CONTROLADOR
# ==========================================
def thread_twitch(token, canal):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    token = token.strip()
    if not token.startswith('oauth:'): token = f'oauth:{token}'
    try:
        bot = BotTwitch(token, canal)
        loop.run_until_complete(bot.run())
    except Exception as e:
        enviar_a_web_seguro("ERROR_SISTEMA", {'msg': f"Error Twitch: {e}"})

def thread_tiktok(username):
    # TikTokLive ya maneja su propio loop, no necesita asyncio wrapper complejo aqui
    arrancar_tiktok(username)

class Api:
    def login(self, datos):
        print(f"Conectando a {datos['platform']}...")
        # Guardar configuración completa
        guardar_config(datos)
        
        if datos['platform'] == 'twitch':
            t = threading.Thread(target=thread_twitch, args=(datos['token'], datos['channel']), daemon=True)
            t.start()
        else:
            t = threading.Thread(target=thread_tiktok, args=(datos['tiktok_user'],), daemon=True)
            t.start()

    def obtener_config(self):
        return cargar_config()

    def obtener_voces(self):
        return list(VOCES_DISPONIBLES.keys())

    def cambiar_voz(self, nombre):
        global VOZ_ACTUAL_ID
        if nombre in VOCES_DISPONIBLES:
            VOZ_ACTUAL_ID = VOCES_DISPONIBLES[nombre]

    def abrir_url(self, url): webbrowser.open(url)
    def cerrar(self): window.destroy()

# ==========================================
#    5. HTML / JS / CSS (INTERFAZ)
# ==========================================
HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
    body { background-color: #18181b; color: white; font-family: 'Segoe UI', sans-serif; margin: 0; height: 100vh; overflow: hidden; }
    
    /* LOGIN */
    #login-screen { position: absolute; width: 100%; height: 100%; background: #0e0e10; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 10; transition: 0.5s; }
    .box { width: 320px; padding: 25px; background: #1f1f23; border-radius: 10px; box-shadow: 0 5px 20px rgba(0,0,0,0.5); }
    h2 { text-align: center; color: #a970ff; margin-top: 0; }
    
    label { display: block; font-size: 12px; color: #adadb8; margin: 10px 0 5px; }
    input, select { width: 100%; padding: 10px; background: #0e0e10; border: 1px solid #333; border-radius: 5px; color: white; box-sizing: border-box; }
    
    .chk-group { display: flex; gap: 15px; margin-top: 15px; }
    .chk-item { display: flex; align-items: center; font-size: 13px; gap: 5px; cursor: pointer; }
    
    button { width: 100%; padding: 12px; background: #9147ff; border: none; font-weight: bold; color: white; border-radius: 5px; cursor: pointer; margin-top: 20px; transition: 0.2s; }
    button:hover { background: #772ce8; }
    button:disabled { background: #555; }

    .tiktok-mode h2 { color: #ff0050; }
    .tiktok-mode button { background: #ff0050; }
    .tiktok-mode button:hover { background: #e00045; }

    /* CHAT */
    #app-screen { display: none; flex-direction: column; height: 100%; }
    #header { padding: 10px; background: #1f1f23; display: flex; gap: 10px; border-bottom: 1px solid #000; align-items: center; }
    #chat-box { flex-grow: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; justify-content: flex-end; }
    
    .msg { padding: 5px 10px; animation: fade 0.3s; margin-bottom: 4px; border-radius: 4px; }
    .msg:hover { background: #26262c; }
    .badge { height: 16px; vertical-align: middle; margin-right: 4px; }
    .user { font-weight: bold; margin-right: 5px; }
    
    @keyframes fade { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
    ::-webkit-scrollbar { width: 8px; background: #18181b; }
    ::-webkit-scrollbar-thumb { background: #444; border-radius: 4px; }
</style>
</head>
<body>

<div id="login-screen">
    <div class="box" id="loginBox">
        <h2>Configuración</h2>
        
        <label>Plataforma</label>
        <select id="selPlatform" onchange="togglePlatform()">
            <option value="twitch">Twitch</option>
            <option value="tiktok">TikTok Live</option>
        </select>

        <div id="twitchInputs">
            <label>Canal de Twitch</label>
            <input type="text" id="twChannel" placeholder="ej: ibai">
            <label>Token OAuth <a href="#" onclick="openLink()" style="color:#00db84; font-size:10px; text-decoration:none;">(Obtener)</a></label>
            <input type="password" id="twToken" placeholder="oauth:xxxxx...">
        </div>

        <div id="tiktokInputs" style="display:none;">
            <label>Usuario de TikTok (sin @)</label>
            <input type="text" id="ttUser" placeholder="ej: elmariana">
        </div>

        <div class="chk-group">
            <label class="chk-item"><input type="checkbox" id="chkStreamer" checked> Leer Streamer</label>
            <label class="chk-item"><input type="checkbox" id="chkBots"> Leer Bots</label>
        </div>

        <button id="btnConnect" onclick="connect()">CONECTAR</button>
        <div id="errorMsg" style="color:#ff4f4d; text-align:center; font-size:12px; margin-top:10px;"></div>
    </div>
</div>

<div id="app-screen">
    <div id="header">
        <span style="font-weight:bold;">VOZ:</span>
        <select id="voiceSelect" onchange="pywebview.api.cambiar_voz(this.value)"></select>
        <button style="width:auto; margin:0; padding:5px 15px; background:transparent; border:1px solid #ff4f4d; color:#ff4f4d;" onclick="pywebview.api.cerrar()">SALIR</button>
    </div>
    <div id="chat-box">
        <div style="color:gray; padding:10px;">Esperando conexión...</div>
    </div>
</div>

<script>
    let config = {};

    function togglePlatform() {
        const plat = document.getElementById('selPlatform').value;
        const box = document.getElementById('loginBox');
        
        if(plat === 'twitch') {
            document.getElementById('twitchInputs').style.display = 'block';
            document.getElementById('tiktokInputs').style.display = 'none';
            box.classList.remove('tiktok-mode');
            document.querySelector('h2').innerText = 'Twitch Config';
        } else {
            document.getElementById('twitchInputs').style.display = 'none';
            document.getElementById('tiktokInputs').style.display = 'block';
            box.classList.add('tiktok-mode');
            document.querySelector('h2').innerText = 'TikTok Config';
        }
    }

    function openLink() { pywebview.api.abrir_url('https://twitchtokengenerator.com'); }

    window.addEventListener('pywebviewready', () => {
        pywebview.api.obtener_config().then(cfg => {
            config = cfg;
            if(cfg.platform) document.getElementById('selPlatform').value = cfg.platform;
            if(cfg.channel) document.getElementById('twChannel').value = cfg.channel;
            if(cfg.token) document.getElementById('twToken').value = cfg.token;
            if(cfg.tiktok_user) document.getElementById('ttUser').value = cfg.tiktok_user;
            
            document.getElementById('chkStreamer').checked = cfg.read_streamer !== false;
            document.getElementById('chkBots').checked = cfg.read_bots === true;
            
            togglePlatform();
            cargarVoces();
        });
    });

    function cargarVoces() {
        pywebview.api.obtener_voces().then(voces => {
            const sel = document.getElementById('voiceSelect');
            sel.innerHTML = "";
            voces.forEach(v => {
                let opt = document.createElement('option');
                opt.value = v; opt.text = v;
                if(v.includes("Tomas")) opt.selected = true;
                sel.appendChild(opt);
            });
            if(voces.length === 0) setTimeout(cargarVoces, 1000);
        });
    }

    function connect() {
        const plat = document.getElementById('selPlatform').value;
        const data = {
            platform: plat,
            channel: document.getElementById('twChannel').value.trim(),
            token: document.getElementById('twToken').value.trim(),
            tiktok_user: document.getElementById('ttUser').value.trim(),
            read_streamer: document.getElementById('chkStreamer').checked,
            read_bots: document.getElementById('chkBots').checked
        };

        // Validacion simple
        if(plat === 'twitch' && (!data.channel || !data.token)) return showError("Faltan datos de Twitch");
        if(plat === 'tiktok' && !data.tiktok_user) return showError("Falta usuario de TikTok");

        document.getElementById('btnConnect').disabled = true;
        document.getElementById('btnConnect').innerText = "CONECTANDO...";
        pywebview.api.login(data);
    }

    function showError(msg) { document.getElementById('errorMsg').innerText = msg; }

    function recibirEventoBase64(tipo, b64) {
        const data = JSON.parse(atob(b64));
        if(tipo === 'CONEXION_EXITOSA') {
            document.getElementById('login-screen').style.opacity = '0';
            setTimeout(() => { 
                document.getElementById('login-screen').style.display = 'none';
                document.getElementById('app-screen').style.display = 'flex';
            }, 500);
        } else if(tipo === 'NUEVO_MENSAJE') {
            addMsg(data);
        } else if(tipo === 'ERROR_SISTEMA') {
            alert(data.msg);
            document.getElementById('btnConnect').disabled = false;
            document.getElementById('btnConnect').innerText = "CONECTAR";
        }
    }

    function addMsg(data) {
        const box = document.getElementById('chat-box');
        const div = document.createElement('div');
        div.className = 'msg';
        
        let badgesHtml = '';
        if(data.badges) {
            data.badges.forEach(b => {
                // Usamos imagenes locales si existen, si no, nada
                badgesHtml += `<img src="${b}.png" class="badge" onerror="this.style.display='none'">`;
            });
        }
        
        div.innerHTML = `${badgesHtml}<span class="user" style="color:${data.color||'#a970ff'}">${data.username}:</span> ${data.message}`;
        box.appendChild(div);
        box.scrollTop = box.scrollHeight;
    }
</script>
</body>
</html>
"""

if __name__ == "__main__":
    t_audio = threading.Thread(target=proceso_audio, daemon=True)
    t_audio.start()
    
    api = Api()
    window = webview.create_window("Twitch & TikTok Speaker", html=HTML, js_api=api, width=420, height=650, background_color='#0e0e10')
    webview.start()