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

# --- VARIABLES GLOBALES ---
configuracion = {"token": "", "canal": ""}
cola_tts = queue.Queue()
window = None
VOCES_DISPONIBLES = {}
VOZ_ACTUAL_ID = "es-AR-TomasNeural" 
bot_instancia = None 

# ==========================================
#    1. GESTIÓN DE AUDIO
# ==========================================
def cargar_config():
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                return json.load(f)
    except: pass
    return {"token": "", "canal": ""}

def guardar_config(token, canal):
    with open("config.json", "w") as f:
        json.dump({"token": token, "canal": canal}, f)

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
        # Quitamos emojis del print para evitar errores en el .exe
        print(f"Error cargando voces Edge: {e}")

async def generar_audio_edge(texto, voz, archivo_salida="temp_tts.mp3"):
    communicate = edge_tts.Communicate(texto, voz)
    await communicate.save(archivo_salida)

def proceso_audio():
    pygame.mixer.init()
    asyncio.run(obtener_voces_edge())
    
    while True:
        try:
            texto = cola_tts.get()
            voz_a_usar = VOZ_ACTUAL_ID if VOZ_ACTUAL_ID else "es-MX-DaliaNeural"
            
            asyncio.run(generar_audio_edge(texto, voz_a_usar))
            
            pygame.mixer.music.load("temp_tts.mp3")
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            pygame.mixer.music.unload()
            
            cola_tts.task_done()
        except Exception as e:
            print(f"Error en audio: {e}")

# ==========================================
#    2. PUENTE PYTHON <-> JS
# ==========================================
def enviar_a_web_seguro(tipo_evento, datos):
    if window:
        try:
            json_str = json.dumps(datos)
            b64_str = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
            script = f"recibirEventoBase64('{tipo_evento}', '{b64_str}')"
            window.evaluate_js(script)
        except Exception as e:
            print(f"Error enviando a web: {e}")

# ==========================================
#    3. BOT TWITCH
# ==========================================
class BotTwitch(commands.Bot):
    def __init__(self, token, canal):
        super().__init__(token=token, prefix='!', initial_channels=[canal])
        self.canal_nombre = canal

    async def event_ready(self):
        # Print limpio sin emojis para evitar crash en .exe
        print(f'Conectado a Twitch: {self.nick}')
        cola_tts.put(f"Conectado al canal {self.canal_nombre}")
        enviar_a_web_seguro("CONEXION_EXITOSA", {'nick': self.nick, 'canal': self.canal_nombre})

    async def event_message(self, message):
        if message.echo or not message.author: return
        if message.content.startswith('!'): return

        badges_list = []
        if 'broadcaster' in message.author.badges: badges_list.append('broadcaster')
        if message.author.is_mod: badges_list.append('mod')
        if 'vip' in message.author.badges: badges_list.append('vip')
        if message.author.is_subscriber: badges_list.append('sub')

        datos = {
            'username': message.author.name,
            'message': message.content,
            'color': message.author.color,
            'badges': badges_list
        }
        enviar_a_web_seguro("NUEVO_MENSAJE", datos)
        cola_tts.put(f"{message.author.name} dice: {message.content}")

    async def event_error(self, error: Exception, data: str = None):
        enviar_a_web_seguro("ERROR_SISTEMA", {'msg': str(error)})

def arrancar_twitch_thread(token, canal):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # --- AUTO-CORRECCIÓN DEL TOKEN ---
    # 1. Quitamos espacios en blanco al principio o final
    token = token.strip()
    # 2. Si el usuario NO puso 'oauth:', se lo ponemos nosotros
    if not token.startswith('oauth:'):
        token = f'oauth:{token}'
    # ---------------------------------

    try:
        bot = BotTwitch(token, canal)
        loop.run_until_complete(bot.run())
    except Exception as e:
        enviar_a_web_seguro("ERROR_SISTEMA", {'msg': f"Fallo al conectar: {str(e)}"})

