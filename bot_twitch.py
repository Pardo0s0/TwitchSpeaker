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
import time
import uuid
import requests  # <--- NUEVO: Para descargar emotes de 7TV
from twitchio.ext import commands
from TikTokLive import TikTokLiveClient

# Intentamos importar audio avanzado
try:
    import pygame._sdl2.audio as sdl2_audio
except ImportError:
    sdl2_audio = None

# --- VARIABLES GLOBALES ---
configuracion = {
    "platform": "twitch", "channel": "", "token": "", "tiktok_user": "",
    "read_bots": True, "read_streamer": True,
    "volume": 1.0, "audio_device": None
}

cola_tts = queue.Queue()
window = None
VOCES_DISPONIBLES = {}
VOZ_ACTUAL_ID = "es-AR-TomasNeural" 
bot_instancia = None 
tiktok_client = None

# DICCIONARIO DE EMOTES (Nombre -> URL Imagen)
EMOTES_MAP = {} 

# --- FILTROS ---
BOTS_COMUNES = ["nightbot", "streamelements", "streamlabs", "moobot", "wizebot"]

# ==========================================
#    1. GESTOR DE EMOTES (NUEVO)
# ==========================================
def cargar_emotes_7tv(canal_twitch):
    """Descarga los emotes de 7TV/BTTV para el canal"""
    global EMOTES_MAP
    EMOTES_MAP = {} # Limpiar
    
    print(f"🔄 Cargando emotes para: {canal_twitch}...")
    
    # 1. Obtener ID numérico del usuario de Twitch (Necesario para 7TV)
    try:
        # Usamos una API pública para sacar el ID rápido sin tokens complejos
        r_id = requests.get(f"https://api.ivr.fi/v2/twitch/user?login={canal_twitch}")
        if r_id.status_code != 200: return
        user_data = r_id.json()
        if not user_data: return
        twitch_id = user_data[0]['id']
        
        # 2. Obtener Emotes Globales de 7TV
        r_global = requests.get("https://7tv.io/v3/emote-sets/global")
        if r_global.status_code == 200:
            data = r_global.json()
            for emote in data.get('emotes', []):
                nombre = emote['name']
                # Usamos la versión webp 2x
                url = f"https://cdn.7tv.app/emote/{emote['id']}/2x.webp"
                EMOTES_MAP[nombre] = url

        # 3. Obtener Emotes del Canal de 7TV
        r_channel = requests.get(f"https://7tv.io/v3/users/twitch/{twitch_id}")
        if r_channel.status_code == 200:
            data = r_channel.json()
            emote_set = data.get('emote_set', {})
            for emote in emote_set.get('emotes', []):
                nombre = emote['name']
                url = f"https://cdn.7tv.app/emote/{emote['id']}/2x.webp"
                EMOTES_MAP[nombre] = url
                
        print(f"✅ Se cargaron {len(EMOTES_MAP)} emotes de 7TV/BTTV.")
        
    except Exception as e:
        print(f"⚠️ Error cargando emotes: {e}")

def procesar_texto_visual(texto, twitch_emotes_raw=None):
    """
    Convierte el texto plano en HTML con imágenes.
    Prioridad: 1. Emotes Nativos Twitch, 2. Emotes 7TV/BTTV
    """
    palabras = texto.split(" ")
    html_output = []
    
    # Mapa de posiciones de emotes nativos de Twitch
    # Formato Twitch: "emotes": "25:0-4,12-16/1902:6-10"
    twitch_map = {}
    if twitch_emotes_raw:
        raw_split = twitch_emotes_raw.split("/")
        for e in raw_split:
            if ":" in e:
                id_emote, posiciones = e.split(":")
                for pos in posiciones.split(","):
                    start, end = map(int, pos.split("-"))
                    code = texto[start:end+1]
                    url = f"https://static-cdn.jtvnw.net/emoticons/v2/{id_emote}/default/dark/2.0"
                    twitch_map[code] = url

    for palabra in palabras:
        # 1. Checar si es Emote Nativo
        if palabra in twitch_map:
            html_output.append(f'<img src="{twitch_map[palabra]}" class="emote" alt="{palabra}">')
        
        # 2. Checar si es Emote 7TV/BTTV
        elif palabra in EMOTES_MAP:
            html_output.append(f'<img src="{EMOTES_MAP[palabra]}" class="emote" alt="{palabra}">')
            
        # 3. Texto normal
        else:
            # Escapar HTML básico para seguridad
            safe_word = palabra.replace("<", "&lt;").replace(">", "&gt;")
            html_output.append(safe_word)
            
    return " ".join(html_output)

