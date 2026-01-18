# 🎙️ Twitch Speaker Chat (Neural TTS)

Una aplicación de escritorio moderna que lee el chat de Twitch en voz alta utilizando **Inteligencia Artificial Neuronal** (Edge-TTS). Diseñada para streamers que quieren interactuar con su chat sin leer la pantalla constantemente.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-win)

## ✨ Características

* **🗣️ Voces Neuronales:** Utiliza el motor de Microsoft Edge (gratis) para voces ultra realistas.
* **🎙️ Voz "Valentino":** Configurada por defecto con la voz `es-AR-TomasNeural`, muy similar a la famosa voz de TikTok/CapCut.
* **🎨 Chat Visual:** Interfaz idéntica al chat web de Twitch, con soporte para emblemas (VIP, Mods, Subs).
* **🔒 Seguridad:** El token de acceso se maneja de forma segura y no se expone en texto plano.
* **🧠 Inteligente:** Detecta automáticamente si pegas el token sin el prefijo `oauth:` y lo corrige.
* **💾 Auto-Guardado:** Recuerda tu canal y token para no ingresarlos cada vez.

## 📥 Descarga (Para Usuarios)

Si solo quieres usar la aplicación, no necesitas instalar Python.

1.  Ve a la sección de **[Releases](../../releases)** de este repositorio.
2.  Descarga el archivo `.zip` de la última versión.
3.  Descomprime la carpeta.
4.  Ejecuta `TwitchSpeaker.exe`.

## 🛠️ Instalación (Para Desarrolladores)

Si quieres modificar el código o compilarlo tú mismo:

1.  Clona el repositorio:
    ```bash
    git clone [https://github.com/TU_USUARIO/TwitchSpeaker.git](https://github.com/TU_USUARIO/TwitchSpeaker.git)
    cd TwitchSpeaker
    ```

2.  Instala las dependencias:
    ```bash
    pip install -r requirements.txt
    ```

3.  Ejecuta la aplicación:
    ```bash
    python bot_twitch.py
    ```

## 📦 Crear el Ejecutable (.exe)

Para compilar tu propia versión:

```bash
python -m PyInstaller --noconsole --name="TwitchSpeaker" --icon="tu_icono.ico" bot_twitch.py