# ==========================================
#    4. API
# ==========================================
class Api:
    def intentar_login(self, canal, token):
        print(f"Conectando a {canal}...")
        guardar_config(token, canal)
        threading.Thread(target=arrancar_twitch_thread, args=(token, canal), daemon=True).start()
        
    def obtener_config_guardada(self):
        return cargar_config()

    def obtener_voces(self):
        return list(VOCES_DISPONIBLES.keys())

    def cambiar_voz(self, nombre):
        global VOZ_ACTUAL_ID
        if nombre in VOCES_DISPONIBLES:
            VOZ_ACTUAL_ID = VOCES_DISPONIBLES[nombre]
            print(f"Voz cambiada a: {VOZ_ACTUAL_ID}")

    def abrir_navegador(self, url):
        webbrowser.open(url)

    def cerrar_app(self):
        window.destroy()

# ==========================================
#    5. HTML WEBVIEW
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
    body { background-color: #18181b; color: #efeff1; font-family: 'Segoe UI', sans-serif; margin: 0; height: 100vh; overflow: hidden; }
    
    #login-screen { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; width: 100%; position: absolute; background: #0e0e10; z-index: 100; transition: opacity 0.5s; }
    .login-box { width: 300px; padding: 20px; background: #1f1f23; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
    h2 { text-align: center; color: #a970ff; }
    
    label { display: block; margin-bottom: 5px; font-size: 12px; color: #adadb8; }
    input { width: 100%; padding: 10px; margin-bottom: 15px; background: #0e0e10; color: white; border: 1px solid #333; border-radius: 4px; box-sizing: border-box;}
    
    .btn-main { width: 100%; padding: 10px; background: #9147ff; color: white; border: none; font-weight: bold; border-radius: 4px; cursor: pointer; }
    .btn-main:hover { background: #772ce8; }
    
    .token-link { text-align: right; margin-top: -10px; margin-bottom: 15px; font-size: 11px; }
    .token-link a { color: #00db84; text-decoration: none; cursor: pointer; }
    .token-link a:hover { text-decoration: underline; }

    #msgError { color: #ff4f4d; font-size: 12px; margin-top: 10px; text-align: center; min-height: 15px;}
    
    #app-screen { display: none; flex-direction: column; height: 100%; }
    #controls { background: #1f1f23; padding: 10px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid #000; }
    select { background: #3a3a3d; color: white; border: none; padding: 5px; border-radius: 4px; flex-grow: 1; }
    
    .btn-salir { background: transparent; border: 1px solid #ff4f4d; color: #ff4f4d; cursor: pointer; padding: 5px 15px; border-radius: 4px; font-weight: bold; transition: 0.2s; }
    .btn-salir:hover { background: #ff4f4d; color: white; }

    #chat-container { flex-grow: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; justify-content: flex-end; }
    .chat-line { padding: 4px 10px; line-height: 1.5; animation: fadein 0.3s; margin-bottom: 2px; }
    .username { font-weight: 700; margin-right: 5px; }
    .badge-img { height: 18px; vertical-align: middle; margin-right: 4px; }
    ::-webkit-scrollbar { width: 8px; background: #18181b; }
    ::-webkit-scrollbar-thumb { background: #3a3a3d; border-radius: 4px; }
    @keyframes fadein { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
</style>
</head>
<body>
    <div id="login-screen">
        <div class="login-box">
            <h2>Configuración</h2>
            
            <label>Nombre del Canal</label>
            <input type="text" id="inpCanal" placeholder="Ej: ibai">
            
            <label>Token de Acceso</label>
            <input type="password" id="inpToken" placeholder="Pega tu token (ej: 4g72...)">
            
            <div class="token-link">
                <a onclick="abrirLinkToken()">🔑 ¿No tienes token? Obtenlo aquí</a>
            </div>

            <button class="btn-main" id="btnLogin" onclick="login()">CONECTAR</button>
            <div id="msgError"></div>
        </div>
    </div>

    <div id="app-screen">
        <div id="controls">
            <span style="font-weight: bold; color: #a970ff;">VOZ:</span>
            <select id="voiceSelect" onchange="cambiarVoz()">
                <option>Cargando voces...</option>
            </select>
            <button class="btn-salir" onclick="cerrarAplicacion()">SALIR</button>
        </div>
        <div id="chat-container">
            <div class="chat-line" style="color:gray">Conectado. Esperando mensajes...</div>
        </div>
    </div>
<script>
    window.addEventListener('pywebviewready', function() {
        pywebview.api.obtener_config_guardada().then(cfg => {
            if(cfg.canal) document.getElementById('inpCanal').value = cfg.canal;
            if(cfg.token) document.getElementById('inpToken').value = cfg.token;
        });
        setTimeout(() => { cargarListaVoces(); }, 2000);
    });

    function cargarListaVoces() {
        pywebview.api.obtener_voces().then(voces => {
            const sel = document.getElementById('voiceSelect');
            if(voces.length > 0) {
                sel.innerHTML = "";
                voces.forEach(v => {
                    let opt = document.createElement('option');
                    opt.value = v; opt.text = v;
                    if(v.includes("Tomas")) opt.selected = true;
                    sel.appendChild(opt);
                });
            } else { setTimeout(cargarListaVoces, 1000); }
        });
    }

    function abrirLinkToken() { pywebview.api.abrir_navegador('https://twitchtokengenerator.com'); }
    function cerrarAplicacion() { pywebview.api.cerrar_app(); }

    function login() {
        const canal = document.getElementById('inpCanal').value.trim().toLowerCase();
        const token = document.getElementById('inpToken').value.trim();
        if(!canal || !token) { document.getElementById('msgError').innerText = "Faltan datos"; return; }
        document.getElementById('btnLogin').disabled = true;
        document.getElementById('btnLogin').innerText = "CONECTANDO...";
        pywebview.api.intentar_login(canal, token);
    }

    function recibirEventoBase64(tipo, base64Str) {
        try { gestionarEventos(tipo, JSON.parse(atob(base64Str))); } catch (e) { console.error(e); }
    }

    function gestionarEventos(tipo, datos) {
        if (tipo === "CONEXION_EXITOSA") {
            const login = document.getElementById('login-screen');
            login.style.opacity = '0';
            setTimeout(() => { login.style.display = 'none'; document.getElementById('app-screen').style.display = 'flex'; }, 500);
        } else if (tipo === "ERROR_SISTEMA") {
            document.getElementById('btnLogin').disabled = false;
            document.getElementById('btnLogin').innerText = "CONECTAR";
            document.getElementById('msgError').innerText = datos.msg;
        } else if (tipo === "NUEVO_MENSAJE") {
            agregarMensajeChat(datos);
        }
    }

    function agregarMensajeChat(datos) {
        const container = document.getElementById('chat-container');
        const div = document.createElement('div');
        div.className = 'chat-line';
        if (datos.badges) {
            datos.badges.forEach(b => {
                const img = document.createElement('img');
                img.src = b + '.png'; img.className = 'badge-img';
                img.onerror = function(){ this.style.display='none' };
                div.appendChild(img);
            });
        }
        const name = document.createElement('span');
        name.className = 'username';
        name.innerText = datos.username;
        name.style.color = datos.color || '#a970ff';
        div.appendChild(name);
        div.appendChild(document.createTextNode(': '));
        const msg = document.createElement('span');
        msg.className = 'message-text';
        msg.innerText = datos.message;
        div.appendChild(msg);
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    function cambiarVoz() { pywebview.api.cambiar_voz(document.getElementById('voiceSelect').value); }
</script>
</body>
</html>
"""

if __name__ == "__main__":
    threading.Thread(target=proceso_audio, daemon=True).start()
    api = Api()
    # Sin debug para la versión final
    window = webview.create_window("TTV SPEAKER BY PARDOSO", html=HTML_TEMPLATE, js_api=api, width=400, height=600, background_color='#0e0e10')
    webview.start()