# ==========================================
#    2. GESTIÓN DE AUDIO (V5.0)
# ==========================================
def cargar_config():
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f: return json.load(f)
    except: pass
    return configuracion

def guardar_config(datos):
    global configuracion
    configuracion.update(datos)
    with open("config.json", "w") as f: json.dump(configuracion, f)

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
    except: pass

def listar_dispositivos_audio():
    devices = ["Default System Device"]
    if sdl2_audio:
        try:
            if not pygame.get_init(): pygame.init()
            if not pygame.mixer.get_init(): pygame.mixer.init()
            devs = sdl2_audio.get_audio_device_names(False)
            if devs: devices = devs
        except: pass
    return devices

async def generar_audio_edge(texto, voz, archivo_salida):
    communicate = edge_tts.Communicate(texto, voz)
    await communicate.save(archivo_salida)

def proceso_audio():
    pygame.mixer.init()
    asyncio.run(obtener_voces_edge())
    
    cfg = cargar_config()
    dev = cfg.get("audio_device", None)
    if dev and sdl2_audio:
        try: pygame.mixer.quit(); pygame.mixer.init(devicename=dev)
        except: pygame.mixer.init()

    while True:
        archivo_temp = ""
        try:
            texto = cola_tts.get()
            
            if texto.startswith("CMD_CHANGE_DEVICE:"):
                new_dev = texto.split(":", 1)[1]
                try: pygame.mixer.quit(); pygame.mixer.init(devicename=new_dev if new_dev != "Default System Device" else None)
                except: pygame.mixer.init()
                cola_tts.task_done(); continue
            
            voz = VOZ_ACTUAL_ID if VOZ_ACTUAL_ID else "es-MX-DaliaNeural"
            archivo_temp = f"tts_{uuid.uuid4().hex}.mp3"
            
            asyncio.run(generar_audio_edge(texto, voz, archivo_temp))
            
            try:
                snd = pygame.mixer.Sound(archivo_temp)
                snd.set_volume(float(configuracion.get("volume", 1.0)))
                ch = snd.play()
                if ch: 
                    while ch.get_busy(): pygame.time.Clock().tick(10)
            except Exception as e: print(f"Error play: {e}")
            
            cola_tts.task_done()
        except Exception as e:
            print(f"Error loop: {e}")
            cola_tts.task_done()
        finally:
            if archivo_temp and os.path.exists(archivo_temp):
                try: os.remove(archivo_temp)
                except: pass

# ==========================================
#    3. LOGICA BOTS
# ==========================================
def enviar_a_web_seguro(tipo, datos):
    if window:
        try:
            j = json.dumps(datos)
            b64 = base64.b64encode(j.encode('utf-8')).decode('utf-8')
            window.evaluate_js(f"recibirEventoBase64('{tipo}', '{b64}')")
        except: pass

def procesar_mensaje_tts(usuario, mensaje, es_streamer):
    if es_streamer and not configuracion.get('read_streamer', True): return
    if not configuracion.get('read_bots', False) and usuario.lower() in BOTS_COMUNES: return
    cola_tts.put(f"{usuario} dice: {mensaje}")

class BotTwitch(commands.Bot):
    def __init__(self, token, canal):
        super().__init__(token=token, prefix='!', initial_channels=[canal])
        self.canal_nombre = canal

    async def event_ready(self):
        print(f'Twitch: {self.nick}')
        # CARGAMOS EMOTES AL INICIAR
        threading.Thread(target=cargar_emotes_7tv, args=(self.canal_nombre,)).start()
        
        enviar_a_web_seguro("CONEXION_EXITOSA", {'platform': 'Twitch', 'canal': self.canal_nombre})
        cola_tts.put("Conectado a Twitch")

    async def event_message(self, message):
        if message.echo or not message.author: return
        
        # 1. Preparar visual (HTML con emotes)
        # TwitchIO nos da los tags de emotes crudos en message.tags['emotes']
        emotes_raw = message.tags.get('emotes', None)
        mensaje_visual_html = procesar_texto_visual(message.content, emotes_raw)

        badges = []
        if 'broadcaster' in message.author.badges: badges.append('broadcaster')
        if message.author.is_mod: badges.append('mod')
        if message.author.is_subscriber: badges.append('sub')
        
        enviar_a_web_seguro("NUEVO_MENSAJE", {
            'username': message.author.name, 
            'message': mensaje_visual_html, # ENVIAMOS EL HTML PROCESADO
            'color': message.author.color, 
            'badges': badges
        })
        
        # 2. Enviar audio (Texto plano)
        es_streamer = (message.author.name.lower() == self.canal_nombre.lower())
        procesar_mensaje_tts(message.author.name, message.content, es_streamer)

def arrancar_tiktok(username):
    global tiktok_client
    from TikTokLive import TikTokLiveClient
    try: from TikTokLive.types.events import CommentEvent, ConnectEvent
    except ImportError: from TikTokLive.events import CommentEvent, ConnectEvent

    tiktok_client = TikTokLiveClient(unique_id=f"@{username}")

    @tiktok_client.on(ConnectEvent)
    async def on_connect(event: ConnectEvent):
        enviar_a_web_seguro("CONEXION_EXITOSA", {'platform': 'TikTok', 'canal': username})
        cola_tts.put("Conectado a TikTok")

    @tiktok_client.on(CommentEvent)
    async def on_comment(event: CommentEvent):
        badges = []
        if event.user.is_moderator: badges.append('mod')
        
        # TikTok no tiene sistema de emotes 7tv, asi que texto plano
        enviar_a_web_seguro("NUEVO_MENSAJE", {
            'username': event.user.nickname, 
            'message': event.comment, 
            'color': '#ff0050', 'badges': badges
        })
        
        es_streamer = (event.user.unique_id == username)
        procesar_mensaje_tts(event.user.nickname, event.comment, es_streamer)

    try: tiktok_client.run()
    except Exception as e: enviar_a_web_seguro("ERROR_SISTEMA", {'msg': f"Error TikTok: {e}"})

def thread_twitch(token, canal):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if not token.startswith('oauth:'): token = f'oauth:{token}'
    try:
        bot = BotTwitch(token, canal)
        loop.run_until_complete(bot.run())
    except Exception as e: enviar_a_web_seguro("ERROR_SISTEMA", {'msg': f"Error Twitch: {e}"})

def thread_tiktok(username): arrancar_tiktok(username)

# ==========================================
#    4. API CONTROLADOR
# ==========================================
class Api:
    def login(self, datos):
        global configuracion
        if 'volume' in datos: datos['volume'] = float(datos['volume'])
        configuracion.update(datos)
        guardar_config(configuracion)
        
        if datos['platform'] == 'twitch':
            threading.Thread(target=thread_twitch, args=(datos['token'], datos['channel']), daemon=True).start()
        else:
            threading.Thread(target=thread_tiktok, args=(datos['tiktok_user'],), daemon=True).start()

    def obtener_config(self):
        global configuracion
        configuracion.update(cargar_config())
        return configuracion

    def obtener_voces(self): return list(VOCES_DISPONIBLES.keys())
    def obtener_dispositivos_audio(self): return listar_dispositivos_audio()
    def cambiar_voz(self, nombre):
        global VOZ_ACTUAL_ID
        if nombre in VOCES_DISPONIBLES: VOZ_ACTUAL_ID = VOCES_DISPONIBLES[nombre]

    def abrir_url(self, url): webbrowser.open(url)
    def cerrar(self): window.destroy()
    def actualizar_volumen_live(self, v): configuracion['volume'] = float(v)
    def guardar_ajustes_audio(self, v, d):
        configuracion['volume'] = float(v)
        configuracion['audio_device'] = d
        guardar_config(configuracion)
        if d: cola_tts.put(f"CMD_CHANGE_DEVICE:{d}")
    def probar_audio(self): cola_tts.put("Prueba de audio.")

# ==========================================
#    5. HTML / JS / CSS (CON SOPORTE IMG)
# ==========================================
HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
    body { background-color: #18181b; color: white; font-family: 'Segoe UI', sans-serif; margin: 0; height: 100vh; overflow: hidden; }
    
    /* ESTILOS DE EMOTES */
    .emote {
        height: 28px;
        vertical-align: middle;
        margin: -4px 2px;
        display: inline-block;
    }

    #settings-modal { display: none; position: absolute; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.8); z-index: 50; align-items: center; justify-content: center; }
    .settings-box { width: 80%; background: #1f1f23; padding: 20px; border-radius: 8px; box-shadow: 0 0 20px rgba(0,0,0,0.8); }
    .settings-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid #333; padding-bottom: 10px; }
    .settings-title { font-weight: bold; font-size: 18px; color: #a970ff; }
    .close-btn { background: none; border: none; color: white; font-size: 20px; cursor: pointer; }
    
    label { display: block; font-size: 12px; color: #adadb8; margin: 10px 0 5px; }
    input[type="range"] { width: 100%; cursor: pointer; accent-color: #a970ff; }
    select, input[type="text"], input[type="password"] { width: 100%; padding: 8px; background: #0e0e10; border: 1px solid #333; border-radius: 5px; color: white; box-sizing: border-box; }
    .btn-save { width: 100%; padding: 10px; background: #00db84; border: none; font-weight: bold; color: black; border-radius: 5px; cursor: pointer; margin-top: 15px; }
    .btn-test { padding: 5px 10px; background: #555; border: none; color: white; border-radius: 3px; cursor: pointer; font-size: 11px; float: right;}

    #login-screen { position: absolute; width: 100%; height: 100%; background: #0e0e10; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 10; transition: 0.5s; }
    .box { width: 320px; padding: 25px; background: #1f1f23; border-radius: 10px; box-shadow: 0 5px 20px rgba(0,0,0,0.5); }
    .chk-group { display: flex; gap: 15px; margin-top: 15px; }
    .chk-item { display: flex; align-items: center; font-size: 13px; gap: 5px; cursor: pointer; }
    .main-btn { width: 100%; padding: 12px; background: #9147ff; border: none; font-weight: bold; color: white; border-radius: 5px; cursor: pointer; margin-top: 20px; }
    
    #app-screen { display: none; flex-direction: column; height: 100%; }
    #header { padding: 10px; background: #1f1f23; display: flex; gap: 10px; border-bottom: 1px solid #000; align-items: center; }
    #chat-box { flex-grow: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; justify-content: flex-end; }
    .msg { padding: 5px 10px; animation: fade 0.3s; margin-bottom: 4px; border-radius: 4px; word-wrap: break-word; }
    .msg:hover { background: #26262c; }
    .badge { height: 16px; vertical-align: middle; margin-right: 4px; }
    .user { font-weight: bold; margin-right: 5px; }
    .icon-btn { background: none; border: none; color: #adadb8; cursor: pointer; font-size: 18px; padding: 5px; }
    .icon-btn:hover { color: white; }

    @keyframes fade { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
    ::-webkit-scrollbar { width: 8px; background: #18181b; }
    ::-webkit-scrollbar-thumb { background: #444; border-radius: 4px; }
</style>
</head>
<body>

<div id="settings-modal">
    <div class="settings-box">
        <div class="settings-header"><span class="settings-title">Configuración de Audio</span><button class="close-btn" onclick="toggleSettings()">×</button></div>
        <label>Volumen (<span id="vol-val">100%</span>) <button class="btn-test" onclick="pywebview.api.probar_audio()">🔊 Probar</button></label>
        <input type="range" id="volRange" min="0" max="1" step="0.05" value="1" oninput="updateVolText()" onchange="sendVolToPython()">
        <label>Dispositivo de Salida</label>
        <select id="audioDeviceSel"></select>
        <button class="btn-save" onclick="saveAudioSettings()">Guardar y Cerrar</button>
    </div>
</div>

<div id="login-screen">
    <div class="box" id="loginBox">
        <h2 style="text-align:center;color:#a970ff;margin:0;">Configuración</h2>
        <label>Plataforma</label>
        <select id="selPlatform" onchange="togglePlatform()">
            <option value="twitch">Twitch</option>
            <option value="tiktok">TikTok Live</option>
        </select>
        <div id="twitchInputs">
            <label>Canal</label><input type="text" id="twChannel" placeholder="ej: ibai">
            <label>Token <a href="#" onclick="pywebview.api.abrir_url('https://twitchtokengenerator.com')" style="color:#00db84;text-decoration:none;">(Link)</a></label>
            <input type="password" id="twToken" placeholder="oauth:...">
        </div>
        <div id="tiktokInputs" style="display:none;"><label>Usuario TikTok</label><input type="text" id="ttUser" placeholder="ej: elmariana"></div>
        <div class="chk-group">
            <label class="chk-item"><input type="checkbox" id="chkStreamer" checked> Leer Streamer</label>
            <label class="chk-item"><input type="checkbox" id="chkBots"> Leer Bots</label>
        </div>
        <button id="btnConnect" class="main-btn" onclick="connect()">CONECTAR</button>
        <div id="errorMsg" style="color:#ff4f4d; text-align:center; font-size:12px; margin-top:10px;"></div>
    </div>
</div>

<div id="app-screen">
    <div id="header">
        <select id="voiceSelect" onchange="pywebview.api.cambiar_voz(this.value)" style="width: 140px;"></select>
        <button class="icon-btn" onclick="toggleSettings()" title="Configuración">⚙️</button>
        <button style="margin-left:auto; padding:5px 10px; background:transparent; border:1px solid #ff4f4d; color:#ff4f4d; cursor:pointer;" onclick="pywebview.api.cerrar()">SALIR</button>
    </div>
    <div id="chat-box"><div style="color:gray; padding:10px;">Esperando conexión...</div></div>
</div>

<script>
    let config = {};
    window.addEventListener('pywebviewready', () => {
        pywebview.api.obtener_config().then(cfg => {
            config = cfg;
            if(cfg.platform) document.getElementById('selPlatform').value = cfg.platform;
            if(cfg.channel) document.getElementById('twChannel').value = cfg.channel;
            if(cfg.token) document.getElementById('twToken').value = cfg.token;
            if(cfg.tiktok_user) document.getElementById('ttUser').value = cfg.tiktok_user;
            document.getElementById('chkStreamer').checked = cfg.read_streamer !== false;
            document.getElementById('chkBots').checked = cfg.read_bots === true;
            if(cfg.volume !== undefined) { document.getElementById('volRange').value = cfg.volume; updateVolText(); }
            togglePlatform(); cargarVoces(); cargarDispositivosAudio();
        });
    });

    function toggleSettings() {
        const modal = document.getElementById('settings-modal');
        modal.style.display = (modal.style.display === 'flex') ? 'none' : 'flex';
    }
    function updateVolText() { document.getElementById('vol-val').innerText = Math.round(document.getElementById('volRange').value * 100) + '%'; }
    function sendVolToPython() { pywebview.api.actualizar_volumen_live(document.getElementById('volRange').value); }
    function cargarDispositivosAudio() {
        pywebview.api.obtener_dispositivos_audio().then(devs => {
            const sel = document.getElementById('audioDeviceSel');
            sel.innerHTML = "";
            devs.forEach(d => {
                let opt = document.createElement('option'); opt.value = d; opt.text = d;
                if (config.audio_device && d === config.audio_device) opt.selected = true;
                sel.appendChild(opt);
            });
        });
    }
    function saveAudioSettings() {
        pywebview.api.guardar_ajustes_audio(document.getElementById('volRange').value, document.getElementById('audioDeviceSel').value);
        toggleSettings();
    }
    function togglePlatform() {
        const plat = document.getElementById('selPlatform').value;
        document.getElementById('twitchInputs').style.display = (plat==='twitch')?'block':'none';
        document.getElementById('tiktokInputs').style.display = (plat==='tiktok')?'block':'none';
    }
    function cargarVoces() {
        pywebview.api.obtener_voces().then(voces => {
            const sel = document.getElementById('voiceSelect');
            sel.innerHTML = "";
            voces.forEach(v => {
                let opt = document.createElement('option'); opt.value = v; opt.text = v;
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
            read_bots: document.getElementById('chkBots').checked,
            volume: document.getElementById('volRange').value,
            audio_device: document.getElementById('audioDeviceSel').value
        };
        if(plat === 'twitch' && (!data.channel || !data.token)) return showError("Faltan datos");
        if(plat === 'tiktok' && !data.tiktok_user) return showError("Falta usuario");
        document.getElementById('btnConnect').disabled = true; document.getElementById('btnConnect').innerText = "CONECTANDO...";
        pywebview.api.login(data);
    }
    function showError(msg) { document.getElementById('errorMsg').innerText = msg; }
    function recibirEventoBase64(tipo, b64) {
        const data = JSON.parse(atob(b64));
        if(tipo === 'CONEXION_EXITOSA') {
            document.getElementById('login-screen').style.opacity = '0';
            setTimeout(() => { document.getElementById('login-screen').style.display = 'none'; document.getElementById('app-screen').style.display = 'flex'; }, 500);
        } else if(tipo === 'NUEVO_MENSAJE') addMsg(data);
        else if(tipo === 'ERROR_SISTEMA') { alert(data.msg); document.getElementById('btnConnect').disabled = false; document.getElementById('btnConnect').innerText = "CONECTAR"; }
    }
    function addMsg(data) {
        const box = document.getElementById('chat-box');
        const div = document.createElement('div'); div.className = 'msg';
        let badgesHtml = '';
        if(data.badges) data.badges.forEach(b => badgesHtml += `<img src="${b}.png" class="badge" onerror="this.style.display='none'">`);
        // AQUI ESTA EL CAMBIO: data.message AHORA CONTIENE HTML
        div.innerHTML = `${badgesHtml}<span class="user" style="color:${data.color||'#a970ff'}">${data.username}:</span> ${data.message}`;
        box.appendChild(div); box.scrollTop = box.scrollHeight;
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